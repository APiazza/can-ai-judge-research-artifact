"""Tests that need no API access and no manuscript. Tests on the real inputs are skipped when
config/paths.local.yaml is absent."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness import common, isolation, review
from harness.common import REPO, Paths, load_template, load_yaml, sha256_file
from harness.inputs import load_manuscript
from harness.plans import Slot, expand, load_models, load_plan
from harness.providers import BUILDERS, Call, build_anthropic, build_chat, build_gemini, build_openai
from harness.records import classify, estimate_cost, load_prices, read_jsonl, write_once

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
MANIFEST = load_yaml(REPO / "prompts" / "manifest.yaml")["review"]
REVIEWERS = load_models()["reviewers"]


@pytest.fixture
def fake_inputs(tmp_path) -> Path:
    root = tmp_path / "ai-run-inputs"
    for name, body in (("pilot-v6", "flawed"), ("clean-matched-v6", "clean")):
        d = root / name
        (d / "figures").mkdir(parents=True)
        (d / "manuscript.md").write_text(
            f"# Title\n\nIntro {body}.\n\n![Figure 1](figures/figure_1.png)\n\nMiddle.\n\n"
            f"![Figure 2](figures/figure_2.png)\n\nEnd.\n", encoding="utf-8")
        (d / "figures" / "figure_1.png").write_bytes(PNG + body.encode())
        (d / "figures" / "figure_2.png").write_bytes(PNG + b"2" + body.encode())
        (d / "manuscript.pdf").write_bytes(b"%PDF-1.4\n" + body.encode() + b"\n%%EOF\n")
    return root


def make_paths(inputs: Path, tmp_path: Path, key_hashes=("0" * 64,)) -> Paths:
    return Paths(inputs_dir=inputs.resolve(), data_dir=(tmp_path / "runs").resolve(), keys_file=None,
                 key_sha256=list(key_hashes), operator="TEST", dry_run_dir=(tmp_path / "dry_runs").resolve())


# ---------------------------------------------------------------- templates

@pytest.mark.parametrize("tid", list(MANIFEST))
def test_template_hash_matches_manifest(tid):
    t = load_template("review", tid)
    assert t.sha256 == MANIFEST[tid]["sha256"]
    assert t.text and not t.text.endswith("\n")


def test_edited_template_is_refused(tmp_path, monkeypatch):
    (tmp_path / "prompts" / "review").mkdir(parents=True)
    (tmp_path / "prompts" / "review" / "x_v1.txt").write_text("Review this paper.\n", encoding="utf-8")
    (tmp_path / "prompts" / "manifest.yaml").write_text(
        "review:\n  x_v1:\n    file: review/x_v1.txt\n    sha256: \"" + "a" * 64 + "\"\n", encoding="utf-8")
    monkeypatch.setattr(common, "REPO", tmp_path)
    with pytest.raises(SystemExit, match="Never edit a template in place"):
        load_template("review", "x_v1")


# ---------------------------------------------------------------- inputs

def test_md_figures_places_images_and_keeps_all_text(fake_inputs):
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", "md_figures")
    kinds = [s.kind for s in mi.segments]
    assert kinds == ["text", "image", "text", "image", "text"]
    md = (fake_inputs / "pilot-v6" / "manuscript.md").read_text(encoding="utf-8")
    assert "".join(s.text for s in mi.segments if s.kind == "text") == md
    assert {f["role"] for f in mi.files} == {"manuscript", "figure"} and len(mi.files) == 3


def test_image_link_outside_inputs_is_refused(fake_inputs, tmp_path):
    (tmp_path / "secret.png").write_bytes(PNG)
    md = fake_inputs / "pilot-v6" / "manuscript.md"
    md.write_text("![x](../../secret.png)\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="outside the inputs folder"):
        load_manuscript(fake_inputs.resolve(), "pilot-v6", "md_figures")


# ---------------------------------------------------------------- isolation

def test_isolation_passes_on_clean_inputs(fake_inputs):
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", "pdf")
    result = isolation.check(fake_inputs.resolve(), ["0" * 64], mi.files)
    assert result["passed"] and result["key_path_available_to_review_runner"] is False


def test_isolation_fails_if_key_copy_in_inputs(fake_inputs):
    copy = fake_inputs / "notes.json"
    copy.write_bytes(b'{"C1": "planted"}')
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", "pdf")
    with pytest.raises(SystemExit, match="identical to the answer key"):
        isolation.check(fake_inputs.resolve(), [hashlib.sha256(copy.read_bytes()).hexdigest()], mi.files)


def test_isolation_fails_on_key_named_file(fake_inputs):
    (fake_inputs / "STATUS-P01-pilot-v6-key.md").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="named like a key"):
        isolation.check(fake_inputs.resolve(), ["0" * 64], [])


def test_isolation_fails_on_label_text_in_sent_file(fake_inputs):
    md = fake_inputs / "pilot-v6" / "manuscript.md"
    md.write_text("This is the pilot-v6 copy with a planted flaw.\n", encoding="utf-8")
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", "md_text")
    with pytest.raises(SystemExit, match="label text"):
        isolation.check(fake_inputs.resolve(), ["0" * 64], mi.files)


# ---------------------------------------------------------------- plans

@pytest.mark.parametrize("plan,n", [("main_v1", 480), ("effort_v1", 40), ("format_v1", 20), ("practice_v1", 20),
                                    ("effort_check_v1", 10)])
def test_plan_sizes(plan, n):
    slots = expand(load_plan(REPO / "plans" / f"{plan}.yaml"), REVIEWERS, MANIFEST)
    assert len(slots) == n
    assert [s.slot for s in slots] == list(range(1, n + 1))


def test_main_plan_balances_order_within_model():
    slots = expand(load_plan(REPO / "plans" / "main_v1.yaml"), REVIEWERS, MANIFEST)
    fable = [s for s in slots if s.model_key == "claude-fable-5-1"]
    first = [(s.manuscript, s.template_id) for s in fable[:6]]
    assert first == [(m, t) for m in ("pilot-v6", "clean-matched-v6") for t in ("p1_bare_v1", "p2_reader_v1", "p3_criteria_v1")]
    assert all(s.rep == 1 for s in fable[:6]) and fable[6].rep == 2


def test_every_reviewer_has_construction_tag():
    for k, cfg in REVIEWERS.items():
        assert cfg["construction"] in ("used in construction", "not used in construction"), k
        assert cfg["route"] in BUILDERS, k
        assert cfg.get("effort_default"), k


# ---------------------------------------------------------------- request builders

def _flat(obj) -> str:
    return json.dumps(obj)


@pytest.mark.parametrize("builder,route,fmt", [
    (build_anthropic, "anthropic_api", "pdf"), (build_anthropic, "anthropic_api", "md_figures"),
    (build_openai, "openai_api", "pdf"), (build_gemini, "gemini_api", "pdf"),
    (build_gemini, "gemini_api", "md_figures"), (build_chat, "fireworks_serverless", "md_figures"),
    (build_chat, "fireworks_serverless", "md_text")])
def test_logged_request_has_no_binary_and_prompt_last(fake_inputs, builder, route, fmt):
    cfg = {"model_id": "m", "route": route, "max_output_tokens": 100}
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", fmt)
    call = builder(cfg, mi, "Review this paper.")
    logged, settings = call.request, call.settings
    text = _flat(logged)
    assert "base64," not in text and "JVBER" not in text        # no data URLs, no base64 PDF
    parts = logged["contents"][0]["parts"] if "contents" in logged else (
        logged["messages"][0]["content"] if "messages" in logged else logged["input"][0]["content"])
    assert parts[-1].get("text") == "Review this paper."
    assert len(parts) == len(mi.segments) + 1
    assert settings["temperature"] == "not set (provider default)"


def test_anthropic_cache_breakpoint_after_manuscript(fake_inputs):
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", "pdf")
    call = build_anthropic({"model_id": "m", "route": "anthropic_api", "max_output_tokens": 1}, mi, "P")
    content = call.request["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in content[1]


def test_effort_is_set_only_when_configured(fake_inputs):
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", "pdf")
    base = {"model_id": "gpt-6-astra", "route": "openai_api", "max_output_tokens": 1}
    call = build_openai(base, mi, "P")
    assert "reasoning" not in call.request and call.settings["effort"] == "not set (provider default)"
    call = build_openai({**base, "effort": "max"}, mi, "P")
    assert call.request["reasoning"] == {"effort": "max"} and call.settings["effort"] == "max"
    key = call.request["prompt_cache_key"]
    assert key == "ms-" + mi.files[0]["sha256"][:16] and "pilot" not in key


def test_documented_effort_is_sent_for_claude_and_gemini(fake_inputs):
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", "pdf")
    call = build_anthropic(REVIEWERS["claude-fable-5-1"], mi, "P")
    assert call.request["output_config"] == {"effort": "high"} and call.settings["effort"] == "high"
    call = build_gemini(REVIEWERS["gemini-3-5-flash-lite"], mi, "P")
    assert call.request["config"]["thinking_config"] == {"thinking_level": "MINIMAL"}
    assert REVIEWERS["gemini-4-argon"]["effort"] == "medium" and REVIEWERS["claude-haiku-5-5"]["effort"] == "medium"
    call = build_chat(REVIEWERS["kimi-k3"], load_manuscript(fake_inputs.resolve(), "pilot-v6", "md_figures"), "P")
    assert "reasoning_effort" not in call.request and REVIEWERS["kimi-k3"]["effort_default"] == "provider default, not documented"


def test_chat_route_refuses_pdf(fake_inputs):
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", "pdf")
    with pytest.raises(SystemExit, match="cannot take a PDF"):
        build_chat({"model_id": "m", "route": "fireworks_serverless", "max_output_tokens": 1}, mi, "P")


# ---------------------------------------------------------------- records

def test_write_once_never_overwrites(tmp_path):
    write_once(tmp_path / "a.txt", b"1")
    with pytest.raises(FileExistsError):
        write_once(tmp_path / "a.txt", b"2")
    assert (tmp_path / "a.txt").read_bytes() == b"1"


@pytest.mark.parametrize("stop,text,status", [
    ("end_turn", "ok", "ok"), ("STOP", "ok", "ok"), ("completed", "ok", "ok"), ("max_tokens", "x", "truncated"),
    ("incomplete: max_output_tokens", "x", "truncated"), ("refusal", "", "refused"), ("stop", "  ", "empty")])
def test_classify(stop, text, status):
    assert classify({"stop_reason": stop, "text": text}) == status


def test_cost_estimate():
    prices = load_prices()
    u = {"input_total": 1_000_000, "cached_input": 0, "cache_write": 0, "output_billed": 100_000}
    assert estimate_cost("claude-sonnet-5-5", u, prices)["usd"] == pytest.approx(2.0 + 1.0)
    assert estimate_cost("not-a-model", u, prices)["usd"] == "unknown"
    long = {"input_total": 120_000, "cached_input": 0, "cache_write": 119_000, "output_billed": 6_000}
    expected = (1_000 * 0.50 + 119_000 * 0.125 * 5 + 6_000 * 2.50) / 1e6     # Haiku above 100K: rates x5
    assert estimate_cost("claude-haiku-5-5", long, prices)["usd"] == pytest.approx(expected)


# ---------------------------------------------------------------- one call, end to end, with a fake provider

def fake_builder(result=None, exc=None, parse_exc=None):
    def builder(cfg, mi, prompt):
        def send():
            if exc:
                raise exc
            return result

        def parse(resp):
            if parse_exc:
                raise parse_exc
            return resp
        return Call({"model": cfg["model_id"], "prompt": prompt}, {"temperature": "not set (provider default)"},
                    send, lambda r: {"raw": "response"}, parse)
    return builder


def _prepared(fake_inputs, tmp_path):
    slots = [Slot(1, "claude-haiku-5-5", "p2_reader_v1", "pilot-v6", 1)]
    prep = review.Prepared(slots, REVIEWERS, make_paths(fake_inputs, tmp_path))
    batch = {"batch_id": "test-20261015T000000Z", "purpose": "test", "plan_id": "test", "prices": load_prices()}
    return prep, slots, batch


def test_call_record_ok(fake_inputs, tmp_path, monkeypatch):
    result = {"text": "A review.", "model_returned": "claude-haiku-5-5", "request_id": "req_1", "stop_reason": "end_turn",
              "usage": {"input_total": 1000, "cached_input": 0, "cache_write": 0, "output_billed": 10, "reasoning": "x"},
              "effort_reported": "unknown"}
    monkeypatch.setitem(review.BUILDERS, "anthropic_api", fake_builder(result))
    prep, slots, batch = _prepared(fake_inputs, tmp_path)
    bdir = tmp_path / "runs" / "review" / batch["batch_id"]
    rec = review.do_call(prep, bdir, batch, slots[0], 1, {"commit": "abc", "dirty": False}, "TEST")
    assert rec["status"] == "ok" and rec["construction"] == "used in construction" and rec["version"] == "flawed"
    assert rec["git_commit"] == "abc" and rec["request_id"] == "req_1" and rec["template_sha256"] == MANIFEST["p2_reader_v1"]["sha256"]
    assert (bdir / rec["text_file"]).read_text(encoding="utf-8") == "A review."
    assert sha256_file(bdir / rec["raw_file"]) == rec["raw_sha256"]
    assert read_jsonl(bdir / "calls.jsonl") == [rec]
    with pytest.raises(FileExistsError):                       # same run ID cannot be written twice
        review.do_call(prep, bdir, batch, slots[0], 1, {"commit": "abc", "dirty": False}, "TEST")


def test_call_record_error_is_kept(fake_inputs, tmp_path, monkeypatch):
    monkeypatch.setitem(review.BUILDERS, "anthropic_api", fake_builder(exc=RuntimeError("HTTP 529 overloaded")))
    prep, slots, batch = _prepared(fake_inputs, tmp_path)
    bdir = tmp_path / "runs" / "review" / batch["batch_id"]
    rec = review.do_call(prep, bdir, batch, slots[0], 1, {"commit": "abc", "dirty": False}, "TEST")
    assert rec["status"] == "error" and "529" in rec["error"]["message"]
    assert json.loads((bdir / rec["raw_file"]).read_text(encoding="utf-8"))["error"]["type"] == "RuntimeError"


def test_response_is_saved_even_if_reading_it_fails(fake_inputs, tmp_path, monkeypatch):
    monkeypatch.setitem(review.BUILDERS, "anthropic_api", fake_builder({"x": 1}, parse_exc=AttributeError("no field")))
    prep, slots, batch = _prepared(fake_inputs, tmp_path)
    bdir = tmp_path / "runs" / "review" / batch["batch_id"]
    rec = review.do_call(prep, bdir, batch, slots[0], 1, {"commit": "abc", "dirty": False}, "TEST")
    assert rec["status"] == "parse_error" and rec["error"]["type"] == "AttributeError"
    assert json.loads((bdir / rec["raw_file"]).read_text(encoding="utf-8")) == {"raw": "response"}
    assert rec["effort_default_documented"].startswith("medium")


# ---------------------------------------------------------------- reading real SDK response objects

def _md_call(builder, route, fake_inputs, fmt="pdf"):
    mi = load_manuscript(fake_inputs.resolve(), "pilot-v6", fmt)
    return builder({"model_id": "m", "route": route, "max_output_tokens": 100}, mi, "P")


def test_parse_anthropic_message(fake_inputs):
    from anthropic.types import Message
    msg = Message.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "stop_reason": "end_turn",
        "stop_sequence": None, "content": [{"type": "thinking", "thinking": "", "signature": "s"},
                                           {"type": "text", "text": "Review."}],
        "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 900, "cache_read_input_tokens": 0}})
    call = _md_call(build_anthropic, "anthropic_api", fake_inputs)
    r = call.parse(msg)
    assert r["text"] == "Review." and r["usage"]["input_total"] == 910 and r["usage"]["cache_write"] == 900
    assert call.dump(msg)["message"]["id"] == "msg_1"


def test_parse_gemini_response(fake_inputs):
    from google.genai import types
    resp = types.GenerateContentResponse.model_validate({
        "response_id": "r1", "model_version": "gemini-4-argon-001",
        "candidates": [{"content": {"role": "model", "parts": [{"text": "thinking", "thought": True}, {"text": "Review."}]},
                        "finish_reason": "STOP"}],
        "usage_metadata": {"prompt_token_count": 100, "candidates_token_count": 20, "thoughts_token_count": 30}})
    call = _md_call(build_gemini, "gemini_api", fake_inputs)
    r = call.parse(resp)
    assert r["text"] == "Review." and r["stop_reason"] == "STOP" and r["usage"]["output_billed"] == 50
    resp2 = resp.model_copy(update={"usage_metadata": types.GenerateContentResponseUsageMetadata(
        prompt_token_count=100, candidates_token_count=20)})
    r2 = call.parse(resp2)
    assert r2["usage"]["reasoning"] == "not reported" and r2["usage"]["output_billed"] == 20
    assert classify(r) == "ok" and call.dump(resp)["response_id"] == "r1"


def test_parse_openai_response(fake_inputs):
    from openai.types.responses import Response
    resp = Response.model_validate({
        "id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-6-astra-2026-09-01", "status": "completed",
        "incomplete_details": None, "error": None, "instructions": None, "metadata": {}, "parallel_tool_calls": True,
        "temperature": None, "tool_choice": "auto", "tools": [], "top_p": None, "reasoning": {"effort": "medium"},
        "output": [{"type": "message", "id": "m1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "Review.", "annotations": []}]}],
        "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 40, "cache_write_tokens": 10}, "output_tokens": 70,
                  "output_tokens_details": {"reasoning_tokens": 50}, "total_tokens": 170}})
    call = _md_call(build_openai, "openai_api", fake_inputs)
    r = call.parse(resp)
    assert r["text"] == "Review." and r["effort_reported"] == "medium" and r["usage"]["cached_input"] == 40
    assert r["usage"]["cache_write"] == 10
    assert r["model_returned"] == "gpt-6-astra-2026-09-01" and classify(r) == "ok"


def test_parse_fireworks_completion(fake_inputs):
    from openai.types.chat import ChatCompletion
    resp = ChatCompletion.model_validate({
        "id": "c1", "object": "chat.completion", "created": 0, "model": "accounts/fireworks/models/kimi-k3",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "Review.", "reasoning_content": "..."}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}})
    call = _md_call(build_chat, "fireworks_serverless", fake_inputs, "md_figures")
    r = call.parse(resp)
    assert r["text"] == "Review." and r["request_id"] == "c1" and r["usage"]["output_billed"] == 30
    assert r["effort_reported"] == "unknown" and r["settings_reported"] == {}
    assert call.dump(resp)["completion"]["choices"][0]["message"]["reasoning_content"] == "..."


def test_interrupted_call_is_recorded(fake_inputs, tmp_path):
    bdir = tmp_path / "b"
    (bdir / "requests").mkdir(parents=True)
    (bdir / "requests" / "x-20261015T000000Z-s004-a1.json").write_text("{}", encoding="utf-8")
    review.mark_interrupted(bdir, {"batch_id": "x-20261015T000000Z"}, {"commit": "abc"}, "TEST")
    rec = read_jsonl(bdir / "calls.jsonl")[0]
    assert rec["status"] == "interrupted" and rec["slot"] == 4 and rec["attempt"] == 1


# ---------------------------------------------------------------- real inputs (local only)

LOCAL = REPO / "config" / "paths.local.yaml"


@pytest.mark.skipif(not LOCAL.exists(), reason="no local inputs")
@pytest.mark.parametrize("fmt", ["pdf", "md_figures", "md_text"])
def test_real_inputs_pass_isolation(fmt):
    paths = common.load_paths()
    files = []
    for m in ("pilot-v6", "clean-matched-v6"):
        mi = load_manuscript(paths.inputs_dir, m, fmt)
        files += mi.files
        if fmt == "md_figures":
            assert sum(s.kind == "image" for s in mi.segments) == 8
    assert isolation.check(paths.inputs_dir, paths.key_sha256, files)["passed"]


# ---------------------------------------------------------------- queues and report

def test_same_underlying_model_shares_one_queue(fake_inputs, tmp_path):
    slots = expand(load_plan(REPO / "plans" / "practice_v1.yaml"), REVIEWERS, MANIFEST)
    prep = review.Prepared(slots, REVIEWERS, make_paths(fake_inputs, tmp_path))
    q = review.queues(prep, [(s, 1, None, None) for s in slots])
    assert {j[0].model_key for j in q["gpt-6-astra"]} == {"gpt-6-astra", "gpt-6-astra-effort-low", "gpt-6-astra-effort-max"}
    assert {j[0].model_key for j in q["gemini-4-argon"]} == {"gemini-4-argon", "gemini-4-argon-mdfig"}
    assert sum(len(v) for v in q.values()) == 20


def test_report_rows_and_totals():
    from harness import report
    recs = [{"run_id": "b-s001-a1", "model_key": "m", "provider": "anthropic", "status": "ok",
             "usage": {"input_total": 100, "output_billed": 10}, "cost_estimate": {"usd": 0.5}, "seconds": 3},
            {"run_id": "b-s002-a1", "model_key": "m", "provider": "anthropic", "status": "error", "usage": None,
             "cost_estimate": {"usd": "unknown"}, "seconds": 1},
            {"run_id": "b-s003-a1", "slot": 3, "status": "interrupted"}]
    table = report.rows(recs)
    assert len(table) == 2
    t = report.totals(table)["anthropic"]
    assert t["calls"] == 2 and t["input_total"] == 100 and t["cost_usd"] == 0.5 and t["cost_unknown_calls"] == 1


def test_fireworks_reported_settings_from_headers(fake_inputs):
    from openai.types.chat import ChatCompletion
    call = _md_call(build_chat, "fireworks_serverless", fake_inputs, "md_figures")
    ctx = next(c.cell_contents for c in call.parse.__closure__ if isinstance(c.cell_contents, dict))  # filled by send()
    ctx["headers"] = {"x-request-id": "rq9", "fireworks-sampling-options": '{"temperature": 1.0, "top_p": 0.95}',
                      "fireworks-conversation-options": '{"reasoning_effort": "high"}'}
    resp = ChatCompletion.model_validate({
        "id": "c1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "R"}}]})
    r = call.parse(resp)
    assert r["request_id"] == "rq9" and r["effort_reported"] == "high"
    assert r["settings_reported"]["sampling"]["temperature"] == 1.0 and r["usage"]["input_total"] is None


def test_batch_readme_follows_record_format():
    from harness import report
    batch = {"batch_id": "practice_v1-X", "created_utc": "2026-10-15T21:31:47Z", "operator": "XX", "purpose": "practice",
             "git": {"commit": "e2fc2ccc83e8", "dirty": False}, "harness_version": "0.1.0", "python": "3.11.9",
             "sdk_versions": {"anthropic": "1.14.0"}, "plan_file": "plans/practice_v1.yaml", "plan_sha256": "ab",
             "slots": [{}, {}], "inputs": {"pilot-v6/pdf": [{"path": "pilot-v6/manuscript.pdf", "sha256": "ff"}]},
             "templates": {"p1_bare_v1": {"file": "review/p1_bare_v1.txt", "sha256": "42"}},
             "models": {"claude-haiku-5-5": REVIEWERS["claude-haiku-5-5"]},
             "model_metadata": {"claude-haiku-5-5": {"created_at": "2026-08-01"}},
             "isolation": {"inputs_folder_files_scanned": 21, "files_sent": 1}}
    recs = [{"run_id": "practice_v1-X-s001-a1", "model_key": "claude-haiku-5-5", "status": "ok", "effort_reported": "unknown"},
            {"run_id": "practice_v1-X-s002-a2", "model_key": "claude-haiku-5-5", "status": "ok",
             "parent_run_id": "practice_v1-X-s002-a1", "rerun_reason": "HTTP 529 overloaded"}]
    text = report.readme(batch, recs, [{"command": "start", "time_utc": "t"}], "usage.csv")
    for part in ("**Tools.**", "Claude Code", "**Request.**", "**Inputs (read only, unchanged)**", "**Method.**",
                 "**Checks.**", "**Judgment calls.**", "**Outputs**", "e2fc2ccc83e8", "HTTP 529 overloaded", "2026-08-01"):
        assert part in text, part


def test_model_metadata_never_raises():
    from harness.providers import model_metadata
    assert "error" in model_metadata({"route": "nowhere", "model_id": "m"})


def test_queue_stops_after_three_errors_in_a_row(fake_inputs, tmp_path, monkeypatch):
    monkeypatch.setitem(review.BUILDERS, "anthropic_api", fake_builder(exc=RuntimeError("credit balance is too low")))
    slots = [Slot(n, "claude-haiku-5-5", "p2_reader_v1", "pilot-v6", n) for n in range(1, 6)]
    prep = review.Prepared(slots, REVIEWERS, make_paths(fake_inputs, tmp_path))
    batch = {"batch_id": "t-20261016T000000Z", "purpose": "test", "plan_id": "t", "prices": load_prices()}
    bdir = tmp_path / "runs" / "review" / batch["batch_id"]
    out = review.run_queue(prep, bdir, batch, [(s, 1, None, None) for s in slots], {"commit": "abc", "dirty": False}, "T")
    assert len(out) == 3 and all(r["status"] == "error" for r in out)
    ev = read_jsonl(bdir / "events.jsonl")[0]
    assert ev["command"] == "queue stopped" and ev["slots_not_attempted"] == [4, 5]


def test_keys_file_overrides_environment(tmp_path, monkeypatch):
    from harness.common import key_fingerprints, load_api_keys
    monkeypatch.setenv("OPENAI_API_KEY", "personal-key")
    f = tmp_path / "keys.txt"
    f.write_text("OpenAI: project-key\n", encoding="utf-8")
    assert load_api_keys(f) == ["OPENAI_API_KEY"]
    import os
    assert os.environ["OPENAI_API_KEY"] == "project-key"
    fp = key_fingerprints(["OPENAI_API_KEY"])["OPENAI_API_KEY"]
    assert len(fp) == 12 and "project" not in fp


def test_endpoints_are_fixed():
    from harness.providers import ANTHROPIC_BASE_URL, OPENAI_BASE_URL
    assert ANTHROPIC_BASE_URL == "https://api.anthropic.com" and OPENAI_BASE_URL == "https://api.openai.com/v1"


"""Coding runs: blinding, human sample, prompt, reading answers and call records. No API access needed."""
from __future__ import annotations

import collections
import json

import pytest

from harness import code
from harness.coding import (blind, draw_human_sample, extract_json, quote_found, read_answer, split_template,
                            CONCERNS)
from harness.common import REPO, load_template, load_yaml, sha256_bytes, sha256_file
from harness.inputs import ManuscriptInput, Segment
from harness.plans import load_models
from harness.providers import Call, build_anthropic, build_chat
from harness.records import load_prices, read_jsonl

CODERS = load_models()["coders"]
MAIN_MODELS = {"claude-fable-5-1": "anthropic", "claude-haiku-5-5": "anthropic", "gpt-6-astra": "openai",
               "gpt-6-luna": "openai", "gemini-4-argon": "google", "gemini-3-5-flash-lite": "google",
               "deepseek-v4p1-flash": "fireworks", "kimi-k3": "fireworks"}
PROMPTS = ["p1_bare_v1", "p2_reader_v1", "p3_criteria_v1"]


def fake_reviews():
    rows, slot = [], 0
    for m, prov in MAIN_MODELS.items():
        for rep in range(1, 11):
            for ms, v in (("pilot-v6", "flawed"), ("clean-matched-v6", "clean")):
                for p in PROMPTS:
                    slot += 1
                    rows.append({"review_batch_id": "main_v1-X", "review_purpose": "main",
                                 "review_run_id": f"main_v1-X-s{slot:03d}-a1", "review_slot": slot, "model_key": m,
                                 "provider": prov, "template_id": p, "manuscript": ms, "version": v, "rep": rep,
                                 "text_file": f"main_v1-X/text/{slot}.md", "text_sha256": f"{slot:064d}"})
    for i in range(1, 41):
        rows.append({"review_batch_id": "effort_v1-X", "review_purpose": "effort", "review_run_id": f"effort-{i}",
                     "review_slot": i, "model_key": "gpt-6-astra-effort-low", "provider": "openai",
                     "template_id": "p3_criteria_v1", "manuscript": "pilot-v6", "version": "flawed", "rep": i,
                     "text_file": f"effort_v1-X/text/{i}.md", "text_sha256": f"{i:064d}"})
    return rows


# ---------------------------------------------------------------- blinding and human sample

def test_blinding_is_fixed_by_the_seed_and_complete():
    rows = fake_reviews()
    a, b, c = blind(rows, 20261023), blind(list(reversed(rows)), 20261023), blind(rows, 1)
    assert [r["review_run_id"] for r in a] == [r["review_run_id"] for r in b]
    assert [r["review_run_id"] for r in a] != [r["review_run_id"] for r in c]
    assert len({r["blind_id"] for r in a}) == len(rows) == 520 and a[0]["blind_id"] == "B001"


def test_human_sample_follows_section_5():
    s = draw_human_sample(blind(fake_reviews(), 20261023), 20261023)
    core, extra = s["core"], s["extra"]
    assert len(core) == 24 and len(extra) == 16
    assert set(collections.Counter((r["version"], r["template_id"]) for r in core).values()) == {4}
    for m in MAIN_MODELS:
        mine = [r for r in core if r["model_key"] == m]
        assert sorted(r["template_id"] for r in mine) == PROMPTS
        pattern = tuple(next(r["version"] for r in mine if r["template_id"] == p) for p in PROMPTS)
        assert pattern in (("flawed", "clean", "flawed"), ("clean", "flawed", "clean"))
    for prov in set(MAIN_MODELS.values()):                     # each provider's pair is split between the halves
        pair = [m for m, p in MAIN_MODELS.items() if p == prov]
        assert (pair[0] in s["halves"]["A"]) != (pair[1] in s["halves"]["A"])
    for m in MAIN_MODELS:
        mine = [r for r in extra if r["model_key"] == m]
        assert sorted(r["version"] for r in mine) == ["clean", "flawed"]
        assert mine[0]["template_id"] != mine[1]["template_id"]
    assert sorted(collections.Counter(r["template_id"] for r in extra).values()) == [5, 5, 6]
    ids = [r["blind_id"] for r in core + extra]
    assert len(ids) == len(set(ids)) == 40
    assert all(collections.Counter(r["model_key"] for r in core + extra)[m] == 5 for m in MAIN_MODELS)
    assert [r["order"] for r in core + extra] == list(range(1, 41))
    assert all(r["review_run_id"].startswith("main_v1") for r in core + extra)
    assert draw_human_sample(blind(fake_reviews(), 20261023), 20261023) == s


# ---------------------------------------------------------------- template and request

def test_coding_template_hash_and_slots():
    entry = load_yaml(REPO / "prompts" / "manifest.yaml")["coding"]["code_v1"]
    assert sha256_file(REPO / "prompts" / entry["file"]) == entry["sha256"]
    tpl = load_template("coding", "code_v1")
    fixed, with_review = split_template(tpl.text, "SHEET TEXT", "REVIEW TEXT {CODING_SHEET}")
    assert "SHEET TEXT" in fixed and "REVIEW TEXT" not in fixed
    assert with_review.startswith("REVIEW TEXT {CODING_SHEET}") and "SHEET TEXT" not in with_review
    assert with_review.rstrip().endswith("Answer with the JSON object only.")


def test_template_without_slots_is_refused():
    with pytest.raises(SystemExit):
        split_template("no slots", "s", "r")
    with pytest.raises(SystemExit):
        split_template("{REVIEW} then {CODING_SHEET}", "s", "r")


def _coding_call(builder, route):
    tpl = load_template("coding", "code_v1")
    fixed, with_review = split_template(tpl.text, "SHEET", "THE REVIEW")
    mi = ManuscriptInput("coding sheet", "text", [Segment(kind="text", text=fixed)])
    return builder({"model_id": "m", "route": route, "max_output_tokens": 100, "effort": "high"}, mi, with_review)


def test_anthropic_coding_request_caches_the_sheet_and_ends_with_the_review():
    call = _coding_call(build_anthropic, "anthropic_api")
    blocks = call.request["messages"][0]["content"]
    assert len(blocks) == 2 and "SHEET" in blocks[0]["text"] and blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"].startswith("THE REVIEW") and "cache_control" not in blocks[1]
    assert call.request["output_config"] == {"effort": "high"} and "system" not in call.request


def test_fireworks_coding_request_is_one_user_message():
    call = _coding_call(build_chat, "fireworks_serverless")
    msgs = call.request["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    assert "SHEET" in msgs[0]["content"][0]["text"] and msgs[0]["content"][1]["text"].startswith("THE REVIEW")


def test_sonnet_sends_its_documented_default_effort():
    assert CODERS["claude-sonnet-5-5"]["effort"] == "high"
    assert "effort" not in CODERS["qwen3p8-2p4t-a95b"]


# ---------------------------------------------------------------- reading answers

REVIEW = ("The paper says H2 is supported. A significant estimate in one subgroup and a nonsignificant estimate in "
          "another does not establish that the two estimates differ. Also, **Table 3** should cluster by firm.")


def answer(**over):
    concerns = [{"concern": c, "code": "–", "quote": "", "why": "", "unsure": False, "alternative_code": None,
                 "unsure_reason": None} for c in CONCERNS]
    concerns[5] = {"concern": "C6", "code": "F", "quote": "A significant estimate in one subgroup and a nonsignificant "
                   "estimate in another does not establish that the two estimates differ.", "why": "subgroup fallacy",
                   "unsure": False, "alternative_code": None, "unsure_reason": None}
    obj = {"concerns": concerns, "criticisms": ["H2 inference", "clustering"], "criticism_count": 2}
    obj.update(over)
    return obj


def test_read_answer_ok_with_prose_fences_and_thinking():
    text = "<think>{\"concerns\": 1}</think>Here it is:\n```json\n" + json.dumps(answer(), ensure_ascii=False) + "\n```"
    codes, problems = read_answer(text, REVIEW)
    assert problems == [] and codes["concerns"]["C6"]["code"] == "F" and codes["criticism_count"] == 2
    assert codes["concerns"]["C6"]["quote_found_in_review"] is True
    assert codes["concerns"]["C1"]["code"] == "–" and "quote_found_in_review" not in codes["concerns"]["C1"]


def test_read_answer_problems():
    a = answer(criticism_count=3)
    a["concerns"] = a["concerns"][:7]
    a["concerns"][0]["code"] = "X"
    _, problems = read_answer(json.dumps(a), REVIEW)
    assert any("missing concerns: C8" in p for p in problems)
    assert any("C1: code" in p for p in problems) and any("criticism_count 3" in p for p in problems)
    b = answer()
    b["concerns"][2].update({"code": "P", "quote": "", "why": ""})
    b["concerns"][3].update({"unsure": True, "alternative_code": None})
    _, problems = read_answer(json.dumps(b), REVIEW)
    assert any("C3: P without a quote" in p for p in problems)
    assert any("C4: unsure without a different alternative code" in p for p in problems)
    assert read_answer("no json here", REVIEW) == (None, ["no JSON object with a 'concerns' field"])


def test_hyphen_is_read_as_dash_and_unsure_is_kept():
    a = answer()
    a["concerns"][0]["code"] = "-"
    a["concerns"][7].update({"code": "F", "quote": "Table 3 should cluster by firm", "why": "x", "unsure": True,
                             "alternative_code": "P", "unsure_reason": "borderline"})
    codes, problems = read_answer(json.dumps(a), REVIEW)
    assert problems == [] and codes["concerns"]["C1"]["code"] == "–"
    assert codes["concerns"]["C8"]["alternative_code"] == "P" and codes["concerns"]["C8"]["quote_found_in_review"]


@pytest.mark.parametrize("quote, found", [
    ("a significant estimate in one subgroup … the two estimates differ", True),
    ("“Table 3 should cluster by firm.”", True),
    ("H2 is clearly unsupported", False),
])
def test_quote_found(quote, found):
    assert quote_found(quote, REVIEW) is found


# ---------------------------------------------------------------- one call

class FakePrep:
    def __init__(self, result=None, exc=None):
        self.coders = {"claude-sonnet-5-5": CODERS["claude-sonnet-5-5"]}
        self.template = load_template("coding", "code_v1")
        self.reviews = {"B001": {"text_sha256": sha256_bytes(REVIEW.encode()), "review_run_id": "main-s1"}}
        self.texts = {"B001": REVIEW}
        self._result, self._exc = result, exc

    def build(self, s):
        def send():
            if self._exc:
                raise self._exc
            return {"raw": "response"}
        return Call({"model": "m", "messages": "..."}, {"effort": "high"}, send, lambda r: r, lambda r: self._result)


def _batch():
    return {"batch_id": "coding_v1-20261023T000000Z", "purpose": "coding", "plan_id": "coding_v1",
            "prices": load_prices(), "coding_sheet": {"version": "v1.0", "sha256": "f" * 64}, "workers_per_coder": 1}


def test_call_record_ok_writes_codes(tmp_path):
    result = {"text": json.dumps(answer()), "model_returned": "claude-sonnet-5-5", "request_id": "req_1",
              "stop_reason": "end_turn", "effort_reported": "unknown",
              "usage": {"input_total": 9000, "cached_input": 8000, "cache_write": 0, "output_billed": 900, "reasoning": "x"}}
    bdir = tmp_path / "coding" / "b"
    rec = code.do_call(FakePrep(result), bdir, _batch(), code.CodingSlot(1, "claude-sonnet-5-5", "B001"), 1,
                       {"commit": "abc", "dirty": False}, "TEST")
    assert rec["status"] == "ok" and rec["problems"] == [] and rec["criticism_count"] == 2
    assert rec["blind_id"] == "B001" and "review_run_id" not in rec and rec["coding_sheet_sha256"] == "f" * 64
    assert rec["quote_flags"] == {"quotes": 1, "not_found_in_review": 0, "over_40_words": 0}
    saved = json.loads((bdir / rec["codes_file"]).read_text(encoding="utf-8"))
    assert saved["concerns"]["C6"]["code"] == "F" and saved["blind_id"] == "B001"
    assert read_jsonl(bdir / "calls.jsonl") == [rec]
    assert isinstance(rec["cost_estimate"]["usd"], float)


def test_invalid_answer_is_kept_and_marked(tmp_path):
    result = {"text": "I cannot comply.", "model_returned": "m", "request_id": "r", "stop_reason": "end_turn",
              "effort_reported": "unknown", "usage": {"input_total": 1, "cached_input": 0, "cache_write": 0,
                                                      "output_billed": 1, "reasoning": "x"}}
    bdir = tmp_path / "coding" / "b"
    rec = code.do_call(FakePrep(result), bdir, _batch(), code.CodingSlot(1, "claude-sonnet-5-5", "B001"), 1,
                       {"commit": "abc", "dirty": False}, "TEST")
    assert rec["status"] == "invalid_output" and rec["codes_file"] is None
    assert (bdir / rec["text_file"]).read_text(encoding="utf-8") == "I cannot comply."


def test_error_is_kept(tmp_path):
    bdir = tmp_path / "coding" / "b"
    rec = code.do_call(FakePrep(exc=RuntimeError("HTTP 529 overloaded")), bdir, _batch(),
                       code.CodingSlot(1, "claude-sonnet-5-5", "B001"), 1, {"commit": "abc", "dirty": False}, "TEST")
    assert rec["status"] == "error" and "529" in rec["error"]["message"]


def test_workers_split_each_coder_queue(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(code, "run_queue", lambda prep, bdir, batch, q, git, op: seen.append([j[0].slot for j in q]))
    jobs = [(code.CodingSlot(i, "a" if i <= 6 else "b", f"B{i:03d}"), 1, None, None) for i in range(1, 13)]
    code.run_jobs(None, tmp_path, {"workers_per_coder": 3}, jobs, {}, "TEST")
    assert sorted(seen) == [[1, 4], [2, 5], [3, 6], [7, 10], [8, 11], [9, 12]]


def test_coding_plan_names_the_frozen_sheet_and_known_coders():
    plan = load_yaml(REPO / "plans" / "coding_v1.yaml")
    assert set(plan["coders"]) <= set(CODERS) and plan["template"] == "code_v1"
    assert len(plan["coding_sheet"]["sha256"]) == 64 and plan["seed"] == 20261023


# ---------------------------------------------------------------- re-reading with the rules of 24 Oct

def test_rules_read_missing_unsure_as_not_unsure_and_use_list_length():
    a = answer(criticism_count=3)
    for c in a["concerns"]:
        for k in ("unsure", "alternative_code", "unsure_reason"):
            c.pop(k)
    strict_codes, strict_problems = read_answer(json.dumps(a), REVIEW)
    assert any("'unsure' is not true or false" in p for p in strict_problems)
    assert any("criticism_count 3" in p for p in strict_problems)
    codes, problems = read_answer(json.dumps(a), REVIEW, rules="rules_2026_10_24")
    assert problems == [] and codes["criticism_count"] == 2 and codes["criticism_count_stated"] == 3
    assert all(e["unsure"] is False and e["alternative_code"] is None for e in codes["concerns"].values())
    assert len(codes["read_rules_applied"]) == 9 and codes["read_rules"] == "rules_2026_10_24"


def test_rules_do_not_excuse_other_problems():
    a = answer()
    a["concerns"] = a["concerns"][:7]
    _, problems = read_answer(json.dumps(a), REVIEW, rules="rules_2026_10_24")
    assert any("missing concerns: C8" in p for p in problems)
    with pytest.raises(ValueError):
        read_answer(json.dumps(a), REVIEW, rules="anything")


def test_read_records_selects_the_latest_readable_attempt(tmp_path):
    bdir = tmp_path / "b"
    (bdir / "text").mkdir(parents=True)
    good = json.dumps(answer())
    bad = "not json"
    recs = []
    for rid, slot, att, status, text in (("r1", 1, 1, "invalid_output", bad), ("r2", 1, 2, "ok", good),
                                         ("r3", 2, 1, "ok", good), ("r4", 3, 1, "error", None)):
        rec = {"run_id": rid, "slot": slot, "attempt": att, "coder_key": "c", "blind_id": "B001", "status": status,
               "text_file": None, "text_sha256": None}
        if text is not None:
            (bdir / "text" / f"{rid}.md").write_text(text, encoding="utf-8")
            rec.update({"text_file": f"text/{rid}.md", "text_sha256": sha256_bytes(text.encode())})
        recs.append(rec)
    # an interrupted attempt's record has no coder or blind ID
    recs.append({"run_id": "r5", "slot": 4, "attempt": 1, "status": "interrupted"})
    slots = [{"slot": n, "coder_key": "c", "blind_id": "B001"} for n in (1, 2, 3, 4, 5)]
    rows, selected = code.read_records(bdir, recs, {"B001": REVIEW}, "rules_2026_10_24", slots)
    assert [r["read_status"] for r in rows] == ["problems", "ok", "ok"]
    assert [s["run_id"] for s in selected] == ["r2", "r3", None, None, None]
    assert all(s["coder_key"] == "c" for s in selected)


def test_resume_can_set_the_number_of_queues(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(code, "run_queue", lambda prep, bdir, batch, q, git, op: seen.append(len(q)))
    jobs = [(code.CodingSlot(i, "qwen", f"B{i:03d}"), 1, None, None) for i in range(1, 13)]
    code.run_jobs(None, tmp_path, {"workers_per_coder": 3}, jobs, {}, "TEST", workers=6)
    assert sorted(seen) == [2] * 6

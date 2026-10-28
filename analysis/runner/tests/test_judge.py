"""Judge runs: pairing, templates, requests, verdicts and call records. No API access needed."""
from __future__ import annotations

import collections
import json

import pytest

from harness import judge
from harness.common import REPO, load_template, load_yaml, sha256_file
from harness.inputs import ManuscriptInput
from harness.judging import fill_user, make_pairs, read_verdict
from harness.plans import load_models
from harness.providers import Call, build_chat, build_openai
from harness.records import load_prices, read_jsonl
from tests.test_coding import fake_reviews

JUDGES = load_models()["judges"]


def blinded():
    from harness.coding import blind
    return blind(fake_reviews(), 20261023)


def test_pairs_cover_each_main_review_once_within_cells_and_models_differ():
    rows = blinded()
    pairs = make_pairs(rows, 20261024)
    by_id = {r["blind_id"]: r for r in rows}
    assert len(pairs) == 240
    assert set(collections.Counter((p["version"], p["template_id"]) for p in pairs).values()) == {40}
    used = [p["review_1"] for p in pairs] + [p["review_2"] for p in pairs]
    assert len(used) == len(set(used)) == 480
    for p in pairs:
        a, b = by_id[p["review_1"]], by_id[p["review_2"]]
        assert a["model_key"] != b["model_key"]
        assert (a["version"], a["template_id"]) == (b["version"], b["template_id"]) == (p["version"], p["template_id"])
    assert make_pairs(rows, 20261024) == pairs and make_pairs(rows, 1) != pairs


def test_judge_templates_match_manifest_and_name_the_tags():
    m = load_yaml(REPO / "prompts" / "manifest.yaml")["judge"]
    for t in m.values():
        assert sha256_file(REPO / "prompts" / t["file"]) == t["sha256"]
    system = load_template("judge", "kw_pairwise_reviews_only_v1").text
    assert "<review_a>...</review_a>" in system and system.count("•") == 13
    assert "without recommending additional work" in system and "confidential" not in system
    user = fill_user(load_template("judge", "kw_reviews_user_v1").text, "TEXT A {REVIEW_B}", "TEXT B")
    assert user.startswith("<review_a>\nTEXT A {REVIEW_B}\n</review_a>") and "<review_b>\nTEXT B\n</review_b>" in user


def test_openai_judge_request_sends_instructions_and_xhigh_effort():
    call = build_openai(JUDGES["gpt-5-5"], ManuscriptInput("judge", "text"), "USER", system="SYSTEM")
    assert call.request["instructions"] == "SYSTEM" and call.request["reasoning"] == {"effort": "xhigh"}
    assert call.request["input"][0]["content"] == [{"type": "input_text", "text": "USER"}]
    assert call.request["prompt_cache_key"].startswith("sys-") and call.request["store"] is False


def test_fireworks_judge_request_has_system_message_first():
    call = build_chat(JUDGES["qwen3p8-2p4t-a95b"], ManuscriptInput("judge", "text"), "USER", system="SYSTEM")
    msgs = call.request["messages"]
    assert msgs[0] == {"role": "system", "content": "SYSTEM"} and msgs[1]["role"] == "user"


def test_review_and_coding_requests_are_unchanged_without_system():
    call = build_chat({"model_id": "m", "route": "fireworks_serverless", "max_output_tokens": 10},
                      ManuscriptInput("x", "text"), "P")
    assert [m["role"] for m in call.request["messages"]] == ["user"]
    assert call.settings["system_prompt"] == "none"


@pytest.mark.parametrize("text, winner, problems", [
    ('{"winner": "A", "rationale": "A is clearer."}', "A", []),
    ('Sure.\n```json\n{"winner": "b", "rationale": "x"}\n```', "B", []),
    ('<think>{"winner": "A"}</think>{"winner": "<B>", "rationale": "y"}', "B", []),
    ('{"winner": "tie", "rationale": "both"}', None, ["winner 'tie' is not A or B"]),
    ('{"winner": "A"}', "A", ["no rationale"]),
    ("no json", None, ["no JSON object with a 'winner' field"]),
])
def test_read_verdict(text, winner, problems):
    v, p = read_verdict(text)
    assert (v["winner"] if v else None) == winner and p == problems


def test_each_pair_is_judged_in_both_orders_in_shuffled_order():
    pairs = {"pairs": make_pairs(blinded(), 20261024)}
    plan = {"judges": ["gpt-5-5", "qwen3p8-2p4t-a95b"], "seed": 20261024}
    slots = judge.expand(plan, JUDGES, pairs)
    assert len(slots) == 960
    for j in plan["judges"]:
        mine = [(s.pair_id, s.order) for s in slots if s.judge_key == j]
        assert len(set(mine)) == 480 and collections.Counter(o for _, o in mine) == {"12": 240, "21": 240}
    first = [s.pair_id for s in slots if s.judge_key == "gpt-5-5"][:20]
    assert first != sorted(first)                                   # not run in pair order


class FakePrep:
    def __init__(self, result=None):
        self.judges = {"gpt-5-5": JUDGES["gpt-5-5"]}
        self.system = load_template("judge", "kw_pairwise_reviews_only_v1")
        self.user = load_template("judge", "kw_reviews_user_v1")
        self.shas = {"B001": "1" * 64, "B002": "2" * 64}
        self.pairs = {"P001": {"pair_id": "P001", "review_1": "B001", "review_2": "B002"}}
        self._result = result

    def sides(self, s):
        return ("B001", "B002") if s.order == "12" else ("B002", "B001")

    def build(self, s):
        return Call({"model": "gpt-5.5"}, {"effort": "xhigh"}, lambda: {"raw": 1}, lambda r: r, lambda r: self._result)


def test_call_record_maps_the_winner_to_its_blind_id(tmp_path):
    result = {"text": '{"winner": "A", "rationale": "A explains the H2 test."}', "model_returned": "gpt-5.5",
              "request_id": "r", "stop_reason": "completed", "effort_reported": "xhigh",
              "usage": {"input_total": 9000, "cached_input": 2000, "cache_write": 0, "output_billed": 3000,
                        "reasoning": 2800}}
    batch = {"batch_id": "judge_v1-20261025T000000Z", "purpose": "judge (exploratory)", "plan_id": "judge_v1",
             "prices": load_prices()}
    bdir = tmp_path / "judge" / "b"
    rec = judge.do_call(FakePrep(result), bdir, batch, judge.JudgeSlot(1, "gpt-5-5", "P001", "21"), 1,
                        {"commit": "abc", "dirty": False}, "TEST")
    assert rec["status"] == "ok" and rec["winner"] == "A" and rec["winner_blind_id"] == "B002"
    assert rec["review_a"] == "B002" and isinstance(rec["cost_estimate"]["usd"], float)
    assert read_jsonl(bdir / "calls.jsonl") == [rec]


def test_judge_plan_names_known_judges_and_templates():
    plan = load_yaml(REPO / "plans" / "judge_v1.yaml")
    assert set(plan["judges"]) <= set(JUDGES) and plan["blinding_plan"] == "coding_v1"
    assert JUDGES["gpt-5-5"]["effort"] == "xhigh"

"""Judge analysis: decided pairs and the three outcomes on a small made-up example. No API access needed."""
from __future__ import annotations

import pytest

from harness import judge_tables as J
from harness.tables import CODERS, CONCERNS


def codes_for(spec: dict) -> dict:
    """spec: {blind_id: ({concern: Sonnet code}, {concern: Qwen code})}; unlisted concerns are –."""
    out = {}
    for b, (son, qwen) in spec.items():
        out[(b, CODERS[0])] = {c: son.get(c, "–") for c in CONCERNS}
        out[(b, CODERS[1])] = {c: qwen.get(c, "–") for c in CONCERNS}
    return out


def test_verdicts_keep_the_latest_ok_attempt_and_both_orders():
    calls = [{"slot": 1, "attempt": 1, "status": "invalid_output", "judge_key": "j", "pair_id": "P1", "order": "12", "winner_blind_id": None},
             {"slot": 1, "attempt": 2, "status": "ok", "judge_key": "j", "pair_id": "P1", "order": "12", "winner_blind_id": "B1"},
             {"slot": 2, "attempt": 1, "status": "ok", "judge_key": "j", "pair_id": "P1", "order": "21", "winner_blind_id": "B1"}]
    assert J.verdicts(calls) == {("j", "P1"): {"12": "B1", "21": "B1"}}


def test_three_outcomes_with_lower_and_higher_codes():
    codes = codes_for({"B1": ({"C1": "F", "C2": "F"}, {"C1": "F", "C2": "P"}),   # 2 F (higher), 1 F (lower)
                       "B2": ({"C1": "F"}, {"C1": "F"}),                         # 1 F
                       "B3": ({"C3": "F"}, {"C3": "F"}), "B4": ({}, {})})        # clean pair
    pairs = [{"pair_id": "P1", "version": "flawed", "template_id": "p1_bare_v1", "review_1": "B1", "review_2": "B2"},
             {"pair_id": "P2", "version": "clean", "template_id": "p1_bare_v1", "review_1": "B3", "review_2": "B4"}]
    providers = {"B1": "anthropic", "B2": "google", "B3": "openai", "B4": "google"}
    decided = {"P1": "B2", "P2": "B3"}
    hi = J.analyse(pairs, decided, codes, providers, "higher", "F", False, CONCERNS)
    assert hi["agreement"]["all 8 concerns"]["n"] == 1 and hi["agreement"]["all 8 concerns"]["share"] == 0
    assert hi["preferred_but_missed"]["C2"] == pytest.approx({"k": 1, "n": 1, "share": 1.0, "ci95": list(J.wilson(1, 1))})
    assert hi["raised_on_clean"]["all 8 concerns"]["share"] == 1
    lo = J.analyse(pairs, decided, codes, providers, "lower", "F", False, CONCERNS)
    assert lo["agreement"]["all 8 concerns"]["n"] == 0                   # tie under the lower codes
    no = J.analyse(pairs, decided, codes, providers, "higher", "F", True, CONCERNS)
    assert no["pairs"] == 1 and no["raised_on_clean"]["all 8 concerns"]["n"] == 0

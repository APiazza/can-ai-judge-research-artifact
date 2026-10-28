"""Results tables: agreement statistics and the lower/higher reading of coder disagreements. No API access needed."""
from __future__ import annotations

import pytest

from harness import tables


def test_agreement_share_kappa_and_ac1():
    a = ["F", "F", "–", "–"]
    b = ["F", "–", "–", "–"]
    r = tables.agreement(a, b)
    assert r["same"] == 3 and r["agreement"] == 0.75
    assert r["kappa"] == pytest.approx(0.5)
    assert r["ac1"] == pytest.approx((0.75 - 0.234375) / (1 - 0.234375))
    same = tables.agreement(["F", "P", "–"], ["F", "P", "–"])
    assert same["agreement"] == same["kappa"] == 1


def review(son: dict, qwen: dict) -> dict:
    full = lambda d: {c: d.get(c, "–") for c in tables.CONCERNS}
    return {"codes": {tables.CODERS[0]: full(son), tables.CODERS[1]: full(qwen)},
            "counts": {tables.CODERS[0]: 6, tables.CODERS[1]: 9}}


def test_disagreements_are_read_with_the_lower_and_the_higher_code():
    rows = [review({"C1": "F"}, {"C1": "P"}), review({"C1": "F"}, {"C1": "F"})]
    assert tables.share(rows, ["C1"], "F", "lower") == 0.5
    assert tables.share(rows, ["C1"], "F", "higher") == 1
    assert tables.share(rows, ["C1"], "FP", "lower") == tables.share(rows, ["C1"], "FP", "higher") == 1
    assert tables.share(rows, ["C1"], "F", tables.CODERS[1]) == 0.5
    assert tables.per_review(rows, "F", "higher") == 1      # one of eight concerns raised per review
    assert tables.mean_count(rows) == 7.5                   # average of the two coders' counts
    assert tables.any_run(rows, "F", "lower") == 1 and tables.any_run(rows, "F", "higher") == 1
    assert tables.any_run([review({"C2": "P"}, {"C2": "P"}), rows[0]], "FP", "lower") == 2

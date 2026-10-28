"""Judge runs (exploratory; plan of 24 Oct 2026): does a judge's preference between two reviews track which one
catches the planted problems?

Pairs. The main reviews are taken from the coding blinding, so every review keeps its blind ID. Within each cell of
version x prompt, the reviews are shuffled with the plan's seed and paired so that the two reviews of a pair come from
different models; every review is in exactly one pair. Each pair is judged in both orders (A then B, and B then A).

Prompt. King and Worthington (2026), Supplementary Appendix D(b), "Overall pairwise ranking (reviews only)", with
their abbreviated Appendix B guidelines inserted where they mark it, is sent as the system message. The user message
holds the two reviews in <review_a> and <review_b> tags. The judge sees no manuscript, no model, version or prompt.
"""
from __future__ import annotations

import json
import random
import re

REVIEW_A, REVIEW_B = "{REVIEW_A}", "{REVIEW_B}"


def make_pairs(blinded: list[dict], seed, purpose: str = "main") -> list[dict]:
    rng = random.Random(f"{seed}:judge-pairs")
    rows = [r for r in blinded if r["review_purpose"] == purpose]
    cells: dict[tuple, list[dict]] = {}
    for r in rows:
        cells.setdefault((r["version"], r["template_id"]), []).append(r)
    pairs = []
    for (version, prompt) in sorted(cells):
        cell = sorted(cells[(version, prompt)], key=lambda r: r["blind_id"])
        if len(cell) % 2:
            raise SystemExit(f"Cell {version}/{prompt} has an odd number of reviews ({len(cell)})")
        for _ in range(100_000):
            rng.shuffle(cell)
            if all(cell[i]["model_key"] != cell[i + 1]["model_key"] for i in range(0, len(cell), 2)):
                break
        else:
            raise SystemExit(f"Could not pair cell {version}/{prompt} with different models in every pair")
        for i in range(0, len(cell), 2):
            pairs.append({"version": version, "template_id": prompt,
                          "review_1": cell[i]["blind_id"], "review_2": cell[i + 1]["blind_id"]})
    width = max(3, len(str(len(pairs))))
    return [{"pair_id": f"P{i:0{width}d}", **p} for i, p in enumerate(pairs, 1)]


def fill_user(template: str, review_a: str, review_b: str) -> str:
    if template.count(REVIEW_A) != 1 or template.count(REVIEW_B) != 1:
        raise SystemExit("The judge user template needs exactly one {REVIEW_A} and one {REVIEW_B}")
    i = template.index(REVIEW_B)
    return template[:i].replace(REVIEW_A, review_a) + template[i:].replace(REVIEW_B, review_b, 1)


def read_verdict(text: str) -> tuple[dict | None, list[str]]:
    """Returns ({winner, rationale}, problems). The verdict counts only if 'winner' is A or B."""
    t = re.sub(r"(?s)<think>.*?</think>", "", text)
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", t):
        try:
            obj, _ = dec.raw_decode(t, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and "winner" in obj:
            winner = str(obj["winner"]).strip().strip("<>").upper()
            problems = [] if winner in ("A", "B") else [f"winner {obj['winner']!r} is not A or B"]
            rationale = obj.get("rationale")
            if not (isinstance(rationale, str) and rationale.strip()):
                problems.append("no rationale")
            return {"winner": winner if winner in ("A", "B") else None, "rationale": rationale}, problems
    return None, ["no JSON object with a 'winner' field"]

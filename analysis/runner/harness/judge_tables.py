"""Judge analysis (exploratory; run plan section 8): does a judge's preference between two reviews track which review
catches the planted problems? No API call.

A pair is decided when the same review wins in both orders; other pairs are undecided and counted. Detection comes from
the final LLM codes: where the two coders differ, every result is computed with the lower and with the higher code, and
each with F only and with F or P.
  1. Agreement: among decided planted-version pairs whose numbers of planted concerns raised differ, the share in which
     the judge prefers the review that raises more. Read with the bands set before any result: 80% or more, preference
     largely tracks detection; 60% or less, a weak guide; in between, mixed.
  2. Preferred but missed: for each concern, among decided planted-version pairs in which exactly one review raises it,
     the share in which the judge prefers the review that misses it.
  3. Raised on clean: among decided clean-version pairs whose numbers of concerns raised differ, the share in which the
     judge prefers the review that raises more.
Every result is also given without pairs that contain an OpenAI review, and the Qwen judge's results also against
Sonnet's codes alone.

    python -m harness.judge_tables <judge_batch_id> --coding <coding_batch_id> --read <reads folder> --tables <tables folder>
"""
from __future__ import annotations

import argparse
import json
import math

from . import HARNESS_VERSION
from .code import load_blinding, load_plan
from .common import REPO, git_state, load_paths, sha256_file, utc_now
from .records import read_jsonl, write_once
from .tables import CODERS, CONCERNS, PROMPTS, RANK, TYPE_ORDER, TYPES, llm_codes, raised

QWEN_JUDGE, GPT_JUDGE = "qwen3p8-2p4t-a95b", "gpt-5-5"


def wilson(k: int, n: int) -> tuple[float | None, float | None]:
    if not n:
        return None, None
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def verdicts(calls: list[dict]) -> dict:
    """{(judge, pair_id): {"12": winner blind ID, "21": ...}} from the latest ok attempt of each slot."""
    best = {}
    for r in calls:
        if r["status"] == "ok" and r.get("winner_blind_id"):
            k = r["slot"]
            if k not in best or r["attempt"] > best[k]["attempt"]:
                best[k] = r
    out = {}
    for r in best.values():
        out.setdefault((r["judge_key"], r["pair_id"]), {})[r["order"]] = r["winner_blind_id"]
    return out


def code_of(codes: dict, blind_id: str, concern: str, which: str) -> str:
    a, b = codes[(blind_id, CODERS[0])][concern], codes[(blind_id, CODERS[1])][concern]
    return {"lower": min(a, b, key=RANK.get), "higher": max(a, b, key=RANK.get), "sonnet": a, "qwen": b}[which]


def count(codes, blind_id, concerns, level, which) -> int:
    return sum(raised(code_of(codes, blind_id, c, which), level) for c in concerns)


def result(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "share": k / n if n else None, "ci95": [lo, hi]}


def analyse(pairs: list[dict], decided: dict, codes: dict, providers: dict, which: str, level: str, no_openai: bool,
            reliable: list[str]) -> dict:
    keep = [p for p in pairs if not (no_openai and "openai" in (providers[p["review_1"]], providers[p["review_2"]]))]
    dec = [(p, decided[p["pair_id"]]) for p in keep if decided.get(p["pair_id"])]
    out = {"pairs": len(keep), "decided": len(dec)}

    def tracks(version, concerns, prompt=None):
        k = n = 0
        for p, w in dec:
            if p["version"] != version or (prompt and p["template_id"] != prompt):
                continue
            a, b = (count(codes, x, concerns, level, which) for x in (p["review_1"], p["review_2"]))
            if a != b:
                n += 1
                k += w == (p["review_1"] if a > b else p["review_2"])
        return result(k, n)

    sets = {"all 8 concerns": CONCERNS, "reliably coded only": [c for c in CONCERNS if c in reliable]}
    out["agreement"] = {name: tracks("flawed", cs) for name, cs in sets.items()}
    out["agreement_by_prompt"] = {p: tracks("flawed", CONCERNS, p) for p in PROMPTS}
    out["agreement_by_type"] = {t: tracks("flawed", [c for c in CONCERNS if TYPES[c] == t]) for t in TYPE_ORDER}
    missed = {}
    for c in CONCERNS:
        k = n = 0
        for p, w in dec:
            if p["version"] != "flawed":
                continue
            a, b = (raised(code_of(codes, x, c, which), level) for x in (p["review_1"], p["review_2"]))
            if a != b:
                n += 1
                k += w == (p["review_2"] if a else p["review_1"])
        missed[c] = result(k, n)
    out["preferred_but_missed"] = missed
    out["raised_on_clean"] = {name: tracks("clean", cs) for name, cs in sets.items()}
    return out


def main():
    ap = argparse.ArgumentParser(description="Judge analysis (no API call)")
    ap.add_argument("batch_id"); ap.add_argument("--coding", required=True)
    ap.add_argument("--read", required=True); ap.add_argument("--tables", required=True)
    args = ap.parse_args()
    git = git_state()
    if git["commit"] == "unknown" or git["dirty"] is not False:
        raise SystemExit("The analysis needs a committed, clean working tree, so the output names the code that made it.")
    paths = load_paths()
    jdir = paths.data_dir / "judge" / args.batch_id
    batch = json.loads((jdir / "batch.json").read_text(encoding="utf-8"))
    pfile = paths.data_dir / "judge" / "pairs" / batch["plan_id"] / "pairs.json"
    pairs = json.loads(pfile.read_text(encoding="utf-8"))["pairs"]
    cdir = paths.data_dir / "coding" / args.coding
    codes, _ = llm_codes(cdir, args.read)
    tfile = cdir / "tables" / args.tables / "tables.json"
    status = json.loads(tfile.read_text(encoding="utf-8"))["five_in_six"]
    reliable = [c for c, s in status.items() if s != "not reliably coded"]
    cbatch = json.loads((cdir / "batch.json").read_text(encoding="utf-8"))
    blinding, b_sha = load_blinding(paths, load_plan(REPO / cbatch["plan_file"]))
    if b_sha != cbatch["blinding"]["sha256"]:
        raise SystemExit("blinding.json differs from the one the coding batch started with.")
    providers = {r["blind_id"]: r["provider"] for r in blinding["reviews"]}
    by_id = {p["pair_id"]: p for p in pairs}
    calls = read_jsonl(jdir / "calls.jsonl")
    v = verdicts(calls)
    out = {"judges": {}}
    for judge in (GPT_JUDGE, QWEN_JUDGE):
        both = {pid: o for (j, pid), o in v.items() if j == judge}
        decided = {pid: o["12"] for pid, o in both.items() if len(o) == 2 and o["12"] == o["21"]}
        first_wins = sum((o.get("12") == by_id[pid]["review_1"]) + (o.get("21") == by_id[pid]["review_2"])
                         for pid, o in both.items())
        judged = sum(len(o) for o in both.values())
        res = {"pairs_judged_both_orders": sum(len(o) == 2 for o in both.values()), "decided": len(decided),
               "share_first_position_wins": first_wins / judged if judged else None, "results": {}}
        for which in ("lower", "higher") + (("sonnet",) if judge == QWEN_JUDGE else ()):
            for level in ("F", "FP"):
                for no_openai in (False, True):
                    key = f"{which}|{level}|{'no OpenAI pairs' if no_openai else 'all pairs'}"
                    res["results"][key] = analyse(pairs, decided, codes, providers, which, level, no_openai, reliable)
        out["judges"][judge] = res
    out["reliable_concerns"] = reliable
    stamp = utc_now().replace(':', '').replace('-', '')[:15] + "Z"
    od = jdir / "analysis" / stamp
    inputs = {"judge_batch": args.batch_id, "coding_batch": args.coding, "read": args.read, "tables": args.tables,
              "tables_sha256": sha256_file(tfile), "pairs_sha256": sha256_file(pfile), "calls_sha256": sha256_file(jdir / "calls.jsonl"),
              "created_utc": utc_now(), "operator": paths.operator, "git": git, "harness_version": HARNESS_VERSION}
    write_once(od / "inputs.json", json.dumps(inputs, indent=2).encode("utf-8"))
    write_once(od / "judge_analysis.json", json.dumps(out, indent=1).encode("utf-8"))
    print(f"Judge analysis -> {od}")
    for judge, res in out["judges"].items():
        a = res["results"]["lower|F|all pairs"]["agreement"]["all 8 concerns"]
        b = res["results"]["higher|F|all pairs"]["agreement"]["all 8 concerns"]
        print(f"  {judge}: decided {res['decided']} of 240; outcome 1 (F, all 8): {a['share']:.2f} (n {a['n']}) to "
              f"{b['share']:.2f} (n {b['n']})")


if __name__ == "__main__":
    main()

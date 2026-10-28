"""Results tables for a coding batch (coding sheet v1.0, section 5). No API call.

Inputs: the LLM codes as read again under a named rule set (reads/<rules>-<time>/), the blinding file, and the human-check
codes (both coders' first codes and the agreed codes) exported by tools/export_human_codes.py. Output: tables/<time>/
beside the batch, written once.

Final codes. Where the two LLM coders give the same code, that is the final code. Where they differ, every result is
computed twice, once with the lower and once with the higher of the two codes (F > P > –). Criticism counts are the
average of the two LLM coders' counts. Agreement is measured on first codes (for an unsure code, the provisional one).
The agreed human codes are used only to check each LLM coder (five in six of the shared reviews).

    python -m harness.tables <batch_id> --read <reads folder> --human human_check/human_codes.json
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from . import HARNESS_VERSION
from .code import load_blinding, load_plan
from .common import REPO, git_state, load_paths, sha256_file, utc_now
from .plans import load_models
from .records import read_jsonl, write_once

CONCERNS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]
TITLES = {"C1": "Does the status gap actually narrow?", "C2": "Could the firms’ own status have changed?",
          "C3": "Why change the rules for everyone?", "C4": "Does the extra check measure the same thing?",
          "C5": "Are related observations treated as independent?",
          "C6": "Does the analysis test the difference it claims?",
          "C7": "Could unmeasured capabilities still explain the result?",
          "C8": "Do more opportunities mean better selection?"}
# Construction-register labels (decision of 12 Oct 2026).
TYPES = {"C1": "Taste/mixed", "C2": "Mixed", "C3": "Taste/mixed", "C4": "Technical/mixed", "C5": "Technical",
         "C6": "Technical", "C7": "Technical/mixed", "C8": "Taste/mixed"}
TYPE_ORDER = ["Technical", "Technical/mixed", "Mixed", "Taste/mixed"]
PROMPTS = {"p1_bare_v1": "Bare", "p2_reader_v1": "Reader instructions", "p3_criteria_v1": "Reader + criteria"}
VERSIONS = {"flawed": "Planted", "clean": "Clean"}
RANK = {"–": 0, "P": 1, "F": 2}
MAIN_MODELS = ["claude-fable-5-1", "claude-haiku-5-5", "gpt-6-astra", "gpt-6-luna", "gemini-4-argon",
               "gemini-3-5-flash-lite", "deepseek-v4p1-flash", "kimi-k3"]
CODERS = ("claude-sonnet-5-5", "qwen3p8-2p4t-a95b")
PASS = 5 / 6


# ---------- inputs ----------

def llm_codes(bdir: Path, read_dir: str) -> tuple[dict, dict]:
    """{(blind_id, coder): {C1: code, ...}} and {(blind_id, coder): criticism count} from the selected attempts."""
    rd = bdir / "reads" / read_dir
    selected = {s["run_id"]: s for s in read_jsonl(rd / "selected.jsonl") if s["run_id"]}
    codes, counts = {}, {}
    for row in read_jsonl(rd / "codes.jsonl"):
        if row["run_id"] in selected:
            key = (row["blind_id"], row["coder_key"])
            codes[key] = {c: row["codes"]["concerns"][c]["code"] for c in CONCERNS}
            counts[key] = row["codes"]["criticism_count"]
    return codes, counts


def human_codes(path: Path) -> dict:
    """{"coder1"|"coder2"|"agreed": {(blind_id, concern): code}} from the exported human-check file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {n: {(r["blind_id"], r["concern"]): r["code"] for r in data[n]} for n in ("coder1", "coder2", "agreed")}
    if not (set(out["coder1"]) == set(out["coder2"]) == set(out["agreed"])):
        raise SystemExit("The human-check file covers different cells for the two coders.")
    for d in out.values():
        if set(d.values()) - set(RANK):
            raise SystemExit("The human-check file holds a code other than F, P or –.")
    return out


# ---------- statistics ----------

def agreement(a: list[str], b: list[str]) -> dict:
    """Share of identical codes, Cohen's kappa and Gwet's AC1 over the three codes."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa = {k: sum(x == k for x in a) / n for k in RANK}
    pb = {k: sum(y == k for y in b) / n for k in RANK}
    pe_k = sum(pa[k] * pb[k] for k in RANK)
    pi = {k: (pa[k] + pb[k]) / 2 for k in RANK}
    pe_g = sum(pi[k] * (1 - pi[k]) for k in RANK) / (len(RANK) - 1)
    return {"n": n, "same": sum(x == y for x, y in zip(a, b)), "agreement": po,
            "kappa": None if pe_k == 1 else (po - pe_k) / (1 - pe_k),
            "ac1": None if pe_g == 1 else (po - pe_g) / (1 - pe_g)}


def raised(code: str, level: str) -> bool:
    return code == "F" if level == "F" else code in ("F", "P")


def share(rows: list[dict], concerns: list[str], level: str, which: str) -> float | None:
    """Share of (review, concern) cells raised at the level, with lower or higher codes, or one coder's codes."""
    hits = total = 0
    for r in rows:
        for c in concerns:
            a, b = r["codes"][CODERS[0]][c], r["codes"][CODERS[1]][c]
            code = {"lower": min(a, b, key=RANK.get), "higher": max(a, b, key=RANK.get),
                    CODERS[0]: a, CODERS[1]: b}[which]
            hits += raised(code, level); total += 1
    return hits / total if total else None


def per_review(rows: list[dict], level: str, which: str) -> float | None:
    """Mean number of the eight concerns raised per review."""
    if not rows:
        return None
    return share(rows, CONCERNS, level, which) * len(CONCERNS)


def any_run(rows: list[dict], level: str, which: str) -> int:
    """Number of the eight concerns raised in at least one of the reviews."""
    return sum(any(share([r], [c], level, which) for r in rows) for c in CONCERNS)


def mean_count(rows: list[dict]) -> float | None:
    vals = [(r["counts"][CODERS[0]] + r["counts"][CODERS[1]]) / 2 for r in rows]
    return sum(vals) / len(vals) if vals else None


# ---------- tables ----------

def build(reviews: list[dict], humans: dict, reviewers: dict, sample_ids: list[str]) -> dict:
    main = [r for r in reviews if r["purpose"] == "main"]
    T = {}

    # 1. Agreement on first codes
    shared = [r for r in reviews if r["blind_id"] in sample_ids]
    t1 = []
    for c in CONCERNS + ["All"]:
        cs = CONCERNS if c == "All" else [c]
        def pair(get_a, get_b, rows):
            a = [get_a(r, x) for r in rows for x in cs]; b = [get_b(r, x) for r in rows for x in cs]
            return agreement(a, b)
        son = lambda r, x: r["codes"][CODERS[0]][x]
        qw = lambda r, x: r["codes"][CODERS[1]][x]
        h1 = lambda r, x: humans["coder1"][(r["blind_id"], x)]
        h2 = lambda r, x: humans["coder2"][(r["blind_id"], x)]
        ag = lambda r, x: humans["agreed"][(r["blind_id"], x)]
        row = {"concern": c, "llm_llm": pair(son, qw, reviews), "human_human": pair(h1, h2, shared),
               "coder1_sonnet": pair(h1, son, shared), "coder1_qwen": pair(h1, qw, shared),
               "coder2_sonnet": pair(h2, son, shared), "coder2_qwen": pair(h2, qw, shared),
               "sonnet_agreed": pair(son, ag, shared), "qwen_agreed": pair(qw, ag, shared)}
        if c != "All":
            row["sonnet_passes"] = row["sonnet_agreed"]["agreement"] >= PASS
            row["qwen_passes"] = row["qwen_agreed"]["agreement"] >= PASS
        t1.append(row)
    T["agreement"] = t1
    status = {}
    for row in t1[:-1]:
        s, q = row["sonnet_passes"], row["qwen_passes"]
        status[row["concern"]] = ("both coders pass" if s and q else "Sonnet only" if s else "Qwen only" if q
                                  else "not reliably coded")
    T["five_in_six"] = status
    # Coding sheet v1.0, section 5: a concern on which only one LLM coder passes is also reported with that coder alone.
    single = {c: CODERS[0] if s == "Sonnet only" else CODERS[1] for c, s in status.items() if s in ("Sonnet only", "Qwen only")}

    # Provider check: does Sonnet code reviews by Claude models differently from Qwen, relative to other reviews?
    claude = [r for r in main if r["provider"] == "anthropic"]; other = [r for r in main if r["provider"] != "anthropic"]
    T["provider_check"] = {g: {lvl: {"sonnet": share(rows, CONCERNS, lvl, CODERS[0]),
                                     "qwen": share(rows, CONCERNS, lvl, CODERS[1]), "n_reviews": len(rows)}
                               for lvl in ("F", "FP")}
                           for g, rows in (("Claude reviews", claude), ("Other reviews", other))}

    def cell(rows, cs, lvl):
        return {"lower": share(rows, cs, lvl, "lower"), "higher": share(rows, cs, lvl, "higher"), "n": len(rows) * len(cs)}

    # 2. Who caught what: planted version, main runs, concern x model
    planted = [r for r in main if r["version"] == "flawed"]
    T["by_model"] = {lvl: {c: {m: cell([r for r in planted if r["model_key"] == m], [c], lvl) for m in MAIN_MODELS}
                           for c in CONCERNS} for lvl in ("F", "FP")}
    T["by_model_per_review"] = {lvl: {m: {w: per_review([r for r in planted if r["model_key"] == m], lvl, w)
                                          for w in ("lower", "higher")} for m in MAIN_MODELS} for lvl in ("F", "FP")}
    # Repeated runs (table shells of 9 Oct): concerns raised in at least one of a model's planted-version runs.
    T["by_model_any_run"] = {lvl: {m: {w: any_run([r for r in planted if r["model_key"] == m], lvl, w)
                                       for w in ("lower", "higher")} for m in MAIN_MODELS} for lvl in ("F", "FP")}

    # 3. Type x prompt: planted version, main runs
    groups = {**{t: [c for c in CONCERNS if TYPES[c] == t] for t in TYPE_ORDER}, "All": CONCERNS}
    T["type_prompt"] = {lvl: {t: {p: cell([r for r in planted if r["prompt"] == p], cs, lvl) for p in PROMPTS}
                              for t, cs in groups.items()} for lvl in ("F", "FP")}

    # 4. Planted vs clean, by concern (main runs, all models and prompts)
    clean = [r for r in main if r["version"] == "clean"]
    rows_c = {**{c: [c] for c in CONCERNS}, "All": CONCERNS}
    T["planted_clean"] = {lvl: {c: {"planted": cell(planted, cs, lvl), "clean": cell(clean, cs, lvl)}
                                for c, cs in rows_c.items()} for lvl in ("F", "FP")}
    one = lambda rows, c, lvl, who: {"share": share(rows, [c], lvl, who), "n": len(rows)}
    T["single_coder"] = {c: {"coder": who,
                             "by_model": {lvl: {m: one([r for r in planted if r["model_key"] == m], c, lvl, who)
                                                for m in MAIN_MODELS} for lvl in ("F", "FP")},
                             "planted_clean": {lvl: {"planted": one(planted, c, lvl, who), "clean": one(clean, c, lvl, who)}
                                               for lvl in ("F", "FP")}}
                         for c, who in single.items()}
    T["planted_clean_by_prompt"] = {lvl: {p: {v: cell([r for r in main if r["prompt"] == p and r["version"] == v],
                                                      CONCERNS, lvl) for v in VERSIONS} for p in PROMPTS}
                                    for lvl in ("F", "FP")}

    # 5. Construction tag
    T["construction"] = {lvl: {tag: {v: {w: per_review([r for r in main if r["construction"] == tag and r["version"] == v], lvl, w)
                                         for w in ("lower", "higher")} for v in VERSIONS}
                               for tag in ("used in construction", "not used in construction")} for lvl in ("F", "FP")}

    # 6. Effort (GPT-6 Astra, prompt 3) and 7. format (Gemini 4 Argon, prompt 2)
    def arm(rows):
        return {v: {"n": len([r for r in rows if r["version"] == v]),
                    **{f"{lvl}_{w}": per_review([r for r in rows if r["version"] == v], lvl, w)
                       for lvl in ("F", "FP") for w in ("lower", "higher")},
                    "criticisms": mean_count([r for r in rows if r["version"] == v])} for v in VERSIONS}
    T["effort"] = {"low": arm([r for r in reviews if r["model_key"] == "gpt-6-astra-effort-low"]),
                   "default": arm([r for r in main if r["model_key"] == "gpt-6-astra" and r["prompt"] == "p3_criteria_v1"]),
                   "max": arm([r for r in reviews if r["model_key"] == "gpt-6-astra-effort-max"])}
    T["format"] = {"PDF": arm([r for r in main if r["model_key"] == "gemini-4-argon" and r["prompt"] == "p2_reader_v1"]),
                   "Text + figures": arm([r for r in reviews if r["model_key"] == "gemini-4-argon-mdfig"])}

    # 8. Criticism counts (main runs)
    T["criticisms"] = {"by_model": {m: {v: mean_count([r for r in main if r["model_key"] == m and r["version"] == v])
                                        for v in VERSIONS} for m in MAIN_MODELS},
                       "by_prompt": {p: {v: mean_count([r for r in main if r["prompt"] == p and r["version"] == v])
                                         for v in VERSIONS} for p in PROMPTS},
                       "all": {v: mean_count([r for r in main if r["version"] == v]) for v in VERSIONS}}
    T["labels"] = {"models": {m: reviewers[m]["label"] for m in reviewers}, "titles": TITLES, "types": TYPES,
                   "prompts": PROMPTS, "versions": VERSIONS}
    return T


def assemble(bdir: Path, read_dir: str, blinding: dict, reviewers: dict) -> list[dict]:
    codes, counts = llm_codes(bdir, read_dir)
    reviews = []
    for b in blinding["reviews"]:
        k = b["blind_id"]
        if any((k, c) not in codes for c in CODERS):
            raise SystemExit(f"{k}: missing codes from a coder")
        m = reviewers[b["model_key"]]
        reviews.append({"blind_id": k, "purpose": b["review_purpose"], "model_key": b["model_key"],
                        "provider": b["provider"], "construction": m["construction"], "version": b["version"],
                        "prompt": b["template_id"], "rep": b["rep"],
                        "codes": {c: codes[(k, c)] for c in CODERS}, "counts": {c: counts[(k, c)] for c in CODERS}})
    return reviews


def main():
    ap = argparse.ArgumentParser(description="Results tables for a coding batch (no API call)")
    ap.add_argument("batch_id"); ap.add_argument("--read", required=True)
    ap.add_argument("--human", required=True, help="human-check codes, relative to the batch folder")
    args = ap.parse_args()
    git = git_state()
    if git["commit"] == "unknown" or git["dirty"] is not False:
        raise SystemExit("Tables need a committed, clean working tree, so the output names the code that made it.")
    paths = load_paths()
    bdir = paths.data_dir / "coding" / args.batch_id
    batch = json.loads((bdir / "batch.json").read_text(encoding="utf-8"))
    plan = load_plan(REPO / batch["plan_file"])
    blinding, b_sha = load_blinding(paths, plan)
    if b_sha != batch["blinding"]["sha256"]:
        raise SystemExit("blinding.json differs from the one the batch started with.")
    sample = json.loads((paths.data_dir / "coding" / "blinding" / plan["plan_id"] / "human_sample.json").read_text(encoding="utf-8"))
    reviewers = load_models()["reviewers"]
    reviews = assemble(bdir, args.read, blinding, reviewers)
    hfile = bdir / args.human
    humans = human_codes(hfile)
    sample_ids = sorted({k for k, _ in humans["coder1"]})
    core = sorted(s["blind_id"] for s in sample["core"])
    if sample_ids != core:
        raise SystemExit("The human forms do not cover exactly the core 24 drawn at blinding.")
    tables = build(reviews, humans, reviewers, sample_ids)
    stamp = utc_now().replace(':', '').replace('-', '')[:15] + "Z"
    out = bdir / "tables" / stamp
    inputs = {"batch_id": args.batch_id, "read": args.read, "created_utc": utc_now(), "operator": paths.operator,
              "git": git, "harness_version": HARNESS_VERSION, "blinding_sha256": batch["blinding"]["sha256"],
              "human_codes": {"file": args.human, "sha256": sha256_file(hfile),
                              "sources": json.loads(hfile.read_text(encoding="utf-8"))["sources"]},
              "human_reviews": sample_ids, "n_reviews": len(reviews)}
    write_once(out / "inputs.json", json.dumps(inputs, indent=2, ensure_ascii=False).encode("utf-8"))
    write_once(out / "tables.json", json.dumps(tables, indent=2, ensure_ascii=False).encode("utf-8"))
    print(f"Tables -> {out}")
    for c, s in tables["five_in_six"].items():
        print(f"  {c}: {s}")


if __name__ == "__main__":
    main()

"""Coding runs: blinding, the human sample, the coding prompt, and reading a coder's answer.

Blinding. Every complete review in the review batches named by the coding plan gets a random ID (B001, B002, ...)
in an order shuffled with the plan's seed. A coder receives only the coding sheet and the review text. The table that
joins blind IDs to review runs is kept in blinding.json and is used again only to unblind.

Human sample (coding sheet v1.0, section 5). Forty main reviews, drawn before any review is coded:
  core 24  three per model, one per prompt. Half of the models give flawed, clean, flawed for the three prompts and
           the other half clean, flawed, clean; the two models of each provider (the two open-weight models count as
           one provider) are split between the halves, so each version and prompt pair appears four times.
  other 16 two per model, one per version, with the prompts spread as evenly as possible.
The core is coded first; within each set the reviews are shown by blind ID in random order.
"""
from __future__ import annotations

import json
import random
import re

from .common import sha256_file

VERSIONS = ("flawed", "clean")
CONCERNS = tuple(f"C{i}" for i in range(1, 9))
CODE_FORMS = {"F": "F", "P": "P", "–": "–", "-": "–", "—": "–", "−": "–"}
QUOTE_MAX_WORDS = 40


# ---------------------------------------------------------------- the reviews to code

def collect_reviews(review_dir, batch_ids: list[str]) -> list[dict]:
    """The complete review of every slot in the named review batches, read from their run records."""
    out = []
    for bid in batch_ids:
        bdir = review_dir / bid
        batch = json.loads((bdir / "batch.json").read_text(encoding="utf-8"))
        calls = [json.loads(line) for line in (bdir / "calls.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        ok: dict[int, dict] = {}
        for c in calls:
            if c.get("status") == "ok":
                if c["slot"] in ok:
                    raise SystemExit(f"{bid}: slot {c['slot']} has more than one complete review")
                ok[c["slot"]] = c
        missing = [s["slot"] for s in batch["slots"] if s["slot"] not in ok]
        if missing:
            raise SystemExit(f"{bid}: slots without a complete review: {missing}")
        for c in sorted(ok.values(), key=lambda r: r["slot"]):
            path = bdir / c["text_file"]
            if sha256_file(path) != c["text_sha256"]:
                raise SystemExit(f"{bid}: {c['text_file']} differs from its call record")
            out.append({"review_batch_id": bid, "review_purpose": batch["purpose"], "review_run_id": c["run_id"],
                        "review_slot": c["slot"], "model_key": c["model_key"], "provider": c["provider"],
                        "template_id": c["template_id"], "manuscript": c["manuscript"], "version": c["version"],
                        "rep": c["rep"], "text_file": f"{bid}/{c['text_file']}", "text_sha256": c["text_sha256"]})
    return out


def blind(reviews: list[dict], seed) -> list[dict]:
    """Shuffle with the plan's seed and number B001, B002, ... in the shuffled order."""
    rows = sorted(reviews, key=lambda r: (r["review_batch_id"], r["review_slot"]))
    random.Random(f"{seed}:blinding").shuffle(rows)
    width = max(3, len(str(len(rows))))
    return [{"blind_id": f"B{i:0{width}d}", **r} for i, r in enumerate(rows, 1)]


# ---------------------------------------------------------------- human sample

def draw_human_sample(blinded: list[dict], seed) -> dict:
    rng = random.Random(f"{seed}:human-sample")
    main = [r for r in blinded if r["review_purpose"] == "main"]
    models = sorted({r["model_key"] for r in main})
    prompts = sorted({r["template_id"] for r in main})
    if len(prompts) != 3:
        raise SystemExit(f"Expected three prompts in the main reviews, found {prompts}")
    by_provider: dict[str, list[str]] = {}
    for m in models:
        prov = next(r["provider"] for r in main if r["model_key"] == m)
        by_provider.setdefault(prov, []).append(m)
    if any(len(v) != 2 for v in by_provider.values()):
        raise SystemExit(f"Expected two models per provider, found {by_provider}")
    cells: dict[tuple, list[dict]] = {}
    for r in main:
        cells.setdefault((r["model_key"], r["template_id"], r["version"]), []).append(r)
    for v in cells.values():
        v.sort(key=lambda r: r["review_run_id"])

    half_a, half_b = [], []
    for prov in sorted(by_provider):
        pair = sorted(by_provider[prov])
        rng.shuffle(pair)
        half_a.append(pair[0])
        half_b.append(pair[1])
    pattern = {"A": ("flawed", "clean", "flawed"), "B": ("clean", "flawed", "clean")}

    chosen: set[str] = set()

    def pick(model, prompt, version, set_name):
        pool = [r for r in cells[(model, prompt, version)] if r["blind_id"] not in chosen]
        r = rng.choice(pool)
        chosen.add(r["blind_id"])
        return {"blind_id": r["blind_id"], "set": set_name, "model_key": model, "template_id": prompt,
                "version": version, "review_run_id": r["review_run_id"]}

    core = []
    for half, ms in (("A", sorted(half_a)), ("B", sorted(half_b))):
        for m in ms:
            for p, v in zip(prompts, pattern[half]):
                core.append({**pick(m, p, v, "core"), "half": half})

    # Other 16: one flawed and one clean per model on different prompts; across models, prompt counts 3/3/2
    # for one version and 3/2/3 for the other, so the prompts total 6/5/5.
    order = prompts[:]
    rng.shuffle(order)
    flawed_prompts = [order[0]] * 3 + [order[1]] * 3 + [order[2]] * 2
    clean_prompts = [order[0]] * 3 + [order[1]] * 2 + [order[2]] * 3
    for _ in range(10_000):
        rng.shuffle(flawed_prompts)
        rng.shuffle(clean_prompts)
        if all(f != c for f, c in zip(flawed_prompts, clean_prompts)):
            break
    else:
        raise SystemExit("Could not place the other 16 with different prompts per model")
    extra = []
    for m, pf, pc in zip(models, flawed_prompts, clean_prompts):
        extra.append(pick(m, pf, "flawed", "extra"))
        extra.append(pick(m, pc, "clean", "extra"))

    rng.shuffle(core)
    rng.shuffle(extra)
    for i, r in enumerate(core, 1):
        r["order"] = i
    for i, r in enumerate(extra, len(core) + 1):
        r["order"] = i
    return {"seed": seed, "halves": {"A": sorted(half_a), "B": sorted(half_b)}, "patterns": pattern,
            "prompts": prompts, "core": core, "extra": extra}


# ---------------------------------------------------------------- the prompt

SHEET_SLOT, REVIEW_SLOT = "{CODING_SHEET}", "{REVIEW}"


def split_template(template: str, sheet: str, review: str) -> tuple[str, str]:
    """Fill the coding template. Returns (fixed part ending before the review, part with the review). The fixed part
    is the same in every call, so a cache breakpoint can follow it."""
    if template.count(SHEET_SLOT) != 1 or template.count(REVIEW_SLOT) != 1:
        raise SystemExit("A coding template needs exactly one {CODING_SHEET} and one {REVIEW}")
    i = template.index(REVIEW_SLOT)
    if template.index(SHEET_SLOT) > i:
        raise SystemExit("The coding sheet must come before the review in a coding template")
    return template[:i].replace(SHEET_SLOT, sheet), template[i:].replace(REVIEW_SLOT, review, 1)


# ---------------------------------------------------------------- reading the answer

def extract_json(text: str) -> dict:
    """The JSON object with a 'concerns' field in the coder's text (thinking tags and code fences ignored)."""
    t = re.sub(r"(?s)<think>.*?</think>", "", text)
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", t):
        try:
            obj, _ = dec.raw_decode(t, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and "concerns" in obj:
            return obj
    raise ValueError("no JSON object with a 'concerns' field")


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("−", "-").replace(" ", " ")
    s = re.sub(r"[*_`$\\]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_found(quote: str, review: str) -> bool:
    """Every part of the quote (parts joined by an ellipsis) appears in the review, ignoring case, quote style,
    dash style, Markdown emphasis and spacing."""
    body = _norm(review)
    parts = [p.strip(" .,;:'\"()[]") for p in re.split(r"…|\.\.\.", _norm(quote))]
    parts = [p for p in parts if p]
    return bool(parts) and all(p in body for p in parts)


READ_RULES = {
    "strict": "as the coding template asks: every concern gives 'unsure', and criticism_count equals the list length",
    "rules_2026_10_24": ("decided by Investigator 1 on 2026-10-24 (worklog): a concern without an 'unsure' field is read as not "
                         "unsure; a criticism_count that differs from the list is replaced by the list length, and the "
                         "stated count is kept"),
}


def read_answer(text: str, review: str, rules: str = "strict") -> tuple[dict | None, list[str]]:
    """Returns (codes, problems). codes is None when no JSON object could be read. Quote checks are recorded
    with each code but are not problems: a quote that is not found is flagged for the coders' report.
    rules: 'strict' (used during the calls) or 'rules_2026_10_24' (the separate re-read step)."""
    if rules not in READ_RULES:
        raise ValueError(f"unknown reading rules {rules!r}")
    lenient = rules == "rules_2026_10_24"
    applied = []
    try:
        obj = extract_json(text)
    except ValueError as e:
        return None, [str(e)]
    problems = []
    raw = obj.get("concerns")
    if not isinstance(raw, list):
        return None, ["'concerns' is not a list"]
    concerns: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            problems.append(f"concern entry is not an object: {item!r:.80}")
            continue
        cid = str(item.get("concern", "")).strip().upper()
        if cid not in CONCERNS:
            problems.append(f"unknown concern {cid!r}")
            continue
        if cid in concerns:
            problems.append(f"{cid} given twice")
            continue
        code = CODE_FORMS.get(str(item.get("code", "")).strip())
        if code is None:
            problems.append(f"{cid}: code {item.get('code')!r} is not F, P or –")
        quote = item.get("quote") or ""
        why = item.get("why") or ""
        if code in ("F", "P") and not (isinstance(quote, str) and quote.strip()):
            problems.append(f"{cid}: {code} without a quote")
        if code in ("F", "P") and not (isinstance(why, str) and why.strip()):
            problems.append(f"{cid}: {code} without a reason")
        unsure = item.get("unsure")
        if lenient and unsure is None:
            unsure = False
            applied.append(f"{cid}: no 'unsure' field, read as not unsure")
        if not isinstance(unsure, bool):
            problems.append(f"{cid}: 'unsure' is not true or false")
            unsure = bool(unsure)
        alt = CODE_FORMS.get(str(item.get("alternative_code") or "").strip()) if unsure else None
        reason = (item.get("unsure_reason") or "") if unsure else ""
        if unsure and (alt is None or alt == code):
            problems.append(f"{cid}: unsure without a different alternative code")
        if unsure and not str(reason).strip():
            problems.append(f"{cid}: unsure without a reason")
        entry = {"code": code, "quote": quote if code in ("F", "P") else "", "why": why if code in ("F", "P") else "",
                 "unsure": unsure, "alternative_code": alt, "unsure_reason": reason or None}
        if code in ("F", "P") and isinstance(quote, str) and quote.strip():
            entry["quote_words"] = len(quote.split())
            entry["quote_over_40_words"] = entry["quote_words"] > QUOTE_MAX_WORDS
            entry["quote_found_in_review"] = quote_found(quote, review)
        concerns[cid] = entry
    missing = [c for c in CONCERNS if c not in concerns]
    if missing:
        problems.append("missing concerns: " + ", ".join(missing))
    crit = obj.get("criticisms")
    count = obj.get("criticism_count")
    if not isinstance(crit, list) or not all(isinstance(c, str) for c in crit):
        problems.append("'criticisms' is not a list of strings")
        crit = crit if isinstance(crit, list) else []
    stated = count
    if not isinstance(count, int) or isinstance(count, bool):
        problems.append("'criticism_count' is not a whole number")
    elif count != len(crit):
        if lenient:
            count = len(crit)
            applied.append(f"criticism_count {stated} replaced by the {len(crit)} criticisms listed")
        else:
            problems.append(f"criticism_count {count} differs from the {len(crit)} criticisms listed")
    codes = {"concerns": {c: concerns[c] for c in CONCERNS if c in concerns},
             "criticism_count": count, "criticisms": crit}
    if lenient:
        codes.update({"criticism_count_stated": stated, "read_rules": rules, "read_rules_applied": applied})
    return codes, problems


def quote_flags(codes: dict | None) -> dict:
    if not codes:
        return {"quotes": 0, "not_found_in_review": 0, "over_40_words": 0}
    q = [e for e in codes["concerns"].values() if "quote_found_in_review" in e]
    return {"quotes": len(q), "not_found_in_review": sum(not e["quote_found_in_review"] for e in q),
            "over_40_words": sum(e["quote_over_40_words"] for e in q)}

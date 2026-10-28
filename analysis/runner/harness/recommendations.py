"""Recommendations stated in the main reviews (run plan section 8). No API call.

Prompts 2 and 3 asked each reviewer to state Reject, Major revision, Minor revision or Accept. The stated recommendation is
taken from the text after "recommend..." or "verdict" (160 characters each). A review is read automatically when every
such passage that names an option names the same single option; otherwise, and for any prompt 2 or 3 review that names
none, it goes to a hand check, shown by blind ID only. Prompt 1 reviews count only if they state a recommendation, and
are reported separately.

    python -m harness.recommendations extract                     # extraction.jsonl and hand_check.csv
    python -m harness.recommendations tables <folder> --hand H.json  # distributions after the hand check
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import re

from . import HARNESS_VERSION
from .code import load_blinding, load_plan
from .common import REPO, git_state, load_paths, sha256_bytes, sha256_file, utc_now
from .records import read_jsonl, write_once

OPTIONS = ["Reject", "Major revision", "Minor revision", "Accept"]
PATTERNS = {"Reject": r"\breject(?:ion)?\b", "Major revision": r"\bmajor\s+revisions?\b",
            "Minor revision": r"\bminor\s+revisions?\b", "Accept": r"\baccept\b"}
CUE = re.compile(r"recommend\w*|verdict", re.I)
WINDOW = 160


def passages(text: str) -> list[tuple[str, list[str]]]:
    """Each recommendation passage with the options it names, in text order."""
    plain = re.sub(r"[*_#`]+", "", text)
    out = []
    for m in CUE.finditer(plain):
        w = plain[m.start(): m.start() + WINDOW]
        named = [o for o in OPTIONS if re.search(PATTERNS[o], w, re.I)]
        if named:
            out.append((" ".join(w.split()), named))
    return out


def read(text: str) -> tuple[str | None, str]:
    """(option or None, 'auto' | 'hand' | 'none')."""
    ps = passages(text)
    if not ps:
        return None, "none"
    sets = {tuple(n) for _, n in ps}
    if len(sets) == 1 and len(ps[-1][1]) == 1:
        return ps[-1][1][0], "auto"
    return None, "hand"


def cmd_extract(args):
    git = git_state()
    if git["commit"] == "unknown" or git["dirty"] is not False:
        raise SystemExit("Needs a committed, clean working tree, so the output names the code that made it.")
    paths = load_paths()
    plan = load_plan(REPO / "plans" / "coding_v1.yaml")
    blinding, b_sha = load_blinding(paths, plan)
    rows, hand = [], []
    for r in blinding["reviews"]:
        if r["review_purpose"] != "main":
            continue
        data = (paths.data_dir / "review" / r["text_file"]).read_bytes()
        if sha256_bytes(data) != r["text_sha256"]:
            raise SystemExit(f"{r['text_file']} differs from the hash recorded at blinding")
        text = data.decode("utf-8")
        option, how = read(text)
        if how == "none" and r["template_id"] != "p1_bare_v1":
            how = "hand"
        rows.append({"blind_id": r["blind_id"], "model_key": r["model_key"], "provider": r["provider"],
                     "version": r["version"], "template_id": r["template_id"], "option": option, "read": how})
        if how == "hand":
            ps = passages(text)
            hand.append([r["blind_id"], " || ".join(p for p, _ in ps) or "(no passage after 'recommend' or 'verdict'; "
                                                                         "see the review's last lines)",
                         " ".join(text[-400:].split())])
    stamp = utc_now().replace(':', '').replace('-', '')[:15] + "Z"
    out = paths.data_dir / "recommendations" / stamp
    write_once(out / "extraction.jsonl", "".join(json.dumps(x) + "\n" for x in rows).encode("utf-8"))
    buf = io.StringIO()
    w = csv.writer(buf); w.writerow(["blind_id", "passages", "last_400_characters"]); w.writerows(sorted(hand))
    write_once(out / "hand_check.csv", buf.getvalue().encode("utf-8-sig"))
    write_once(out / "extract.json", json.dumps({"created_utc": utc_now(), "operator": paths.operator, "git": git,
                                                  "harness_version": HARNESS_VERSION, "blinding_sha256": b_sha,
                                                  "rules": __doc__.split("\n\n")[1],
                                                  "counts": collections.Counter(x["read"] for x in rows)},
                                                 indent=2).encode("utf-8"))
    print(f"Extraction -> {out}")
    print("  ", dict(collections.Counter((x["template_id"], x["read"]) for x in rows)))


def cmd_tables(args):
    git = git_state()
    if git["commit"] == "unknown" or git["dirty"] is not False:
        raise SystemExit("Needs a committed, clean working tree, so the output names the code that made it.")
    paths = load_paths()
    folder = paths.data_dir / "recommendations" / args.folder
    rows = read_jsonl(folder / "extraction.jsonl")
    hfile = folder / args.hand
    hand = json.loads(hfile.read_text(encoding="utf-8"))["decisions"]
    for x in rows:
        if x["read"] == "hand":
            if x["blind_id"] not in hand or hand[x["blind_id"]] not in OPTIONS + ["none stated"]:
                raise SystemExit(f"No hand decision for {x['blind_id']}")
            x["option"] = None if hand[x["blind_id"]] == "none stated" else hand[x["blind_id"]]
    def dist(sel):
        c = collections.Counter(x["option"] or "none stated" for x in sel)
        return {k: c.get(k, 0) for k in OPTIONS + ["none stated"]} | {"n": len(sel)}
    p23 = [x for x in rows if x["template_id"] != "p1_bare_v1"]
    p1 = [x for x in rows if x["template_id"] == "p1_bare_v1"]
    models = sorted({x["model_key"] for x in rows})
    T = {"prompts_2_3": {v: dist([x for x in p23 if x["version"] == v]) for v in ("flawed", "clean")},
         "by_prompt": {p: {v: dist([x for x in rows if x["template_id"] == p and x["version"] == v]) for v in ("flawed", "clean")}
                       for p in ("p1_bare_v1", "p2_reader_v1", "p3_criteria_v1")},
         "by_model_prompts_2_3": {m: {v: dist([x for x in p23 if x["model_key"] == m and x["version"] == v])
                                      for v in ("flawed", "clean")} for m in models},
         "prompt_1_by_model": {m: {v: dist([x for x in p1 if x["model_key"] == m and x["version"] == v])
                                   for v in ("flawed", "clean")} for m in models}}
    stamp = utc_now().replace(':', '').replace('-', '')[:15] + "Z"
    out = folder / "tables" / stamp
    write_once(out / "inputs.json", json.dumps({"extraction": args.folder, "hand": args.hand, "hand_sha256": sha256_file(hfile),
                                                "created_utc": utc_now(), "operator": paths.operator, "git": git},
                                               indent=2).encode("utf-8"))
    write_once(out / "recommendations.json", json.dumps(T, indent=1).encode("utf-8"))
    print(f"Tables -> {out}")


def main():
    ap = argparse.ArgumentParser(description="Recommendations in the main reviews (no API call)")
    sub = ap.add_subparsers(required=True)
    s = sub.add_parser("extract"); s.set_defaults(fn=cmd_extract)
    s = sub.add_parser("tables"); s.add_argument("folder"); s.add_argument("--hand", required=True); s.set_defaults(fn=cmd_tables)
    args = ap.parse_args(); args.fn(args)


if __name__ == "__main__":
    main()

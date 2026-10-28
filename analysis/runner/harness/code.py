"""Coding runs (workflow: Blinding -> two LLM coders on every review; human sample drawn at blinding).

  python -m harness.code blind   plans/coding_v1.yaml       # blinding.json and human_sample.json; no API call
  python -m harness.code dry-run plans/coding_v1.yaml       # builds every request; no API call; kept local
  python -m harness.code start   plans/coding_v1.yaml --live [--coders KEY ...]
  python -m harness.code resume  BATCH_ID --live [--coders KEY ...]
  python -m harness.code rerun   BATCH_ID --slots 3 7 --reason "HTTP 529 overloaded" --live
  python -m harness.code status  BATCH_ID
  python -m harness.code read    BATCH_ID --rules rules_2026_10_24   # read every answer again; no API call

A coder receives one user message: the coding template with the frozen coding sheet, then the review text exactly
as the reviewing model returned it. It is not told the review's model, manuscript version or prompt. The coding
sheet is read from the local path in config/paths.local.yaml and must match the SHA-256 in the plan; it never
enters the repository.

Record layout (data_dir/coding/, kept apart from the review runs because it contains the key):
  coding/blinding/<plan_id>/blinding.json       blind ID -> review run and text hash; written once
  coding/blinding/<plan_id>/human_sample.json   the human-check sample; written once, before any coding call
  coding/<batch_id>/batch.json, events.jsonl, calls.jsonl
  coding/<batch_id>/requests/<run_id>.json      the exact request sent (includes the coding sheet)
  coding/<batch_id>/raw/<run_id>.json           the provider response or error, unedited
  coding/<batch_id>/text/<run_id>.md            the coder's answer exactly as returned
  coding/<batch_id>/codes/<run_id>.json         the codes read from that answer, with the checks
No file is ever overwritten. A rerun is a new attempt with a new run ID, its parent run ID and a reason.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import json
import platform
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

from . import HARNESS_VERSION
from .coding import (READ_RULES, blind, collect_reviews, draw_human_sample, quote_flags, read_answer,
                     split_template)
from .common import (REPO, git_state, key_fingerprints, load_api_keys, load_paths, load_template, load_yaml,
                     sha256_bytes, sha256_file, utc_now)
from .inputs import ManuscriptInput, Segment
from .plans import load_models
from .providers import BUILDERS, ENDPOINTS
from .records import (append_jsonl, classify, estimate_cost, load_prices, read_jsonl, repo_relative, sdk_versions,
                      write_json_once, write_once)
from .review import ENV_NEEDED, check_env, require_live, snapshot_models

MAX_CONSECUTIVE_ERRORS = 3
# Words that would identify a review's source if the harness had added them; the review texts are scanned and the
# counts kept in the batch record (a reviewing model may name itself; nothing is removed from a review).
SOURCE_WORDS = re.compile(r"(?i)\b(claude|fable|haiku|gpt-?6|astra|luna|gemini|argon|flash-lite|deepseek|kimi|qwen|"
                          r"pilot-v6|clean-matched|flawed version|clean version)\b")


@dataclass(frozen=True)
class CodingSlot:
    slot: int
    coder_key: str
    blind_id: str

    def to_dict(self) -> dict:
        return asdict(self)


def run_id(batch_id: str, slot: int, attempt: int) -> str:
    return f"{batch_id}-s{slot:04d}-a{attempt}"


def load_plan(path: Path) -> dict:
    plan = load_yaml(path)
    for field in ("plan_id", "purpose", "template", "coders", "review_batches", "coding_sheet", "seed"):
        if field not in plan:
            raise SystemExit(f"{path}: missing '{field}'")
    return plan


def blinding_dir(paths, plan_id: str) -> Path:
    return paths.data_dir / "coding" / "blinding" / plan_id


def load_blinding(paths, plan: dict) -> tuple[dict, str]:
    f = blinding_dir(paths, plan["plan_id"]) / "blinding.json"
    if not f.exists():
        raise SystemExit(f"{f} not found: run 'python -m harness.code blind {plan['plan_id']}' first.")
    return json.loads(f.read_text(encoding="utf-8")), sha256_file(f)


def coding_sheet_path() -> Path:
    """Read here and only here, so the review runner's path loader never learns where the coding sheet is."""
    cfg = load_yaml(REPO / "config" / "paths.local.yaml")
    if not cfg.get("coding_sheet"):
        raise SystemExit("config/paths.local.yaml has no coding_sheet path.")
    p = Path(cfg["coding_sheet"]).resolve()
    if REPO in p.parents:
        raise SystemExit(f"{p} is inside the repository; the coding sheet must live outside it.")
    return p


def load_sheet(plan: dict) -> str:
    path = coding_sheet_path()
    actual = sha256_file(path)
    if actual != plan["coding_sheet"]["sha256"]:
        raise SystemExit(f"Coding sheet {path.name} has SHA-256 {actual[:12]}…, not the frozen "
                         f"{plan['coding_sheet']['sha256'][:12]}… in the plan.")
    return path.read_text(encoding="utf-8").rstrip("\n")


# ---------------------------------------------------------------- preparing a batch

class Prepared:
    """Template, coding sheet, coder configurations and blinded review texts, checked once."""

    def __init__(self, plan: dict, coders: dict, paths, blinding: dict):
        self.plan, self.coders, self.paths = plan, coders, paths
        self.template = load_template("coding", plan["template"])
        self.sheet = load_sheet(plan)
        self.reviews = {r["blind_id"]: r for r in blinding["reviews"]}
        self.texts = {}
        for bid, r in self.reviews.items():
            p = paths.data_dir / "review" / r["text_file"]
            data = p.read_bytes()
            if sha256_bytes(data) != r["text_sha256"]:
                raise SystemExit(f"{r['text_file']} differs from the hash recorded at blinding")
            self.texts[bid] = data.decode("utf-8")

    def build(self, s: CodingSlot):
        cfg = self.coders[s.coder_key]
        fixed, with_review = split_template(self.template.text, self.sheet, self.texts[s.blind_id])
        mi = ManuscriptInput(manuscript="coding sheet", input_format="text", segments=[Segment(kind="text", text=fixed)])
        call = BUILDERS[cfg["route"]](cfg, mi, with_review)
        if cfg["route"] == "anthropic_api":
            call.settings["prompt_caching"] = "ephemeral breakpoint after the coding sheet"
        return call


def expand(plan: dict, coders: dict, blinding: dict) -> list[CodingSlot]:
    slots, n = [], 0
    for c in plan["coders"]:
        if c not in coders:
            raise SystemExit(f"Unknown coder '{c}' (see config/models.yaml, coders)")
        for r in blinding["reviews"]:
            n += 1
            slots.append(CodingSlot(n, c, r["blind_id"]))
    return slots


def batch_dir(paths, batch_id: str) -> Path:
    return paths.data_dir / "coding" / batch_id


# ---------------------------------------------------------------- one call

def do_call(prep: Prepared, bdir: Path, batch: dict, s: CodingSlot, attempt: int, git: dict, operator: str,
            parent: str | None = None, reason: str | None = None) -> dict:
    cfg = prep.coders[s.coder_key]
    tpl = prep.template
    rid = run_id(batch["batch_id"], s.slot, attempt)
    review_text = prep.texts[s.blind_id]
    call = prep.build(s)
    req_sha = write_json_once(bdir / "requests" / f"{rid}.json", call.request)

    record = {
        "record_version": 1, "run_id": rid, "batch_id": batch["batch_id"], "slot": s.slot, "attempt": attempt,
        "parent_run_id": parent, "rerun_reason": reason, "purpose": batch["purpose"], "plan_id": batch["plan_id"],
        "operator": operator, "git_commit": git["commit"], "git_dirty": git["dirty"], "harness_version": HARNESS_VERSION,
        "coder_key": s.coder_key, "coder_label": cfg["label"], "provider": cfg["provider"], "route": cfg["route"],
        "model_requested": cfg["model_id"], "model_returned": None,
        "blind_id": s.blind_id, "review_text_sha256": prep.reviews[s.blind_id]["text_sha256"],
        "coding_sheet_version": batch["coding_sheet"]["version"], "coding_sheet_sha256": batch["coding_sheet"]["sha256"],
        "template_id": tpl.template_id, "template_file": tpl.file, "template_sha256": tpl.sha256,
        "request_file": f"requests/{rid}.json", "request_sha256": req_sha,
        "settings": call.settings, "effort_reported": "unknown",
        "effort_default_documented": cfg.get("effort_default", "unknown"), "time_sent_utc": utc_now(),
    }
    empty = {"stop_reason": None, "usage": None, "cost_estimate": {"usd": "unknown"}, "text_file": None,
             "text_sha256": None, "text_chars": 0, "codes_file": None, "codes_sha256": None, "problems": None,
             "quote_flags": None, "criticism_count": None}
    t0 = time.monotonic()
    try:
        resp = call.send()
    except Exception as e:                                             # recorded, never retried silently
        record.update({"time_received_utc": utc_now(), "seconds": round(time.monotonic() - t0, 3)})
        http = getattr(e, "response", None)
        err = {"type": type(e).__name__, "message": str(e), "status_code": getattr(e, "status_code", None),
               "request_id": getattr(e, "request_id", None), "body": getattr(http, "text", None) if http is not None else None,
               "traceback": traceback.format_exc()}
        raw_sha = write_json_once(bdir / "raw" / f"{rid}.json", {"error": err})
        record.update({**empty, "status": "error", "request_id": err["request_id"], "raw_file": f"raw/{rid}.json",
                       "raw_sha256": raw_sha, "error": {k: err[k] for k in ("type", "message", "status_code", "request_id")}})
        append_jsonl(bdir / "calls.jsonl", record)
        return record

    record.update({"time_received_utc": utc_now(), "seconds": round(time.monotonic() - t0, 3)})
    try:                                                               # the paid response is saved first
        raw = call.dump(resp)
    except Exception as e:
        raw = {"dump_error": f"{type(e).__name__}: {e}", "repr": repr(resp)}
    raw_sha = write_json_once(bdir / "raw" / f"{rid}.json", raw)
    record.update({"raw_file": f"raw/{rid}.json", "raw_sha256": raw_sha})
    try:
        result = call.parse(resp)
    except Exception as e:
        record.update({**empty, "status": "parse_error", "request_id": None,
                       "error": {"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc()}})
        append_jsonl(bdir / "calls.jsonl", record)
        return record

    text = result["text"]
    text_sha = write_once(bdir / "text" / f"{rid}.md", text.encode("utf-8"))
    status = classify(result)
    codes, problems = (read_answer(text, review_text) if status == "ok" else (None, None))
    if status == "ok" and (codes is None or problems):
        status = "invalid_output"
    codes_file = codes_sha = None
    if codes is not None:
        codes_sha = write_json_once(bdir / "codes" / f"{rid}.json",
                                    {"run_id": rid, "blind_id": s.blind_id, "coder_key": s.coder_key,
                                     "problems": problems, **codes})
        codes_file = f"codes/{rid}.json"
    record.update({
        "model_returned": result["model_returned"], "request_id": result["request_id"],
        "effort_reported": result["effort_reported"], "status": status, "stop_reason": result["stop_reason"],
        "usage": result["usage"], "usage_provider_fields": result.get("usage_provider_fields"),
        "settings_reported": result.get("settings_reported", "not reported by the provider"),
        "cost_estimate": estimate_cost(cfg["model_id"], result["usage"], batch["prices"]),
        "text_file": f"text/{rid}.md", "text_sha256": text_sha, "text_chars": len(text),
        "codes_file": codes_file, "codes_sha256": codes_sha, "problems": problems,
        "quote_flags": quote_flags(codes), "criticism_count": codes.get("criticism_count") if codes else None,
        "error": None,
    })
    append_jsonl(bdir / "calls.jsonl", record)
    return record


def run_queue(prep, bdir, batch, jobs, git, operator) -> list[dict]:
    """jobs: (slot, attempt, parent, reason) for one coder, one call at a time. After three errors in a row the
    queue stops; slots not yet attempted stay open for resume."""
    out, errors = [], 0
    for i, (s, attempt, parent, reason) in enumerate(jobs):
        rec = do_call(prep, bdir, batch, s, attempt, git, operator, parent, reason)
        print(f"  {rec['run_id']}  {s.coder_key:20s} {s.blind_id}  {rec['status']:14s} {rec['seconds']:>7.1f}s", flush=True)
        out.append(rec)
        errors = errors + 1 if rec["status"] == "error" else 0
        if errors >= MAX_CONSECUTIVE_ERRORS and i + 1 < len(jobs):
            left = [j[0].slot for j in jobs[i + 1:]]
            append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "queue stopped", "coder": s.coder_key,
                                                 "reason": f"{errors} errors in a row; last: {rec['error']['message'][:300]}",
                                                 "slots_not_attempted": left})
            print(f"  QUEUE STOPPED for {s.coder_key} after {errors} errors in a row; {len(left)} slots left for resume",
                  flush=True)
            break
    return out


def run_jobs(prep, bdir, batch, jobs, git, operator, workers: int | None = None):
    """Each coder's jobs are split into `workers_per_coder` queues that run in parallel; the coders run in parallel.
    The review order is already shuffled at blinding, so running order carries no information about the reviews.
    resume and rerun may set a different number of queues (--workers); it is recorded in events.jsonl. Requests and
    settings are unchanged; only how many calls run at once differs."""
    w = workers or batch["workers_per_coder"]
    by_coder: dict[str, list] = {}
    for j in jobs:
        by_coder.setdefault(j[0].coder_key, []).append(j)
    queues = [q[i::w] for q in by_coder.values() for i in range(w) if q[i::w]]
    with cf.ThreadPoolExecutor(max_workers=max(1, len(queues))) as ex:
        for f in [ex.submit(run_queue, prep, bdir, batch, q, git, operator) for q in queues]:
            f.result()


# ---------------------------------------------------------------- commands

def cmd_blind(args):
    paths = load_paths()
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    out = blinding_dir(paths, plan["plan_id"])
    if (out / "blinding.json").exists():
        raise SystemExit(f"{out / 'blinding.json'} already exists; blinding is done once per plan.")
    reviews = collect_reviews(paths.data_dir / "review", plan["review_batches"])
    blinded = blind(reviews, plan["seed"])
    head = {"plan_id": plan["plan_id"], "plan_file": repo_relative(plan_path), "plan_sha256": sha256_file(plan_path),
            "seed": plan["seed"], "created_utc": utc_now(), "operator": paths.operator, "git": git_state(),
            "harness_version": HARNESS_VERSION, "review_batches": plan["review_batches"]}
    b_sha = write_json_once(out / "blinding.json", {**head, "n_reviews": len(blinded), "reviews": blinded})
    sample = draw_human_sample(blinded, plan["seed"])
    write_json_once(out / "human_sample.json", {**head, "blinding_sha256": b_sha, **sample})
    by_batch = collections.Counter(r["review_batch_id"] for r in blinded)
    print(f"Blinded {len(blinded)} reviews -> {out}")
    for b, n in by_batch.items():
        print(f"  {b}: {n}")
    for name in ("core", "extra"):
        rows = sample[name]
        print(f"Human sample, {name}: {len(rows)} reviews; per version x prompt: "
              + ", ".join(f"{v}/{p.split('_')[0]} {n}" for (v, p), n in
                          sorted(collections.Counter((r['version'], r['template_id']) for r in rows).items()))
              + "; per model: " + str(sorted(set(collections.Counter(r['model_key'] for r in rows).values()))))


def source_word_counts(texts: dict[str, str]) -> dict:
    hits = collections.Counter()
    reviews_with_hits = 0
    for t in texts.values():
        found = {m.group(0).lower() for m in SOURCE_WORDS.finditer(t)}
        hits.update(found)
        reviews_with_hits += bool(found)
    return {"pattern": SOURCE_WORDS.pattern, "reviews_with_any_word": reviews_with_hits,
            "reviews_per_word": dict(sorted(hits.items())),
            "note": "Counts of words in the review texts as returned; nothing was removed. The harness adds no "
                    "model, version, prompt or run label to what a coder receives."}


def cmd_dry_run(args):
    paths = load_paths()
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    coders = load_models()["coders"]
    blinding, b_sha = load_blinding(paths, plan)
    prep = Prepared(plan, coders, paths, blinding)
    slots = expand(plan, coders, blinding)
    out = paths.dry_run_dir / f"{plan['plan_id']}-{utc_now().replace(':', '').replace('-', '')[:15]}Z"
    chars = collections.defaultdict(list)
    written = collections.Counter()
    for s in slots:
        call = prep.build(s)                                   # every request is built
        text = json.dumps(call.request, ensure_ascii=False)
        for label in (prep.reviews[s.blind_id]["review_run_id"], prep.reviews[s.blind_id]["review_batch_id"]):
            if label in text:
                raise SystemExit(f"Request for {s.blind_id} contains the label {label}")
        chars[s.coder_key].append(len(text))
        if written[s.coder_key] < 3:
            write_json_once(out / "requests" / f"{s.coder_key}__{s.blind_id}.json",
                            {"request": call.request, "settings": call.settings})
            written[s.coder_key] += 1
    summary = {"plan_id": plan["plan_id"], "plan_sha256": sha256_file(plan_path), "slots": len(slots),
               "git": git_state(), "template": {"file": prep.template.file, "sha256": prep.template.sha256},
               "coding_sheet": plan["coding_sheet"], "blinding_sha256": b_sha,
               "request_chars": {k: {"calls": len(v), "mean": round(sum(v) / len(v)), "max": max(v)} for k, v in chars.items()},
               "source_words_in_reviews": source_word_counts(prep.texts)}
    write_json_once(out / "summary.json", summary)
    print(f"Dry run of {plan['plan_id']}: {len(slots)} slots built, no API called. Requests carry no run or batch label.")
    for k, v in summary["request_chars"].items():
        print(f"  {k:20s} {v['calls']:4d} calls, request about {v['mean'] // 4:,} tokens on average (chars / 4)")
    print(f"First requests per coder and summary written to {out}")


def cmd_start(args):
    git = require_live(args)
    paths = load_paths()
    load_api_keys(paths.keys_file)
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    coders = load_models()["coders"]
    blinding, b_sha = load_blinding(paths, plan)
    prep = Prepared(plan, coders, paths, blinding)
    slots = expand(plan, coders, blinding)
    run_slots = [s for s in slots if not args.coders or s.coder_key in args.coders]
    check_env({coders[c]["route"] for c in plan["coders"]})
    review_iso = {}
    for bid in plan["review_batches"]:
        rb = json.loads((paths.data_dir / "review" / bid / "batch.json").read_text(encoding="utf-8"))
        review_iso[bid] = rb["isolation"]
    batch_id = f"{plan['plan_id']}-{utc_now().replace(':', '').replace('-', '')[:15]}Z"
    bdir = batch_dir(paths, batch_id)
    used = {k: coders[k] for k in plan["coders"]}
    meta = snapshot_models(used)
    batch = {
        "batch_id": batch_id, "plan_id": plan["plan_id"], "purpose": plan["purpose"],
        "plan_file": repo_relative(plan_path), "plan_sha256": sha256_file(plan_path), "created_utc": utc_now(),
        "operator": paths.operator, "git": git, "harness_version": HARNESS_VERSION, "sdk_versions": sdk_versions(),
        "python": platform.python_version(), "platform": platform.platform(),
        "template": {"id": prep.template.template_id, "file": prep.template.file, "sha256": prep.template.sha256},
        "coding_sheet": {**plan["coding_sheet"], "file_name": coding_sheet_path().name},
        "answer_key_sha256": paths.key_sha256,
        "answer_key_note": "The coders receive the frozen coding sheet, which carries the key's content; the key files "
                           "themselves are not sent.",
        "blinding": {"file": f"blinding/{plan['plan_id']}/blinding.json", "sha256": b_sha, "seed": plan["seed"],
                     "n_reviews": len(blinding["reviews"])},
        "review_batches": plan["review_batches"], "review_runs_isolation": review_iso,
        "review_runs_could_not_read_key": all(i.get("passed") and i.get("key_path_available_to_review_runner") is False
                                              for i in review_iso.values()),
        "source_words_in_reviews": source_word_counts(prep.texts),
        "coders": used, "models_yaml_sha256": sha256_file(REPO / "config" / "models.yaml"),
        "model_metadata": meta,
        "weights": {k: ("open weights; exact weight files are not exposed by Fireworks serverless, so their hash "
                        "cannot be recorded; provider metadata above" if v["route"] == "fireworks_serverless"
                        else "closed model") for k, v in used.items()},
        "workers_per_coder": plan.get("workers_per_coder", 1), "prices": load_prices(),
        "slots": [s.to_dict() for s in slots],
        "endpoints": {r: ENDPOINTS[r] for r in sorted({c["route"] for c in used.values()})},
        "api_key_fingerprints": key_fingerprints([v for c in used.values() for v in ENV_NEEDED[c["route"]]]),
    }
    write_json_once(bdir / "batch.json", batch)
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "start", "coders": args.coders or "all",
                                         "git": git, "operator": paths.operator})
    print(f"Batch {batch_id}: {len(run_slots)} of {len(slots)} slots now -> {bdir}")
    run_jobs(prep, bdir, batch, [(s, 1, None, None) for s in run_slots], git, paths.operator)


def load_batch(paths, batch_id: str):
    bdir = batch_dir(paths, batch_id)
    return bdir, json.loads((bdir / "batch.json").read_text(encoding="utf-8"))


def prepare_existing(batch: dict, paths) -> Prepared:
    """Resume and rerun use the coder configurations, template, sheet and blinding the batch started with."""
    coders = load_models()["coders"]
    for k, cfg in batch["coders"].items():
        if coders.get(k) != cfg:
            raise SystemExit(f"config/models.yaml coder '{k}' differs from the one batch {batch['batch_id']} started with.")
    plan = load_plan(REPO / batch["plan_file"])
    if sha256_file(REPO / batch["plan_file"]) != batch["plan_sha256"]:
        raise SystemExit("The plan file changed after the batch started.")
    blinding, b_sha = load_blinding(paths, plan)
    if b_sha != batch["blinding"]["sha256"]:
        raise SystemExit("blinding.json differs from the one the batch started with.")
    check_env({c["route"] for c in batch["coders"].values()})
    prep = Prepared(plan, batch["coders"], paths, blinding)
    if prep.template.sha256 != batch["template"]["sha256"]:
        raise SystemExit("The coding template differs from the one the batch started with.")
    return prep


def attempts(bdir: Path) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for rec in read_jsonl(bdir / "calls.jsonl"):
        out.setdefault(rec["slot"], []).append(rec)
    return out


def mark_interrupted(bdir: Path, batch: dict, git: dict, operator: str) -> None:
    recorded = {r["run_id"] for r in read_jsonl(bdir / "calls.jsonl")}
    for req in sorted((bdir / "requests").glob("*.json")):
        rid = req.stem
        if rid not in recorded:
            slot, attempt = rid.rsplit("-s", 1)[1].split("-a")
            append_jsonl(bdir / "calls.jsonl", {
                "record_version": 1, "run_id": rid, "batch_id": batch["batch_id"], "slot": int(slot),
                "attempt": int(attempt), "status": "interrupted", "operator": operator, "git_commit": git["commit"],
                "noted_utc": utc_now(), "request_file": f"requests/{rid}.json", "request_sha256": sha256_file(req),
                "note": "request written but no response recorded; the outcome of this call is unknown"})


def cmd_resume(args):
    git = require_live(args)
    paths = load_paths()
    load_api_keys(paths.keys_file)
    bdir, batch = load_batch(paths, args.batch_id)
    mark_interrupted(bdir, batch, git, paths.operator)
    done = attempts(bdir)
    todo = [CodingSlot(**d) for d in batch["slots"]
            if d["slot"] not in done and (not args.coders or d["coder_key"] in args.coders)]
    prep = prepare_existing(batch, paths)
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "resume", "coders": args.coders or "all",
                                         "workers_per_coder": args.workers or batch["workers_per_coder"],
                                         "slots": [s.slot for s in todo], "git": git, "operator": paths.operator,
                                         "api_key_fingerprints": key_fingerprints(
                                             [v for c in batch["coders"].values() for v in ENV_NEEDED[c["route"]]])})
    print(f"Batch {batch['batch_id']}: {len(todo)} slots not yet attempted")
    run_jobs(prep, bdir, batch, [(s, 1, None, None) for s in todo], git, paths.operator, args.workers)


def cmd_rerun(args):
    git = require_live(args)
    if not args.reason or len(args.reason.strip()) < 5:
        raise SystemExit("A rerun needs --reason.")
    paths = load_paths()
    load_api_keys(paths.keys_file)
    bdir, batch = load_batch(paths, args.batch_id)
    mark_interrupted(bdir, batch, git, paths.operator)
    done = attempts(bdir)
    by_slot = {d["slot"]: CodingSlot(**d) for d in batch["slots"]}
    jobs = []
    for n in args.slots:
        if n not in done:
            raise SystemExit(f"Slot {n} has no attempt yet; use resume.")
        if any(r["status"] == "ok" for r in done[n]):
            raise SystemExit(f"Slot {n} already has complete codes; it is not rerun.")
        last = max(done[n], key=lambda r: r["attempt"])
        jobs.append((by_slot[n], last["attempt"] + 1, last["run_id"], args.reason.strip()))
    prep = prepare_existing(batch, paths)
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "rerun", "slots": args.slots,
                                         "reason": args.reason.strip(), "workers_per_coder": args.workers or batch["workers_per_coder"],
                                         "git": git, "operator": paths.operator})
    run_jobs(prep, bdir, batch, jobs, git, paths.operator, args.workers)


def load_review_texts(paths, blinding: dict) -> dict[str, str]:
    texts = {}
    for r in blinding["reviews"]:
        data = (paths.data_dir / "review" / r["text_file"]).read_bytes()
        if sha256_bytes(data) != r["text_sha256"]:
            raise SystemExit(f"{r['text_file']} differs from the hash recorded at blinding")
        texts[r["blind_id"]] = data.decode("utf-8")
    return texts


def read_records(bdir: Path, records: list[dict], texts: dict[str, str], rules: str,
                 slots: list[dict]) -> tuple[list[dict], list[dict]]:
    """Read every saved answer again with the given rules. Returns one row per attempt read and one row per slot of
    the batch naming the attempt that enters the analysis: the latest attempt whose answer reads without problems.
    Coder and blind ID come from the batch's slot list, since an interrupted attempt's record does not carry them."""
    rows = []
    for r in records:
        if not r.get("text_file"):
            continue
        data = (bdir / r["text_file"]).read_bytes()
        if sha256_bytes(data) != r["text_sha256"]:
            raise SystemExit(f"{r['text_file']} differs from its call record")
        codes, problems = (read_answer(data.decode("utf-8"), texts[r["blind_id"]], rules)
                           if r["status"] in ("ok", "invalid_output") else (None, [f"call status {r['status']}"]))
        rows.append({"run_id": r["run_id"], "slot": r["slot"], "attempt": r["attempt"], "coder_key": r["coder_key"],
                     "blind_id": r["blind_id"], "call_status": r["status"],
                     "read_status": "ok" if codes is not None and not problems else "problems",
                     "problems": problems, "quote_flags": quote_flags(codes), "codes": codes})
    by_slot: dict[int, list[dict]] = {}
    for row in rows:
        by_slot.setdefault(row["slot"], []).append(row)
    selected = []
    for s in sorted(slots, key=lambda s: s["slot"]):
        good = [x for x in by_slot.get(s["slot"], []) if x["read_status"] == "ok"]
        pick = max(good, key=lambda x: x["attempt"]) if good else None
        selected.append({"slot": s["slot"], "coder_key": s["coder_key"], "blind_id": s["blind_id"],
                         "run_id": pick["run_id"] if pick else None})
    return rows, selected


def cmd_read(args):
    """Read every saved answer again (no API call). Output goes to reads/<rules>-<time>/; call records are unchanged."""
    git = git_state()
    if git["commit"] == "unknown" or git["dirty"] is not False:
        raise SystemExit("Reading needs a committed, clean working tree, so the output names the code that read it.")
    paths = load_paths()
    bdir, batch = load_batch(paths, args.batch_id)
    plan = load_plan(REPO / batch["plan_file"])
    blinding, b_sha = load_blinding(paths, plan)
    if b_sha != batch["blinding"]["sha256"]:
        raise SystemExit("blinding.json differs from the one the batch started with.")
    records = read_jsonl(bdir / "calls.jsonl")
    rows, selected = read_records(bdir, records, load_review_texts(paths, blinding), args.rules, batch["slots"])
    stamp = utc_now().replace(':', '').replace('-', '')[:15] + "Z"
    out = bdir / "reads" / f"{args.rules}-{stamp}"
    notes = [(row["codes"] or {}).get("read_rules_applied") or [] for row in rows]
    applied = {"answers_with_unsure_missing": sum(any("no 'unsure' field" in a for a in n) for n in notes),
               "answers_with_count_replaced": sum(any(a.startswith("criticism_count") for a in n) for n in notes)}
    summary = {
        "batch_id": batch["batch_id"], "rules": args.rules, "rules_text": READ_RULES[args.rules],
        "created_utc": utc_now(), "operator": paths.operator, "git": git, "harness_version": HARNESS_VERSION,
        "calls_jsonl_sha256": sha256_file(bdir / "calls.jsonl"), "attempts_read": len(rows),
        "slots": len(selected), "slots_with_codes": sum(s["run_id"] is not None for s in selected),
        "slots_without_codes": [s["slot"] for s in selected if s["run_id"] is None],
        "rules_applied": dict(applied),
        "quote_flags": dict(sum((collections.Counter(r["quote_flags"]) for r in rows if r["read_status"] == "ok"),
                                collections.Counter())),
    }
    write_once(out / "codes.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))
    write_once(out / "selected.jsonl", "".join(json.dumps(s) + "\n" for s in selected).encode("utf-8"))
    write_json_once(out / "read.json", summary)
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "read", "rules": args.rules,
                                         "output": f"reads/{out.name}", "git": git, "operator": paths.operator})
    by_coder = collections.Counter((s["coder_key"], s["run_id"] is not None) for s in selected)
    print(f"Read {len(rows)} answers with rules '{args.rules}' -> {out}")
    for (c, has), n in sorted(by_coder.items()):
        print(f"  {c:20s} {'codes' if has else 'no usable codes'}: {n}")
    print(f"  rules applied: {dict(applied)}; quotes: {summary['quote_flags']}")


def cmd_status(args):
    paths = load_paths()
    bdir, batch = load_batch(paths, args.batch_id)
    done = attempts(bdir)
    counts: dict[str, collections.Counter] = {}
    flags = collections.Counter()
    for d in batch["slots"]:
        recs = done.get(d["slot"])
        st = max(recs, key=lambda r: r["attempt"])["status"] if recs else "not attempted"
        counts.setdefault(d["coder_key"], collections.Counter())[st] += 1
        for r in recs or []:
            for k, v in (r.get("quote_flags") or {}).items():
                flags[k] += v
    print(f"Batch {batch['batch_id']} ({len(batch['slots'])} slots)")
    for c, n in counts.items():
        print(f"  {c:20s} " + "  ".join(f"{k}: {v}" for k, v in sorted(n.items())))
    if flags:
        print(f"  quotes: {flags['quotes']}, not found in the review: {flags['not_found_in_review']}, "
              f"over 40 words: {flags['over_40_words']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m harness.code", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("blind"); p.add_argument("plan"); p.set_defaults(fn=cmd_blind)
    p = sub.add_parser("dry-run"); p.add_argument("plan"); p.set_defaults(fn=cmd_dry_run)
    p = sub.add_parser("start"); p.add_argument("plan"); p.add_argument("--live", action="store_true")
    p.add_argument("--coders", nargs="*"); p.set_defaults(fn=cmd_start)
    p = sub.add_parser("resume"); p.add_argument("batch_id"); p.add_argument("--live", action="store_true")
    p.add_argument("--coders", nargs="*"); p.add_argument("--workers", type=int); p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("rerun"); p.add_argument("batch_id"); p.add_argument("--slots", nargs="+", type=int, required=True)
    p.add_argument("--reason", required=True); p.add_argument("--live", action="store_true")
    p.add_argument("--workers", type=int); p.set_defaults(fn=cmd_rerun)
    p = sub.add_parser("read"); p.add_argument("batch_id"); p.add_argument("--rules", choices=sorted(READ_RULES), required=True)
    p.set_defaults(fn=cmd_read)
    p = sub.add_parser("status"); p.add_argument("batch_id"); p.set_defaults(fn=cmd_status)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

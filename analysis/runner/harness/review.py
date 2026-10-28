"""Review runs.

  python -m harness.review dry-run plans/practice_v1.yaml
  python -m harness.review start   plans/practice_v1.yaml --live [--models KEY ...]
  python -m harness.review resume  BATCH_ID --live [--models KEY ...]
  python -m harness.review rerun   BATCH_ID --slots 3 7 --reason "HTTP 529 overloaded" --live
  python -m harness.review status  BATCH_ID

dry-run builds every request and runs the key isolation check without calling any API.
start/resume/rerun call paid APIs and need --live and a clean git working tree.

Record layout (in data_dir, outside the repo):
  review/<batch_id>/batch.json        written once when the batch is created
  review/<batch_id>/events.jsonl      one line per start/resume/rerun command
  review/<batch_id>/calls.jsonl       one line per call, appended, never edited
  review/<batch_id>/requests/<run_id>.json   the exact request sent (binary files as name + SHA-256)
  review/<batch_id>/raw/<run_id>.json        the provider response or error, unedited
  review/<batch_id>/text/<run_id>.md         the review text exactly as returned
No file is ever overwritten. A rerun is a new attempt with a new run ID, its parent run ID and a reason.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path

from . import HARNESS_VERSION, isolation
from .common import (REPO, git_state, key_fingerprints, load_api_keys, load_paths, load_template, load_yaml,
                     sha256_file, utc_now)
from .inputs import load_manuscript
from .plans import Slot, expand, load_models, load_plan
from .providers import BUILDERS, ENDPOINTS, model_metadata
from .records import (append_jsonl, classify, estimate_cost, load_prices, read_jsonl, repo_relative, sdk_versions,
                      write_json_once, write_once)

VERSION_LABEL = {"pilot-v6": "flawed", "clean-matched-v6": "clean"}
INPUT_ROUTE = {
    ("pdf", "anthropic_api"): "PDF as a base64 document block",
    ("pdf", "openai_api"): "PDF as a base64 input_file",
    ("pdf", "gemini_api"): "PDF as inline bytes",
    "md_figures": "Markdown text with each figure PNG placed at its position",
    "md_text": "Markdown text only; figure links left as text",
}
ENV_NEEDED = {
    "anthropic_api": ["ANTHROPIC_API_KEY"],
    "gemini_api": ["GEMINI_API_KEY"],
    "openai_api": ["OPENAI_API_KEY"],
    "fireworks_serverless": ["FIREWORKS_API_KEY"],
}


def input_route(cfg: dict) -> str:
    return INPUT_ROUTE.get((cfg["input_format"], cfg["route"])) or INPUT_ROUTE[cfg["input_format"]]


def run_id(batch_id: str, slot: int, attempt: int) -> str:
    return f"{batch_id}-s{slot:03d}-a{attempt}"


# ---------------------------------------------------------------- preparing a batch

class Prepared:
    """Templates, model configurations and manuscript inputs for a set of slots, checked once."""

    def __init__(self, slots: list[Slot], reviewers: dict, paths):
        self.slots = slots
        self.reviewers = reviewers
        self.paths = paths
        self.templates = {t: load_template("review", t) for t in sorted({s.template_id for s in slots})}
        self.inputs = {}
        for s in slots:
            fmt = reviewers[s.model_key]["input_format"]
            if (s.manuscript, fmt) not in self.inputs:
                self.inputs[(s.manuscript, fmt)] = load_manuscript(paths.inputs_dir, s.manuscript, fmt)
        files = [f for mi in self.inputs.values() for f in mi.files]
        self.isolation = isolation.check(paths.inputs_dir, paths.key_sha256, files)
        manifest = load_yaml(REPO / "prompts" / "manifest.yaml")["review"]
        self.rungs = {t: manifest[t]["rung"] for t in self.templates}

    def build(self, s: Slot):
        cfg = self.reviewers[s.model_key]
        mi = self.inputs[(s.manuscript, cfg["input_format"])]
        return BUILDERS[cfg["route"]](cfg, mi, self.templates[s.template_id].text)


def batch_dir(paths, batch_id: str) -> Path:
    return paths.data_dir / "review" / batch_id


def require_live(args) -> dict:
    if not args.live:
        raise SystemExit("This command calls paid APIs. Add --live to run it, or use dry-run.")
    git = git_state()
    if git["commit"] == "unknown" or git["dirty"] is not False:
        raise SystemExit("Live runs need a committed, clean working tree (git status must be empty).")
    return git


def check_env(routes: set[str]) -> None:
    missing = sorted({v for r in routes for v in ENV_NEEDED[r] if not os.environ.get(v)})
    if missing:
        raise SystemExit("Missing environment variables: " + ", ".join(missing))


# ---------------------------------------------------------------- one call

def do_call(prep: Prepared, bdir: Path, batch: dict, s: Slot, attempt: int, git: dict, operator: str,
            parent: str | None = None, reason: str | None = None) -> dict:
    cfg = prep.reviewers[s.model_key]
    tpl = prep.templates[s.template_id]
    mi = prep.inputs[(s.manuscript, cfg["input_format"])]
    rid = run_id(batch["batch_id"], s.slot, attempt)
    call = prep.build(s)
    req_path = bdir / "requests" / f"{rid}.json"
    req_sha = write_json_once(req_path, call.request)            # written before the call: proof of the attempt

    record = {
        "record_version": 1, "run_id": rid, "batch_id": batch["batch_id"], "slot": s.slot, "attempt": attempt,
        "parent_run_id": parent, "rerun_reason": reason, "purpose": batch["purpose"], "plan_id": batch["plan_id"],
        "rep": s.rep, "operator": operator,
        "git_commit": git["commit"], "git_dirty": git["dirty"], "harness_version": HARNESS_VERSION,
        "model_key": s.model_key, "model_label": cfg["label"], "provider": cfg["provider"], "route": cfg["route"],
        "model_requested": cfg["model_id"], "model_returned": None, "construction": cfg["construction"],
        "manuscript": s.manuscript, "version": VERSION_LABEL[s.manuscript],
        "input_format": cfg["input_format"], "input_route": input_route(cfg), "input_files": mi.files,
        "template_id": tpl.template_id, "template_file": tpl.file, "template_sha256": tpl.sha256,
        "rung": prep.rungs[tpl.template_id],
        "request_file": f"requests/{rid}.json", "request_sha256": req_sha,
        "settings": call.settings, "effort_reported": "unknown",
        "effort_default_documented": cfg.get("effort_default", "unknown"),
        "time_sent_utc": utc_now(),
    }
    empty = {"stop_reason": None, "usage": None, "cost_estimate": {"usd": "unknown"},
             "text_file": None, "text_sha256": None, "text_chars": 0}
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
        record.update({**empty, "status": "error", "request_id": err["request_id"],
                       "raw_file": f"raw/{rid}.json", "raw_sha256": raw_sha,
                       "error": {k: err[k] for k in ("type", "message", "status_code", "request_id")}})
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
    record.update({
        "model_returned": result["model_returned"], "request_id": result["request_id"],
        "effort_reported": result["effort_reported"], "status": classify(result), "stop_reason": result["stop_reason"],
        "usage": result["usage"], "usage_provider_fields": result.get("usage_provider_fields"),
        "settings_reported": result.get("settings_reported", "not reported by the provider"),
        "cost_estimate": estimate_cost(cfg["model_id"], result["usage"], batch["prices"]),
        "text_file": f"text/{rid}.md", "text_sha256": text_sha, "text_chars": len(text), "error": None,
    })
    append_jsonl(bdir / "calls.jsonl", record)
    return record


MAX_CONSECUTIVE_ERRORS = 3


def run_queue(prep, bdir, batch, jobs, git, operator) -> list[dict]:
    """jobs: list of (slot, attempt, parent, reason) for one model, run one at a time. After three errors in a
    row (e.g. no credit left, rate limit, outage) the queue stops; the slots not yet attempted stay open for resume."""
    out, errors = [], 0
    for i, (s, attempt, parent, reason) in enumerate(jobs):
        rec = do_call(prep, bdir, batch, s, attempt, git, operator, parent, reason)
        print(f"  {rec['run_id']}  {s.model_key:24s} {s.template_id:15s} {s.manuscript:17s} "
              f"{rec['status']:9s} {rec['seconds']:>7.1f}s", flush=True)
        out.append(rec)
        errors = errors + 1 if rec["status"] == "error" else 0
        if errors >= MAX_CONSECUTIVE_ERRORS and i + 1 < len(jobs):
            left = [j[0].slot for j in jobs[i + 1:]]
            append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "queue stopped",
                                                 "model_id": prep.reviewers[s.model_key]["model_id"],
                                                 "reason": f"{errors} errors in a row; last: {rec['error']['message'][:300]}",
                                                 "slots_not_attempted": left})
            print(f"  QUEUE STOPPED for {prep.reviewers[s.model_key]['model_id']} after {errors} errors in a row; "
                  f"{len(left)} slots left for resume", flush=True)
            break
    return out


def queues(prep, jobs) -> dict[str, list]:
    by_model: dict[str, list] = {}
    for j in jobs:
        by_model.setdefault(prep.reviewers[j[0].model_key]["model_id"], []).append(j)
    return by_model


def run_jobs(prep, bdir, batch, jobs, git, operator):
    """One queue per underlying model, so configurations of the same model (e.g. effort levels) never run at
    the same time and share that model's rate limit; different models run in parallel."""
    by_model = queues(prep, jobs)
    with cf.ThreadPoolExecutor(max_workers=max(1, len(by_model))) as ex:
        futures = [ex.submit(run_queue, prep, bdir, batch, q, git, operator) for q in by_model.values()]
        for f in futures:
            f.result()


# ---------------------------------------------------------------- commands

def slots_from_batch(batch: dict) -> list[Slot]:
    return [Slot(**d) for d in batch["slots"]]


def attempts(bdir: Path) -> dict[int, list[dict]]:
    by_slot: dict[int, list[dict]] = {}
    for rec in read_jsonl(bdir / "calls.jsonl"):
        by_slot.setdefault(rec["slot"], []).append(rec)
    return by_slot


def mark_interrupted(bdir: Path, batch: dict, git: dict, operator: str) -> None:
    """A request file with no call record means the process stopped during the call: record it as such."""
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


def cmd_dry_run(args):
    paths = load_paths()
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    reviewers = load_models()["reviewers"]
    manifest = load_yaml(REPO / "prompts" / "manifest.yaml")["review"]
    slots = expand(plan, reviewers, manifest)
    prep = Prepared(slots, reviewers, paths)
    out = paths.dry_run_dir / f"{plan['plan_id']}-{utc_now().replace(':', '').replace('-', '')[:15]}Z"
    seen, summary = set(), {}
    for s in slots:
        cfg = reviewers[s.model_key]
        row = summary.setdefault(s.model_key, {"model_id": cfg["model_id"], "route": cfg["route"],
                                               "input": input_route(cfg), "construction": cfg["construction"],
                                               "slots": 0, "env_needed": ENV_NEEDED[cfg["route"]]})
        row["slots"] += 1
        combo = (s.model_key, s.template_id, s.manuscript)
        if combo not in seen:
            seen.add(combo)
            call = prep.build(s)                           # builds the full request, including base64 data
            write_json_once(out / "requests" / f"{s.model_key}__{s.template_id}__{s.manuscript}.json",
                            {"request": call.request, "settings": call.settings})
    write_json_once(out / "summary.json", {
        "plan_id": plan["plan_id"], "plan_sha256": sha256_file(plan_path), "slots": len(slots), "git": git_state(),
        "templates": {t: v.sha256 for t, v in prep.templates.items()}, "isolation": prep.isolation,
        "models": summary, "slot_list": [s.to_dict() for s in slots]})
    print(f"Dry run of {plan['plan_id']}: {len(slots)} slots, no API called. Isolation check passed.")
    for k, r in summary.items():
        print(f"  {k:24s} {r['slots']:4d} slots  {r['route']:21s} {r['input']}")
    print(f"Requests written to {out}")


def snapshot_models(cfgs: dict) -> dict:
    """Provider metadata for each model, taken when calls start (free endpoints)."""
    seen, out = {}, {}
    for k, cfg in cfgs.items():
        key = (cfg["route"], cfg["model_id"])
        if key not in seen:
            seen[key] = {"retrieved_utc": utc_now(), **model_metadata(cfg)}
        out[k] = seen[key]
    return out


def cmd_start(args):
    git = require_live(args)
    paths = load_paths()
    load_api_keys(paths.keys_file)
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    models = load_models()
    reviewers = models["reviewers"]
    manifest = load_yaml(REPO / "prompts" / "manifest.yaml")["review"]
    slots = expand(plan, reviewers, manifest)
    prep = Prepared(slots, reviewers, paths)
    run_slots = [s for s in slots if not args.models or s.model_key in args.models]
    check_env({reviewers[s.model_key]["route"] for s in run_slots})

    batch_id = f"{plan['plan_id']}-{utc_now().replace(':', '').replace('-', '')[:15]}Z"
    bdir = batch_dir(paths, batch_id)
    batch = {
        "batch_id": batch_id, "plan_id": plan["plan_id"], "purpose": plan["purpose"],
        "plan_file": repo_relative(plan_path), "plan_sha256": sha256_file(plan_path), "created_utc": utc_now(),
        "operator": paths.operator, "git": git, "harness_version": HARNESS_VERSION, "sdk_versions": sdk_versions(),
        "python": platform.python_version(), "platform": platform.platform(),
        "templates": {t: {"file": v.file, "sha256": v.sha256} for t, v in prep.templates.items()},
        "models": {k: reviewers[k] for k in sorted({s.model_key for s in slots})},
        "models_yaml_sha256": sha256_file(REPO / "config" / "models.yaml"),
        "inputs": {f"{m}/{fmt}": mi.files for (m, fmt), mi in prep.inputs.items()},
        "isolation": prep.isolation, "prices": load_prices(), "slots": [s.to_dict() for s in slots],
        "model_metadata": snapshot_models({k: reviewers[k] for k in sorted({s.model_key for s in run_slots})}),
        "endpoints": {r: ENDPOINTS[r] for r in sorted({reviewers[s.model_key]["route"] for s in slots})},
        "api_key_fingerprints": key_fingerprints([v for s in run_slots for v in ENV_NEEDED[reviewers[s.model_key]["route"]]]),
    }
    write_json_once(bdir / "batch.json", batch)
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "start", "models": args.models or "all",
                                         "git": git, "operator": paths.operator})
    print(f"Batch {batch_id}: {len(run_slots)} of {len(slots)} slots now -> {bdir}")
    run_jobs(prep, bdir, batch, [(s, 1, None, None) for s in run_slots], git, paths.operator)


def load_batch(paths, batch_id: str):
    bdir = batch_dir(paths, batch_id)
    batch = json.loads((bdir / "batch.json").read_text(encoding="utf-8"))
    return bdir, batch


def prepare_existing(batch: dict, slots: list[Slot], paths) -> Prepared:
    """Resume and rerun use the model configurations and templates the batch started with, unchanged."""
    reviewers = load_models()["reviewers"]
    for k, cfg in batch["models"].items():
        if reviewers.get(k) != cfg:
            raise SystemExit(f"config/models.yaml entry '{k}' differs from the one batch {batch['batch_id']} started with.")
    check_env({reviewers[s.model_key]["route"] for s in slots})
    prep = Prepared(slots, batch["models"], paths)
    for t, v in prep.templates.items():
        if v.sha256 != batch["templates"][t]["sha256"]:
            raise SystemExit(f"Template {t} differs from the one batch {batch['batch_id']} started with.")
    return prep


def cmd_resume(args):
    git = require_live(args)
    paths = load_paths()
    load_api_keys(paths.keys_file)
    bdir, batch = load_batch(paths, args.batch_id)
    mark_interrupted(bdir, batch, git, paths.operator)
    done = attempts(bdir)
    todo = [s for s in slots_from_batch(batch) if s.slot not in done and (not args.models or s.model_key in args.models)]
    prep = prepare_existing(batch, todo, paths)
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "resume", "models": args.models or "all",
                                         "slots": [s.slot for s in todo], "git": git, "operator": paths.operator,
                                         "api_key_fingerprints": key_fingerprints(
                                             [v for s in todo for v in ENV_NEEDED[batch["models"][s.model_key]["route"]]]),
                                         "model_metadata": snapshot_models({s.model_key: batch["models"][s.model_key] for s in todo})})
    print(f"Batch {batch['batch_id']}: {len(todo)} slots not yet attempted")
    run_jobs(prep, bdir, batch, [(s, 1, None, None) for s in todo], git, paths.operator)


def cmd_rerun(args):
    git = require_live(args)
    if not args.reason or len(args.reason.strip()) < 5:
        raise SystemExit("A rerun needs --reason.")
    paths = load_paths()
    load_api_keys(paths.keys_file)
    bdir, batch = load_batch(paths, args.batch_id)
    mark_interrupted(bdir, batch, git, paths.operator)
    done = attempts(bdir)
    by_slot = {s.slot: s for s in slots_from_batch(batch)}
    jobs = []
    for n in args.slots:
        if n not in done:
            raise SystemExit(f"Slot {n} has no attempt yet; use resume.")
        last = max(done[n], key=lambda r: r["attempt"])
        if any(r["status"] == "ok" for r in done[n]):
            raise SystemExit(f"Slot {n} already has a complete review ({last['run_id']}); it is not rerun.")
        jobs.append((by_slot[n], last["attempt"] + 1, last["run_id"], args.reason.strip()))
    prep = prepare_existing(batch, [j[0] for j in jobs], paths)
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "rerun", "slots": args.slots,
                                         "reason": args.reason.strip(), "git": git, "operator": paths.operator,
                                         "api_key_fingerprints": key_fingerprints(
                                             [v for j in jobs for v in ENV_NEEDED[batch["models"][j[0].model_key]["route"]]]),
                                         "model_metadata": snapshot_models({j[0].model_key: batch["models"][j[0].model_key] for j in jobs})})
    run_jobs(prep, bdir, batch, jobs, git, paths.operator)


def cmd_status(args):
    paths = load_paths()
    bdir, batch = load_batch(paths, args.batch_id)
    done = attempts(bdir)
    counts: dict[str, dict[str, int]] = {}
    for s in slots_from_batch(batch):
        st = max(done[s.slot], key=lambda r: r["attempt"])["status"] if s.slot in done else "not attempted"
        counts.setdefault(s.model_key, {}).setdefault(st, 0)
        counts[s.model_key][st] += 1
    print(f"Batch {batch['batch_id']} ({len(batch['slots'])} slots)")
    for m, c in counts.items():
        print(f"  {m:24s} " + "  ".join(f"{k}: {v}" for k, v in sorted(c.items())))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m harness.review", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dry-run"); p.add_argument("plan"); p.set_defaults(fn=cmd_dry_run)
    p = sub.add_parser("start"); p.add_argument("plan"); p.add_argument("--live", action="store_true")
    p.add_argument("--models", nargs="*"); p.set_defaults(fn=cmd_start)
    p = sub.add_parser("resume"); p.add_argument("batch_id"); p.add_argument("--live", action="store_true")
    p.add_argument("--models", nargs="*"); p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("rerun"); p.add_argument("batch_id"); p.add_argument("--slots", nargs="+", type=int, required=True)
    p.add_argument("--reason", required=True); p.add_argument("--live", action="store_true"); p.set_defaults(fn=cmd_rerun)
    p = sub.add_parser("status"); p.add_argument("batch_id"); p.set_defaults(fn=cmd_status)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

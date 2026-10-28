"""Judge runs (exploratory): a judge model chooses the more helpful of two reviews.

  python -m harness.judge pair    plans/judge_v1.yaml        # pairs.json from the coding blinding; no API call
  python -m harness.judge dry-run plans/judge_v1.yaml        # builds every request; no API call; kept local
  python -m harness.judge start   plans/judge_v1.yaml --live [--judges KEY ...]
  python -m harness.judge resume  BATCH_ID --live [--judges KEY ...] [--workers N]
  python -m harness.judge rerun   BATCH_ID --slots 3 7 --reason "..." --live [--workers N]
  python -m harness.judge status  BATCH_ID

Record layout (data_dir/judge/):
  judge/pairs/<plan_id>/pairs.json          pairs of blind IDs within version x prompt; written once
  judge/<batch_id>/batch.json, events.jsonl, calls.jsonl, requests/, raw/, text/   as for review and coding runs
A verdict is ok when the answer holds a JSON object whose 'winner' is A or B. Every answer is kept.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import json
import platform
import random
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

from . import HARNESS_VERSION
from .code import attempts, blinding_dir, load_review_texts, mark_interrupted
from .common import (REPO, git_state, key_fingerprints, load_api_keys, load_paths, load_template, load_yaml,
                     sha256_bytes, sha256_file, utc_now)
from .inputs import ManuscriptInput
from .judging import fill_user, make_pairs, read_verdict
from .plans import load_models
from .providers import ENDPOINTS, build_chat, build_openai
from .records import (append_jsonl, classify, estimate_cost, load_prices, read_jsonl, repo_relative, sdk_versions,
                      write_json_once, write_once)
from .review import ENV_NEEDED, check_env, require_live, snapshot_models

MAX_CONSECUTIVE_ERRORS = 3
BUILDERS = {"openai_api": build_openai, "fireworks_serverless": build_chat}


@dataclass(frozen=True)
class JudgeSlot:
    slot: int
    judge_key: str
    pair_id: str
    order: str              # "12": A = review_1, B = review_2; "21": the reverse

    def to_dict(self) -> dict:
        return asdict(self)


def run_id(batch_id: str, slot: int, attempt: int) -> str:
    return f"{batch_id}-s{slot:04d}-a{attempt}"


def load_plan(path: Path) -> dict:
    plan = load_yaml(path)
    for field in ("plan_id", "purpose", "blinding_plan", "review_purpose", "system_template", "user_template",
                  "judges", "seed"):
        if field not in plan:
            raise SystemExit(f"{path}: missing '{field}'")
    return plan


def pairs_file(paths, plan: dict) -> Path:
    return paths.data_dir / "judge" / "pairs" / plan["plan_id"] / "pairs.json"


def load_blinding_for(paths, plan: dict) -> tuple[dict, str]:
    f = blinding_dir(paths, plan["blinding_plan"]) / "blinding.json"
    return json.loads(f.read_text(encoding="utf-8")), sha256_file(f)


def load_pairs(paths, plan: dict) -> tuple[dict, str]:
    f = pairs_file(paths, plan)
    if not f.exists():
        raise SystemExit(f"{f} not found: run 'python -m harness.judge pair' first.")
    return json.loads(f.read_text(encoding="utf-8")), sha256_file(f)


class Prepared:
    def __init__(self, plan: dict, judges: dict, paths, blinding: dict, pairs: dict):
        self.plan, self.judges = plan, judges
        self.system = load_template("judge", plan["system_template"])
        self.user = load_template("judge", plan["user_template"])
        self.texts = load_review_texts(paths, blinding)
        self.shas = {r["blind_id"]: r["text_sha256"] for r in blinding["reviews"]}
        self.pairs = {p["pair_id"]: p for p in pairs["pairs"]}

    def sides(self, s: JudgeSlot) -> tuple[str, str]:
        p = self.pairs[s.pair_id]
        return (p["review_1"], p["review_2"]) if s.order == "12" else (p["review_2"], p["review_1"])

    def build(self, s: JudgeSlot):
        cfg = self.judges[s.judge_key]
        a, b = self.sides(s)
        user = fill_user(self.user.text, self.texts[a], self.texts[b])
        return BUILDERS[cfg["route"]](cfg, ManuscriptInput("judge", "text"), user, system=self.system.text)


def expand(plan: dict, judges: dict, pairs: dict) -> list[JudgeSlot]:
    slots, n = [], 0
    for j in plan["judges"]:
        if j not in judges:
            raise SystemExit(f"Unknown judge '{j}' (see config/models.yaml, judges)")
        jobs = [(p["pair_id"], o) for p in pairs["pairs"] for o in ("12", "21")]
        random.Random(f"{plan['seed']}:judge-order:{j}").shuffle(jobs)
        for pid, o in jobs:
            n += 1
            slots.append(JudgeSlot(n, j, pid, o))
    return slots


def batch_dir(paths, batch_id: str) -> Path:
    return paths.data_dir / "judge" / batch_id


def do_call(prep: Prepared, bdir: Path, batch: dict, s: JudgeSlot, attempt: int, git: dict, operator: str,
            parent: str | None = None, reason: str | None = None) -> dict:
    cfg = prep.judges[s.judge_key]
    rid = run_id(batch["batch_id"], s.slot, attempt)
    a, b = prep.sides(s)
    call = prep.build(s)
    req_sha = write_json_once(bdir / "requests" / f"{rid}.json", call.request)
    record = {
        "record_version": 1, "run_id": rid, "batch_id": batch["batch_id"], "slot": s.slot, "attempt": attempt,
        "parent_run_id": parent, "rerun_reason": reason, "purpose": batch["purpose"], "plan_id": batch["plan_id"],
        "operator": operator, "git_commit": git["commit"], "git_dirty": git["dirty"], "harness_version": HARNESS_VERSION,
        "judge_key": s.judge_key, "judge_label": cfg["label"], "provider": cfg["provider"], "route": cfg["route"],
        "model_requested": cfg["model_id"], "model_returned": None, "pair_id": s.pair_id, "order": s.order,
        "review_a": a, "review_b": b, "review_a_sha256": prep.shas[a], "review_b_sha256": prep.shas[b],
        "system_template": {"id": prep.system.template_id, "sha256": prep.system.sha256},
        "user_template": {"id": prep.user.template_id, "sha256": prep.user.sha256},
        "request_file": f"requests/{rid}.json", "request_sha256": req_sha, "settings": call.settings,
        "effort_reported": "unknown", "effort_default_documented": cfg.get("effort_default", "unknown"),
        "time_sent_utc": utc_now(),
    }
    empty = {"stop_reason": None, "usage": None, "cost_estimate": {"usd": "unknown"}, "text_file": None,
             "text_sha256": None, "text_chars": 0, "winner": None, "winner_blind_id": None, "rationale": None,
             "problems": None}
    t0 = time.monotonic()
    try:
        resp = call.send()
    except Exception as e:
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
    try:
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
    verdict, problems = read_verdict(text) if status == "ok" else (None, None)
    if status == "ok" and not (verdict and verdict["winner"]):
        status = "invalid_output"
    winner = verdict["winner"] if verdict else None
    record.update({
        "model_returned": result["model_returned"], "request_id": result["request_id"],
        "effort_reported": result["effort_reported"], "status": status, "stop_reason": result["stop_reason"],
        "usage": result["usage"], "usage_provider_fields": result.get("usage_provider_fields"),
        "settings_reported": result.get("settings_reported", "not reported by the provider"),
        "cost_estimate": estimate_cost(cfg["model_id"], result["usage"], batch["prices"]),
        "text_file": f"text/{rid}.md", "text_sha256": text_sha, "text_chars": len(text),
        "winner": winner, "winner_blind_id": {"A": a, "B": b}.get(winner),
        "rationale": verdict.get("rationale") if verdict else None, "problems": problems, "error": None,
    })
    append_jsonl(bdir / "calls.jsonl", record)
    return record


def run_queue(prep, bdir, batch, jobs, git, operator) -> list[dict]:
    out, errors = [], 0
    for i, (s, attempt, parent, reason) in enumerate(jobs):
        rec = do_call(prep, bdir, batch, s, attempt, git, operator, parent, reason)
        print(f"  {rec['run_id']}  {s.judge_key:20s} {s.pair_id} {s.order}  {rec['status']:14s} {rec['seconds']:>7.1f}s",
              flush=True)
        out.append(rec)
        errors = errors + 1 if rec["status"] == "error" else 0
        if errors >= MAX_CONSECUTIVE_ERRORS and i + 1 < len(jobs):
            left = [j[0].slot for j in jobs[i + 1:]]
            append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "queue stopped", "judge": s.judge_key,
                                                 "reason": f"{errors} errors in a row; last: {rec['error']['message'][:300]}",
                                                 "slots_not_attempted": left})
            print(f"  QUEUE STOPPED for {s.judge_key}; {len(left)} slots left for resume", flush=True)
            break
    return out


def run_jobs(prep, bdir, batch, jobs, git, operator, workers: int | None = None):
    w = workers or batch["workers_per_judge"]
    by_judge: dict[str, list] = {}
    for j in jobs:
        by_judge.setdefault(j[0].judge_key, []).append(j)
    queues = [q[i::w] for q in by_judge.values() for i in range(w) if q[i::w]]
    with cf.ThreadPoolExecutor(max_workers=max(1, len(queues))) as ex:
        for f in [ex.submit(run_queue, prep, bdir, batch, q, git, operator) for q in queues]:
            f.result()


# ---------------------------------------------------------------- commands

def cmd_pair(args):
    paths = load_paths()
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    out = pairs_file(paths, plan)
    if out.exists():
        raise SystemExit(f"{out} already exists; pairing is done once per plan.")
    blinding, b_sha = load_blinding_for(paths, plan)
    pairs = make_pairs(blinding["reviews"], plan["seed"], plan["review_purpose"])
    write_json_once(out, {"plan_id": plan["plan_id"], "plan_file": repo_relative(plan_path),
                          "plan_sha256": sha256_file(plan_path), "seed": plan["seed"], "created_utc": utc_now(),
                          "operator": paths.operator, "git": git_state(), "harness_version": HARNESS_VERSION,
                          "blinding_plan": plan["blinding_plan"], "blinding_sha256": b_sha, "n_pairs": len(pairs),
                          "pairs": pairs})
    cells = collections.Counter((p["version"], p["template_id"]) for p in pairs)
    print(f"{len(pairs)} pairs -> {out}; per version x prompt: {sorted(set(cells.values()))}")


def cmd_dry_run(args):
    paths = load_paths()
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    judges = load_models()["judges"]
    blinding, _ = load_blinding_for(paths, plan)
    pairs, p_sha = load_pairs(paths, plan)
    prep = Prepared(plan, judges, paths, blinding, pairs)
    slots = expand(plan, judges, pairs)
    labels = {r["blind_id"]: (r["review_run_id"], r["review_batch_id"]) for r in blinding["reviews"]}
    out = paths.dry_run_dir / f"{plan['plan_id']}-{utc_now().replace(':', '').replace('-', '')[:15]}Z"
    chars = collections.defaultdict(list)
    written = collections.Counter()
    for s in slots:
        call = prep.build(s)
        text = json.dumps(call.request, ensure_ascii=False)
        for bid in prep.sides(s):
            for label in (*labels[bid], bid, s.pair_id):
                if label in text:
                    raise SystemExit(f"Request for {s.pair_id} contains the label {label}")
        chars[s.judge_key].append(len(text))
        if written[s.judge_key] < 2:
            write_json_once(out / "requests" / f"{s.judge_key}__{s.pair_id}_{s.order}.json",
                            {"request": call.request, "settings": call.settings})
            written[s.judge_key] += 1
    write_json_once(out / "summary.json", {"plan_id": plan["plan_id"], "plan_sha256": sha256_file(plan_path),
                                           "pairs_sha256": p_sha, "slots": len(slots), "git": git_state(),
                                           "request_chars": {k: {"calls": len(v), "mean": round(sum(v) / len(v)),
                                                                 "max": max(v)} for k, v in chars.items()}})
    print(f"Dry run of {plan['plan_id']}: {len(slots)} slots built, no API called. Requests carry no ID or label.")
    for k, v in chars.items():
        print(f"  {k:20s} {len(v):4d} calls, request about {sum(v) // len(v) // 4:,} tokens on average (chars / 4)")
    print(f"First requests per judge and summary written to {out}")


def cmd_start(args):
    git = require_live(args)
    paths = load_paths()
    load_api_keys(paths.keys_file)
    plan_path = Path(args.plan).resolve()
    plan = load_plan(plan_path)
    judges = load_models()["judges"]
    blinding, b_sha = load_blinding_for(paths, plan)
    pairs, p_sha = load_pairs(paths, plan)
    prep = Prepared(plan, judges, paths, blinding, pairs)
    slots = expand(plan, judges, pairs)
    run_slots = [s for s in slots if not args.judges or s.judge_key in args.judges]
    used = {k: judges[k] for k in plan["judges"]}
    check_env({used[s.judge_key]["route"] for s in run_slots})
    batch_id = f"{plan['plan_id']}-{utc_now().replace(':', '').replace('-', '')[:15]}Z"
    bdir = batch_dir(paths, batch_id)
    batch = {
        "batch_id": batch_id, "plan_id": plan["plan_id"], "purpose": plan["purpose"],
        "plan_file": repo_relative(plan_path), "plan_sha256": sha256_file(plan_path), "created_utc": utc_now(),
        "operator": paths.operator, "git": git, "harness_version": HARNESS_VERSION, "sdk_versions": sdk_versions(),
        "python": platform.python_version(), "platform": platform.platform(),
        "system_template": {"id": prep.system.template_id, "file": prep.system.file, "sha256": prep.system.sha256},
        "user_template": {"id": prep.user.template_id, "file": prep.user.file, "sha256": prep.user.sha256},
        "source": plan.get("source"), "blinding": {"plan": plan["blinding_plan"], "sha256": b_sha},
        "pairs": {"file": f"pairs/{plan['plan_id']}/pairs.json", "sha256": p_sha, "seed": plan["seed"],
                  "n_pairs": len(pairs["pairs"])},
        "judges": used, "models_yaml_sha256": sha256_file(REPO / "config" / "models.yaml"),
        "model_metadata": snapshot_models({k: v for k, v in used.items() if not args.judges or k in args.judges}),
        "workers_per_judge": plan.get("workers_per_judge", 1), "prices": load_prices(),
        "slots": [s.to_dict() for s in slots],
        "endpoints": {r: ENDPOINTS[r] for r in sorted({c["route"] for c in used.values()})},
        "api_key_fingerprints": key_fingerprints([v for k, c in used.items() if not args.judges or k in args.judges
                                                  for v in ENV_NEEDED[c["route"]]]),
    }
    write_json_once(bdir / "batch.json", batch)
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "start", "judges": args.judges or "all",
                                         "git": git, "operator": paths.operator})
    print(f"Batch {batch_id}: {len(run_slots)} of {len(slots)} slots now -> {bdir}")
    run_jobs(prep, bdir, batch, [(s, 1, None, None) for s in run_slots], git, paths.operator)


def load_batch(paths, batch_id: str):
    bdir = batch_dir(paths, batch_id)
    return bdir, json.loads((bdir / "batch.json").read_text(encoding="utf-8"))


def prepare_existing(batch: dict, paths, judges_now: list[str]) -> Prepared:
    judges = load_models()["judges"]
    for k, cfg in batch["judges"].items():
        if judges.get(k) != cfg:
            raise SystemExit(f"config/models.yaml judge '{k}' differs from the one batch {batch['batch_id']} started with.")
    plan = load_plan(REPO / batch["plan_file"])
    if sha256_file(REPO / batch["plan_file"]) != batch["plan_sha256"]:
        raise SystemExit("The plan file changed after the batch started.")
    blinding, b_sha = load_blinding_for(paths, plan)
    pairs, p_sha = load_pairs(paths, plan)
    if b_sha != batch["blinding"]["sha256"] or p_sha != batch["pairs"]["sha256"]:
        raise SystemExit("blinding.json or pairs.json differs from the one the batch started with.")
    check_env({batch["judges"][k]["route"] for k in judges_now})
    prep = Prepared(plan, batch["judges"], paths, blinding, pairs)
    if prep.system.sha256 != batch["system_template"]["sha256"] or prep.user.sha256 != batch["user_template"]["sha256"]:
        raise SystemExit("A judge template differs from the one the batch started with.")
    return prep


def cmd_resume(args):
    git = require_live(args)
    paths = load_paths()
    load_api_keys(paths.keys_file)
    bdir, batch = load_batch(paths, args.batch_id)
    mark_interrupted(bdir, batch, git, paths.operator)
    done = attempts(bdir)
    todo = [JudgeSlot(**d) for d in batch["slots"]
            if d["slot"] not in done and (not args.judges or d["judge_key"] in args.judges)]
    keys = sorted({s.judge_key for s in todo})
    prep = prepare_existing(batch, paths, keys)
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "resume", "judges": args.judges or "all",
                                         "workers_per_judge": args.workers or batch["workers_per_judge"],
                                         "slots": [s.slot for s in todo], "git": git, "operator": paths.operator,
                                         "model_metadata": snapshot_models({k: batch["judges"][k] for k in keys}),
                                         "api_key_fingerprints": key_fingerprints(
                                             [v for k in keys for v in ENV_NEEDED[batch["judges"][k]["route"]]])})
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
    by_slot = {d["slot"]: JudgeSlot(**d) for d in batch["slots"]}
    jobs = []
    for n in args.slots:
        if n not in done:
            raise SystemExit(f"Slot {n} has no attempt yet; use resume.")
        if any(r["status"] == "ok" for r in done[n]):
            raise SystemExit(f"Slot {n} already has a verdict; it is not rerun.")
        last = max(done[n], key=lambda r: r["attempt"])
        jobs.append((by_slot[n], last["attempt"] + 1, last["run_id"], args.reason.strip()))
    prep = prepare_existing(batch, paths, sorted({j[0].judge_key for j in jobs}))
    append_jsonl(bdir / "events.jsonl", {"time_utc": utc_now(), "command": "rerun", "slots": args.slots,
                                         "reason": args.reason.strip(),
                                         "workers_per_judge": args.workers or batch["workers_per_judge"],
                                         "git": git, "operator": paths.operator})
    run_jobs(prep, bdir, batch, jobs, git, paths.operator, args.workers)


def cmd_status(args):
    paths = load_paths()
    bdir, batch = load_batch(paths, args.batch_id)
    done = attempts(bdir)
    counts: dict[str, collections.Counter] = {}
    cost = collections.Counter()
    for d in batch["slots"]:
        recs = done.get(d["slot"])
        st = max(recs, key=lambda r: r["attempt"])["status"] if recs else "not attempted"
        counts.setdefault(d["judge_key"], collections.Counter())[st] += 1
        for r in recs or []:
            usd = (r.get("cost_estimate") or {}).get("usd")
            if isinstance(usd, float):
                cost[d["judge_key"]] += usd
    print(f"Batch {batch['batch_id']} ({len(batch['slots'])} slots)")
    for k, n in counts.items():
        print(f"  {k:20s} " + "  ".join(f"{s}: {v}" for s, v in sorted(n.items())) + f"   ${cost[k]:.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m harness.judge", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair"); p.add_argument("plan"); p.set_defaults(fn=cmd_pair)
    p = sub.add_parser("dry-run"); p.add_argument("plan"); p.set_defaults(fn=cmd_dry_run)
    p = sub.add_parser("start"); p.add_argument("plan"); p.add_argument("--live", action="store_true")
    p.add_argument("--judges", nargs="*"); p.set_defaults(fn=cmd_start)
    p = sub.add_parser("resume"); p.add_argument("batch_id"); p.add_argument("--live", action="store_true")
    p.add_argument("--judges", nargs="*"); p.add_argument("--workers", type=int); p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("rerun"); p.add_argument("batch_id"); p.add_argument("--slots", nargs="+", type=int, required=True)
    p.add_argument("--reason", required=True); p.add_argument("--live", action="store_true")
    p.add_argument("--workers", type=int); p.set_defaults(fn=cmd_rerun)
    p = sub.add_parser("status"); p.add_argument("batch_id"); p.set_defaults(fn=cmd_status)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

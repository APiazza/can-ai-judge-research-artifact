"""Token, time and cost summary of a review batch, and its batch record.

  python -m harness.report <batch_id>

Prints one line per call and totals by provider account, writes usage_summary_<time>.csv into the batch
folder, and writes the batch record README.md in the corpus/prompt_history format (an addendum
README_<time>.md if a README already exists). Reads only the batch and call records; never the review texts.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from collections import Counter

from .common import load_paths, utc_now
from .records import read_jsonl, write_once

COLUMNS = ["run_id", "model_key", "provider", "model_returned", "template_id", "manuscript", "status", "stop_reason",
           "effort_reported", "input_total", "cached_input", "cache_write", "output_billed", "reasoning",
           "cost_usd", "seconds", "text_chars"]


def rows(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        if r.get("status") == "interrupted":
            continue
        u = r.get("usage") or {}
        out.append({
            "run_id": r["run_id"], "model_key": r.get("model_key"), "provider": r.get("provider"),
            "model_returned": r.get("model_returned"), "template_id": r.get("template_id"),
            "manuscript": r.get("manuscript"), "status": r.get("status"), "stop_reason": r.get("stop_reason"),
            "effort_reported": r.get("effort_reported"),
            **{k: u.get(k) for k in ("input_total", "cached_input", "cache_write", "output_billed", "reasoning")},
            "cost_usd": (r.get("cost_estimate") or {}).get("usd"), "seconds": r.get("seconds"),
            "text_chars": r.get("text_chars")})
    return out


def totals(table: list[dict]) -> dict[str, dict]:
    tot: dict[str, dict] = {}
    for row in table:
        t = tot.setdefault(row["provider"], {"calls": 0, "input_total": 0, "output_billed": 0, "cost_usd": 0.0,
                                             "cost_unknown_calls": 0})
        t["calls"] += 1
        for k in ("input_total", "output_billed"):
            t[k] += row[k] if isinstance(row[k], int) else 0
        if isinstance(row["cost_usd"], (int, float)):
            t["cost_usd"] += row["cost_usd"]
        else:
            t["cost_unknown_calls"] += 1
    return tot


def readme(batch: dict, records: list[dict], events: list[dict], usage_file: str) -> str:
    """Batch record in the corpus/prompt_history format: who and when, tools, request, inputs, models, method,
    checks, judgment calls, outputs."""
    git = batch["git"]
    sdks = ", ".join(f"{k} {v}" for k, v in batch["sdk_versions"].items())
    lines = [f"# Review batch {batch['batch_id']}", "",
             f"{batch['created_utc'][:10]} · {batch['operator']}", "",
             f"**Tools.** The ai-reviewer-audit harness (Python), commit `{git['commit']}`, harness "
             f"{batch['harness_version']}, Python {batch['python']}, SDKs {sdks}. The harness was written with "
             f"Claude Code (Anthropic, Claude Opus 5.5) and run by {batch['operator']}.", "",
             f"**Request.** {batch['purpose'].capitalize()} runs: {len(batch['slots'])} slots from "
             f"`{batch['plan_file']}` (SHA-256 `{batch['plan_sha256']}`).", "",
             "**Inputs (read only, unchanged)**"]
    files = {f["path"]: f["sha256"] for fl in batch["inputs"].values() for f in fl}
    lines += [f"- `{path}` · `{sha}`" for path, sha in sorted(files.items())]
    lines += [f"- prompt `{v['file']}` · `{v['sha256']}`" for v in batch["templates"].values()]
    lines += ["", "**Models**"]
    for k, cfg in batch["models"].items():
        meta = batch.get("model_metadata", {}).get(k, {})
        version = meta.get("version") or meta.get("created_at") or meta.get("created") or meta.get("updateTime")
        lines.append(f"- {cfg['label']}: `{cfg['model_id']}` via {cfg['route']}, input {cfg['input_format']}, "
                     f"{cfg['construction']}" + (f"; provider metadata: {version}" if version else ""))
    iso = batch["isolation"]
    lines += ["", "**Method.** One API call per slot. No system message, tools or web access. Temperature, seed, "
              "effort and thinking are not sent (provider defaults), except effort in the effort-comparison "
              "configurations. SDK retries are off. One queue per underlying model; different models run in "
              "parallel. Every request, raw response and review text is written once and never overwritten "
              "(see docs/run_record.md).", "",
              f"**Checks.** Key isolation passed before the batch: {iso['inputs_folder_files_scanned']} files in the "
              f"inputs folder scanned and {iso['files_sent']} files sent, none matching a key hash, named like a "
              f"key or carrying a version label. Working tree clean at commit `{git['commit'][:7]}`."]
    by_model: dict[str, Counter] = {}
    for r in records:
        by_model.setdefault(r.get("model_key", "?"), Counter())[r["status"]] += 1
    lines += [f"- {k}: " + ", ".join(f"{n} {s}" for s, n in sorted(c.items())) for k, c in by_model.items()]
    effort = sorted({(r["model_key"], str(r.get("effort_reported"))) for r in records
                     if r.get("effort_reported") not in (None, "unknown")})
    if effort:
        lines.append("- Effort reported by the provider: " + "; ".join(f"{k} {e}" for k, e in effort) + ".")
    reruns = [r for r in records if r.get("parent_run_id")]
    later = [e for e in events if e["command"] in ("resume", "rerun")]
    judgment = ("; ".join(f"{r['run_id']} reran {r['parent_run_id']}: {r['rerun_reason']}" for r in reruns)
                if reruns else "No reruns.")
    if later:
        judgment += " Commands after the start: " + "; ".join(f"{e['time_utc']} {e['command']}" for e in later) + "."
    lines += ["", f"**Judgment calls.** {judgment} Human decisions about these runs are recorded in worklog.md.", "",
              "**Outputs**",
              f"- `calls.jsonl`: {len(records)} call records; `requests/`, `raw/`, `text/`: one file per call",
              "- `batch.json`: batch record; `events.jsonl`: commands run",
              f"- `{usage_file}`: tokens, time and list-price cost per call", ""]
    return "\n".join(lines)


def main(argv=None):
    batch_id = (argv or sys.argv[1:])[0]
    paths = load_paths()
    bdir = paths.data_dir / "review" / batch_id
    records = read_jsonl(bdir / "calls.jsonl")
    table = rows(records)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    w.writerows(table)
    stamp = utc_now().replace(':', '').replace('-', '')[:15] + "Z"
    out = bdir / f"usage_summary_{stamp}.csv"
    write_once(out, buf.getvalue().encode("utf-8"))
    for row in table:
        print(f"{row['run_id'][-9:]}  {row['model_key']:24s} {row['manuscript']:17s} {row['status']:11s} "
              f"in {row['input_total']!s:>8}  out {row['output_billed']!s:>7}  ${row['cost_usd']!s:>9}  {row['seconds']!s:>7}s")
    print("\nBy provider account (list-price estimate):")
    for prov, t in totals(table).items():
        print(f"  {prov:10s} {t['calls']:3d} calls  in {t['input_total']:>9}  out {t['output_billed']:>8}  "
              f"${t['cost_usd']:.2f}" + (f"  ({t['cost_unknown_calls']} calls without a price)" if t["cost_unknown_calls"] else ""))
    batch = json.loads((bdir / "batch.json").read_text(encoding="utf-8"))
    text = readme(batch, records, read_jsonl(bdir / "events.jsonl"), out.name)
    rd = bdir / "README.md"
    if rd.exists():
        rd = bdir / f"README_{stamp}.md"
    write_once(rd, text.encode("utf-8"))
    print(f"\nWritten to {out}\nBatch record: {rd}")


if __name__ == "__main__":
    main()

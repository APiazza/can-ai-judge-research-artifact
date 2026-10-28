"""Write-once run records, status labels and cost estimates."""
from __future__ import annotations

import json
import threading
from importlib import metadata
from pathlib import Path

from .common import REPO, load_yaml, sha256_bytes

_lock = threading.Lock()


def write_once(path: Path, data: bytes) -> str:
    """Create a file that must not exist yet. Returns its SHA-256. Never overwrites."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as f:
        f.write(data)
    return sha256_bytes(data)


def write_json_once(path: Path, obj) -> str:
    return write_once(path, (json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))


def append_jsonl(path: Path, obj) -> None:
    """Append one record. Lines are never edited or removed."""
    line = json.dumps(obj, ensure_ascii=False, default=str) + "\n"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sdk_versions() -> dict:
    out = {}
    for pkg in ("anthropic", "openai", "google-genai", "pyyaml"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "not installed"
    return out


# ---------------------------------------------------------------- status

STOP_OK = {"end_turn", "stop", "completed", "FinishReason.STOP", "STOP", "stop_sequence"}
STOP_TRUNCATED = {"max_tokens", "length", "FinishReason.MAX_TOKENS", "MAX_TOKENS", "model_context_window_exceeded"}
STOP_REFUSED = {"refusal", "content_filter", "FinishReason.SAFETY", "SAFETY", "FinishReason.PROHIBITED_CONTENT"}


def classify(result: dict) -> str:
    """ok | truncated | refused | empty | other. Only 'ok' runs enter the analysis; every run is kept."""
    stop = str(result.get("stop_reason"))
    if stop in STOP_TRUNCATED or stop.startswith("incomplete: max_output_tokens"):
        return "truncated"
    if stop in STOP_REFUSED or stop.startswith("incomplete: content_filter"):
        return "refused"
    if not (result.get("text") or "").strip():
        return "empty"
    if stop in STOP_OK:
        return "ok"
    return "other"


# ---------------------------------------------------------------- cost

def load_prices() -> dict:
    return load_yaml(REPO / "config" / "prices.yaml")


def estimate_cost(model_id: str, usage: dict, prices: dict) -> dict:
    """List-price estimate in USD. The billed amount is on each provider's console."""
    p = prices["models"].get(model_id)
    if p is None or not isinstance(usage.get("input_total"), int):
        return {"usd": "unknown", "prices_as_of": str(prices["as_of"])}
    long_prompt = usage["input_total"] > 100_000 and "input_over_100k" in p
    rate_in = p["input_over_100k"] if long_prompt else p["input"]
    rate_out = p.get("output_over_100k", p["output"]) if long_prompt else p["output"]
    scale = rate_in / p["input"]                 # long-prompt rates scale cache prices in proportion
    cached = usage.get("cached_input") or 0
    written = usage.get("cache_write") or 0
    uncached = usage["input_total"] - cached - written
    usd = (uncached * rate_in + cached * p.get("cached_input", p["input"]) * scale
           + written * p.get("cache_write", p["input"]) * scale + (usage["output_billed"] or 0) * rate_out) / 1e6
    return {"usd": round(usd, 6), "prices_as_of": str(prices["as_of"])}


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)

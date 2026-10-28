"""Paths, hashing, git state, prompt templates and API keys."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------- local paths (never committed)

@dataclass(frozen=True)
class Paths:
    inputs_dir: Path        # ai-run-inputs/ : pilot-v6/ and clean-matched-v6/
    data_dir: Path          # where run records and raw outputs are written (outside the repo, synced to Dropbox)
    keys_file: Path | None  # local file with API keys (outside the repo)
    key_sha256: list[str]   # SHA-256 of each answer-key file; used only to prove no review input is the key
    operator: str           # initials written into every record
    dry_run_dir: Path       # dry-run requests: local only, kept apart from run records


def load_paths(path: Path | None = None) -> Paths:
    path = path or REPO / "config" / "paths.local.yaml"
    if not path.exists():
        raise SystemExit(f"{path} not found: copy config/paths.example.yaml to config/paths.local.yaml and fill it in.")
    cfg = load_yaml(path)
    hashes = cfg["key_sha256"]
    data_dir = Path(cfg["data_dir"]).resolve()
    paths = Paths(
        inputs_dir=Path(cfg["inputs_dir"]).resolve(),
        data_dir=data_dir,
        keys_file=Path(cfg["keys_file"]).resolve() if cfg.get("keys_file") else None,
        key_sha256=[hashes] if isinstance(hashes, str) else list(hashes),
        operator=cfg.get("operator", "unknown"),
        dry_run_dir=Path(cfg.get("dry_run_dir") or data_dir.parent / "dry_runs").resolve(),
    )
    for p in (paths.inputs_dir, paths.data_dir, paths.dry_run_dir):
        if REPO in p.parents or p == REPO:
            raise SystemExit(f"{p} is inside the repository; inputs and run data must live outside it.")
    if paths.data_dir == paths.inputs_dir or paths.inputs_dir in paths.data_dir.parents:
        raise SystemExit("data_dir must not be inside inputs_dir.")
    if paths.dry_run_dir == paths.data_dir or paths.data_dir in paths.dry_run_dir.parents:
        raise SystemExit("dry_run_dir must not be inside data_dir: dry runs are not run records.")
    return paths


# ---------------------------------------------------------------- git state

def git_state() -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    try:
        commit = git("rev-parse", "HEAD")
        dirty = bool(git("status", "--porcelain"))
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"commit": "unknown", "dirty": "unknown"}
    return {"commit": commit, "dirty": dirty}


# ---------------------------------------------------------------- prompt templates

@dataclass(frozen=True)
class Template:
    template_id: str
    file: str
    sha256: str
    text: str            # exactly what is sent: file content with trailing newlines removed


def load_template(kind: str, template_id: str) -> Template:
    manifest = load_yaml(REPO / "prompts" / "manifest.yaml")
    entry = manifest[kind][template_id]
    path = REPO / "prompts" / entry["file"]
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        raise SystemExit(
            f"Template {template_id} ({entry['file']}) has changed since it was recorded "
            f"(manifest {entry['sha256'][:12]}…, file {actual[:12]}…). Never edit a template in place: "
            f"add a new version file and a new manifest entry.")
    text = path.read_text(encoding="utf-8").rstrip("\n")
    return Template(template_id, entry["file"], actual, text)


# ---------------------------------------------------------------- API keys

KEY_NAMES = {  # label in the local keys file -> environment variable read by the SDKs
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "fireworks ai": "FIREWORKS_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def load_api_keys(keys_file: Path | None) -> list[str]:
    """Put keys from the local file into the environment, replacing any value already set there, so every run
    bills the project accounts. Returns the variable names set, never the values."""
    if keys_file is None or not keys_file.exists():
        return []
    loaded = []
    for line in keys_file.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        var = KEY_NAMES.get(label.strip().lower())
        if var and value.strip():
            os.environ[var] = value.strip()
            loaded.append(var)
    return loaded


def key_fingerprints(names: list[str]) -> dict:
    """First 12 hex digits of each key's SHA-256: identifies which account was used without revealing the key."""
    return {n: sha256_bytes(os.environ[n].encode())[:12] for n in sorted(set(names)) if os.environ.get(n)}

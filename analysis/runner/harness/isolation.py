"""Checks, run before every review batch, that no model under review can receive the answer key.

1. The review runner reads files only inside the inputs folder (enforced in inputs.load_manuscript).
2. No file anywhere in the inputs folder has the same SHA-256 as a key file.
3. No file in the inputs folder is named like a key.
4. No manuscript file sent to a model contains a version, folder or key label.
The review runner is never given the key's location: paths.local.yaml holds only the key's hash.
"""
from __future__ import annotations

import re
from pathlib import Path

from .common import sha256_file

LABELS = re.compile(rb"(?i)\b(planted|answer[ _-]key|status-p01|pilot-v6|clean-matched|flawed version)\b")
KEY_NAME = re.compile(r"(?i)(^|[_\-. ])key([_\-. ]|$)")


def check(inputs_dir: Path, key_sha256: list[str], files_sent: list[dict]) -> dict:
    """files_sent: the {role, path, sha256} entries of every file the batch will send. Raises on failure."""
    key_hashes = {h.lower() for h in key_sha256}
    problems = []

    scanned = 0
    for p in sorted(inputs_dir.rglob("*")):
        if not p.is_file():
            continue
        scanned += 1
        if sha256_file(p) in key_hashes:
            problems.append(f"{p.relative_to(inputs_dir)} is identical to the answer key")
        if KEY_NAME.search(p.stem):
            problems.append(f"{p.relative_to(inputs_dir)} is named like a key file")

    label_hits = {}
    for f in {f["path"]: f for f in files_sent}.values():
        p = inputs_dir / f["path"]
        if not p.resolve().is_relative_to(inputs_dir):
            problems.append(f"{f['path']} is outside the inputs folder")
            continue
        if sha256_file(p) != f["sha256"]:
            problems.append(f"{f['path']} changed after it was hashed")
        if p.suffix in (".md", ".pdf", ".txt"):
            hits = sorted({m.group(0).decode("latin-1").lower() for m in LABELS.finditer(p.read_bytes())})
            if hits:
                label_hits[f["path"]] = hits
    for path, hits in label_hits.items():
        problems.append(f"{path} contains label text: {', '.join(hits)}")

    if problems:
        raise SystemExit("Key isolation check failed:\n  " + "\n  ".join(problems))
    return {
        "passed": True,
        "inputs_folder_files_scanned": scanned,
        "key_sha256_checked": sorted(key_hashes),
        "files_sent": len({f["path"] for f in files_sent}),
        "label_patterns_checked": LABELS.pattern.decode(),
        "key_path_available_to_review_runner": False,
    }

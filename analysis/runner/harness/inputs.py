"""Manuscript inputs for review runs.

pdf         the PDF, attached before the prompt
md_figures  manuscript.md split at each image link, with the figure image placed where the link was
md_text     manuscript.md as text only
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .common import sha256_file

MANUSCRIPTS = {"pilot-v6": "pilot-v6", "clean-matched-v6": "clean-matched-v6"}
IMAGE_LINK = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


@dataclass
class Segment:
    kind: str                 # "text" | "image" | "pdf"
    text: str | None = None
    path: Path | None = None
    sha256: str | None = None
    media_type: str | None = None


@dataclass
class ManuscriptInput:
    manuscript: str           # pilot-v6 | clean-matched-v6
    input_format: str         # pdf | md_figures | md_text
    segments: list[Segment] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)   # every file read, with SHA-256


def _inside(child: Path, parent: Path) -> bool:
    return parent == child or parent in child.parents


def load_manuscript(inputs_dir: Path, manuscript: str, input_format: str) -> ManuscriptInput:
    folder = (inputs_dir / MANUSCRIPTS[manuscript]).resolve()
    if not _inside(folder, inputs_dir):
        raise SystemExit(f"{folder} is outside the inputs folder")
    mi = ManuscriptInput(manuscript, input_format)

    def add_file(path: Path, role: str) -> str:
        path = path.resolve()
        if not _inside(path, inputs_dir):
            raise SystemExit(f"Refusing to read {path}: outside the inputs folder")
        digest = sha256_file(path)
        mi.files.append({"role": role, "path": str(path.relative_to(inputs_dir)).replace("\\", "/"), "sha256": digest})
        return digest

    if input_format == "pdf":
        pdf = folder / "manuscript.pdf"
        mi.segments.append(Segment("pdf", path=pdf, sha256=add_file(pdf, "manuscript"), media_type="application/pdf"))
        return mi

    md_path = folder / "manuscript.md"
    add_file(md_path, "manuscript")
    md = md_path.read_text(encoding="utf-8")
    if input_format == "md_text":
        mi.segments.append(Segment("text", text=md))
        return mi
    if input_format != "md_figures":
        raise SystemExit(f"Unknown input format {input_format}")

    pos = 0
    for m in IMAGE_LINK.finditer(md):
        end = m.end()
        mi.segments.append(Segment("text", text=md[pos:end]))      # text up to and including the image link
        img = (folder / m.group(1)).resolve()
        mi.segments.append(Segment("image", path=img, sha256=add_file(img, "figure"), media_type="image/png"))
        pos = end
    mi.segments.append(Segment("text", text=md[pos:]))
    return mi

"""Run plans: a YAML file of cells, expanded into numbered slots.

Each slot is one review to be produced: model configuration x prompt x manuscript x replicate.
Within a model, slots run in the order replicate -> manuscript -> prompt, so both versions and all
prompts are spread evenly over the run time. Models run in parallel, one call at a time each.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .common import REPO, load_yaml
from .inputs import MANUSCRIPTS


@dataclass(frozen=True)
class Slot:
    slot: int
    model_key: str
    template_id: str
    manuscript: str
    rep: int

    def to_dict(self) -> dict:
        return asdict(self)


def load_models() -> dict:
    return load_yaml(REPO / "config" / "models.yaml")


def load_plan(path: Path) -> dict:
    plan = load_yaml(path)
    for field in ("plan_id", "purpose", "cells"):
        if field not in plan:
            raise SystemExit(f"{path}: missing '{field}'")
    return plan


def expand(plan: dict, reviewers: dict, manifest_review: dict) -> list[Slot]:
    per_model: dict[str, list[tuple]] = {}
    for cell in plan["cells"]:
        for m in cell["models"]:
            if m not in reviewers:
                raise SystemExit(f"Unknown model configuration '{m}' (see config/models.yaml)")
            for t in cell["prompts"]:
                if t not in manifest_review:
                    raise SystemExit(f"Unknown prompt template '{t}' (see prompts/manifest.yaml)")
            for ms in cell["manuscripts"]:
                if ms not in MANUSCRIPTS:
                    raise SystemExit(f"Unknown manuscript '{ms}'")
            for rep in range(1, cell.get("reps", 1) + 1):
                for ms in cell["manuscripts"]:
                    for t in cell["prompts"]:
                        per_model.setdefault(m, []).append((rep, ms, t))
    slots, n = [], 0
    for m, rows in per_model.items():
        rows.sort(key=lambda r: (r[0], list(MANUSCRIPTS).index(r[1]), r[2]))
        for rep, ms, t in rows:
            n += 1
            slots.append(Slot(n, m, t, ms, rep))
    keys = [(s.model_key, s.template_id, s.manuscript, s.rep) for s in slots]
    if len(keys) != len(set(keys)):
        raise SystemExit("The plan lists the same model, prompt, manuscript and replicate twice")
    return slots

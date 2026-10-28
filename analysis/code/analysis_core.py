"""Offline calculations from the retained, anonymous pilot data. Python 3.10+."""

from collections import Counter, defaultdict
from copy import deepcopy
import csv
import hashlib
import json
import math
from pathlib import Path


CODERS = ("sonnet", "qwen")
METRICS = ("F", "FP")
VERSIONS = ("planted", "baseline")
RANK = {"–": 0, "P": 1, "F": 2}
CODER_FIELDS = {
    "claude-sonnet-5-5": "code_sonnet", "sonnet": "code_sonnet",
    "qwen3p8-2p4t-a95b": "code_qwen", "qwen": "code_qwen",
    "code_sonnet": "code_sonnet", "code_qwen": "code_qwen",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def version(value):
    aliases = {"clean": "baseline", "baseline": "baseline", "planted": "planted",
               "flawed": "planted"}
    require(value in aliases, f"Unknown manuscript-version label: {value!r}")
    return aliases[value]


def canonical_code(value):
    value = value.strip()
    return "–" if value in ("-", "–") else value


def load_inputs(data_dir):
    """Read only the named files inside this package's analysis/data folder."""
    names = ("llm_codes_by_review_and_concern.csv", "judge_verdicts_by_pair.csv",
             "recommendations_by_review.csv", "corrections.json",
             "human_validation_aggregate.csv", "study_register.json")
    for name in names:
        require((data_dir / name).is_file(), f"Missing package input: {name}")
    register = json.loads((data_dir / "study_register.json").read_text(encoding="utf-8"))
    rows = read_csv(data_dir / names[0])
    require(bool(rows), "The scoring CSV is empty")
    needed = {"blind_id", "purpose", "model", "provider", "version", "prompt", "run",
              "concern", "code_sonnet", "code_qwen", "code_lower", "code_higher",
              "criticisms_sonnet", "criticisms_qwen", "human_coder_1",
              "human_coder_2", "human_agreed"}
    require(needed <= set(rows[0]), f"Scoring CSV is missing columns: {sorted(needed-set(rows[0]))}")
    identities = set()
    review_metadata = {}
    for row in rows:
        identity = row["blind_id"], row["concern"]
        require(identity not in identities, f"Duplicate review–concern row: {identity}")
        identities.add(identity)
        row["version"] = version(row["version"])
        for field in ("code_sonnet", "code_qwen", "code_lower", "code_higher",
                      "human_coder_1", "human_coder_2", "human_agreed"):
            row[field] = canonical_code(row[field])
            require(row[field] in RANK or (field.startswith("human_") and not row[field]),
                    f"Invalid category in {field}, review {row['blind_id']}")
        pair = row["code_sonnet"], row["code_qwen"]
        require(row["code_lower"] == min(pair, key=RANK.get)
                and row["code_higher"] == max(pair, key=RANK.get),
                f"Original both/either categories disagree with scorer codes: {identity}")
        for field in ("criticisms_sonnet", "criticisms_qwen"):
            require(float(row[field]) >= 0, "Criticism counts must be nonnegative")
        metadata = tuple(row[k] for k in ("purpose", "model", "provider", "version",
                                         "prompt", "run", "criticisms_sonnet", "criticisms_qwen"))
        require(row["blind_id"] not in review_metadata
                or review_metadata[row["blind_id"]] == metadata,
                f"Inconsistent metadata across concerns for {row['blind_id']}")
        review_metadata[row["blind_id"]] = metadata
    concerns = sorted({row["concern"] for row in rows}, key=lambda c: int(c[1:]))
    coverage = defaultdict(set)
    for row in rows:
        coverage[row["blind_id"]].add(row["concern"])
    require(all(value == set(concerns) for value in coverage.values()),
            "Every review must have the same concern coverage")
    pairs = read_csv(data_dir / names[1])
    recommendations = read_csv(data_dir / names[2])
    pair_fields = {"pair_id", "version", "prompt", "review_1", "model_1", "review_2",
                   "model_2", "judge", "winner_review_1_shown_first",
                   "winner_review_2_shown_first", "decided_winner"}
    rec_fields = {"blind_id", "model", "version", "prompt", "recommendation", "how_read"}
    require(bool(pairs) and pair_fields <= set(pairs[0]), "Judge CSV is empty or missing required columns")
    require(bool(recommendations) and rec_fields <= set(recommendations[0]),
            "Recommendation CSV is empty or missing required columns")
    for row in pairs + recommendations:
        row["version"] = version(row["version"])
    for row in recommendations:
        if row["recommendation"] in ("", "none stated", "None"):
            row["recommendation"] = "None"
        if row["how_read"].startswith("rule for mixed statements"):
            row["how_read"] = "mixed statements, investigator checked"
    main_ids = {r['blind_id'] for r in rows if r['purpose'] == 'main'}
    require(len(recommendations) == len({r['blind_id'] for r in recommendations}),
            "Duplicate recommendation review ID")
    require({r['blind_id'] for r in recommendations} == main_ids,
            "Recommendation records do not cover exactly the main reviews")
    review_lookup = {r['blind_id']: r for r in rows}
    for row in recommendations:
        require(all(row[k] == review_lookup[row['blind_id']][k]
                    for k in ('model', 'version', 'prompt')),
                f"Recommendation metadata disagree with scoring data: {row['blind_id']}")
    for row in rows:
        human_fields = [bool(row[k]) for k in ('human_coder_1', 'human_coder_2', 'human_agreed')]
        require(all(human_fields) or not any(human_fields),
                "Incomplete investigator reference fields")
        require(not any(human_fields) or row['purpose'] == 'main',
                "Investigator check includes a non-main review")
    reference_coverage = defaultdict(set)
    for row in rows:
        if row['human_agreed']:
            reference_coverage[row['blind_id']].add(row['concern'])
    require(all(cs == set(concerns) for cs in reference_coverage.values()),
            "Investigator reference lacks a concern within a selected review")
    changes = json.loads((data_dir / "corrections.json").read_text(encoding="utf-8"))
    if isinstance(changes, dict):
        changes = changes.get("changes", changes.get("corrections", changes.get("records")))
    require(isinstance(changes, list), "corrections.json must contain a correction list")
    human = read_csv(data_dir / names[4])
    require({r["concern"] for r in human} == set(concerns),
            "Human aggregate must contain one row for every concern")
    require(len(human) == len(concerns), "Duplicate human aggregate concern")
    for row in human:
        for field in ("yes", "qualified", "no", "cannot_judge", "n"):
            row[field] = int(row[field])
            require(row[field] >= 0, "Human aggregate counts cannot be negative")
        require(row["yes"] + row["qualified"] + row["no"] + row["cannot_judge"] == row["n"],
                f"Human aggregate does not sum to n for {row['concern']}")
    require(len({r['n'] for r in human}) == 1, "Human aggregate denominators differ")
    hashes = {name: hashlib.sha256((data_dir / name).read_bytes()).hexdigest() for name in names}
    return rows, pairs, recommendations, changes, human, register, concerns, hashes


def apply_corrections(original, changes):
    corrected = deepcopy(original)
    index = {(r["blind_id"], r["concern"]): r for r in corrected}
    seen = set()
    applied = []
    for change in changes:
        key = change["blind_id"], change["concern"]
        field = CODER_FIELDS.get(change["coder"])
        require(field is not None, "Unknown scorer in correction")
        require((key, field) not in seen, f"Duplicate correction: {key}, {field}")
        seen.add((key, field))
        require(key in index, f"Correction refers to an absent observation: {key}")
        row = index[key]
        old = canonical_code(change["old_code"])
        new = canonical_code(change["recommended_code"])
        require(old in RANK and new in RANK and old != new, "Correction must change a valid code")
        require(row[field] == old, f"Correction old_code does not match input: {key}, {field}")
        row[field] = new
        row["code_lower"] = min((row["code_sonnet"], row["code_qwen"]), key=RANK.get)
        row["code_higher"] = max((row["code_sonnet"], row["code_qwen"]), key=RANK.get)
        applied.append({"blind_id": key[0], "concern": key[1], "coder": field[5:],
                        "old_code": old, "recommended_code": new,
                        "purpose": row["purpose"], "model": row["model"],
                        "version": row["version"], "prompt": row["prompt"]})
    return corrected, applied


def matches(row, metric, scorer="lower"):
    accepted = {"F"} if metric == "F" else {"F", "P"}
    a, b = row["code_sonnet"] in accepted, row["code_qwen"] in accepted
    return {"sonnet": a, "qwen": b, "lower": a and b, "higher": a or b}[scorer]


def counts(rows, metric, single_scorers=None):
    single_scorers = single_scorers or {}
    return {"n": len(rows), **{
        bound: sum(matches(r, metric, single_scorers.get(r["concern"], bound)) for r in rows)
        for bound in ("lower", "higher")}}


def primary(rows, concerns):
    return {metric: {concern: {v: counts(
        [r for r in rows if r["version"] == v and (concern == "All" or r["concern"] == concern)], metric)
        for v in VERSIONS} for concern in concerns + ["All"]} for metric in METRICS}


def calibration(rows, concerns, threshold):
    result = []
    for concern in concerns:
        shared = [r for r in rows if r["concern"] == concern and r["human_agreed"]]
        require(bool(shared), f"No investigator reference for {concern}")
        row = {"concern": concern, "n": len(shared),
               "human": sum(r["human_coder_1"] == r["human_coder_2"] for r in shared)}
        for coder in CODERS:
            row[coder] = sum(r["code_"+coder] == r["human_agreed"] for r in shared)
            row[coder+"_passes"] = row[coder] >= threshold
        result.append(row)
    return result


def original_qualification(original_calibration):
    """Freeze eligibility using ORIGINAL classifications, never the corrected check."""
    included, excluded, single = [], [], {}
    for row in original_calibration:
        passing = [c for c in CODERS if row[c+"_passes"]]
        if not passing:
            excluded.append(row["concern"])
        else:
            included.append(row["concern"])
            if len(passing) == 1:
                single[row["concern"]] = passing[0]
    return {"included": included, "excluded": excluded, "single_scorers": single}


def criticism_summary(rows):
    unique = {r["blind_id"]: r for r in rows}
    values = [(float(r["criticisms_sonnet"]) + float(r["criticisms_qwen"])) / 2
              for r in unique.values()]
    return {"reviews": len(unique), "mean": sum(values)/len(values) if values else None}


def agreement_summary(rows, left, right):
    pairs = [(r[left], r[right]) for r in rows if r[left] and r[right]]
    n = len(pairs)
    same = sum(a == b for a, b in pairs)
    pa, pb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    chance = sum(pa[c]*pb[c] for c in RANK)/(n*n) if n else None
    share = same/n if n else None
    kappa = (share-chance)/(1-chance) if n and chance != 1 else None
    return {"n": n, "same": same, "share": share, "kappa": kappa}


def diagnostics(rows):
    # Conditions identify recorded experiments; their numerical outcomes are computed below.
    specifications = {
        "effort": {"low": ("gpt-6-astra-effort-low", "Reader + criteria"),
                   "default": ("gpt-6-astra", "Reader + criteria"),
                   "max": ("gpt-6-astra-effort-max", "Reader + criteria")},
        "format": {"PDF": ("gemini-4-argon", "Reader instructions"),
                   "Text + figures": ("gemini-4-argon-mdfig", "Reader instructions")}}
    output = {}
    for kind, levels in specifications.items():
        output[kind] = {}
        for level, (model, prompt) in levels.items():
            output[kind][level] = {}
            for v in VERSIONS:
                selected = [r for r in rows if r["model"] == model
                            and r["prompt"] == prompt and r["version"] == v]
                require(bool(selected), f"Missing diagnostic condition: {kind}/{level}/{v}")
                criticism = criticism_summary(selected)
                output[kind][level][v] = {m: counts(selected, m) for m in METRICS}
                output[kind][level][v].update(reviews=criticism["reviews"], criticisms=criticism["mean"])
    return output


def decided_winner(pair):
    a, b = pair["winner_review_1_shown_first"], pair["winner_review_2_shown_first"]
    return a if a == b and a in (pair["review_1"], pair["review_2"]) else None


def judge_analysis(rows, pairs, concerns, original_restriction, register):
    lookup = defaultdict(dict)
    for row in rows:
        lookup[row["blind_id"]][row["concern"]] = row
    main_review_ids = {r['blind_id'] for r in rows if r['purpose'] == 'main'}
    for pair in pairs:
        require(pair["review_1"] in lookup and pair["review_2"] in lookup,
                "Judge pair refers to a missing review")
        for index in (1, 2):
            review_id = pair[f"review_{index}"]
            metadata = next(iter(lookup[review_id].values()))
            require(metadata["purpose"] == "main" and metadata["version"] == pair["version"]
                    and metadata["prompt"] == pair["prompt"]
                    and metadata["model"] == pair[f"model_{index}"],
                    "Pair matching conditions do not hold")
        require(pair["model_1"] != pair["model_2"], "Judge pair contains the same model twice")
        possible = (pair['review_1'], pair['review_2'])
        require(all(pair[k] in possible for k in
                    ('winner_review_1_shown_first', 'winner_review_2_shown_first')),
                "Each order's recorded winner must be one of the two reviews")
        require(pair['decided_winner'] in possible + ('undecided',),
                "Combined judge choice must be one of the two reviews or undecided")
        published = pair["decided_winner"] if pair["decided_winner"] in lookup else None
        require(decided_winner(pair) == published, "Combined judge verdict disagrees with the two orders")

    def score(review_id, selected, bound, metric):
        return sum(matches(lookup[review_id][c], metric, bound) for c in selected)

    def summarize(selected_pairs, selected, bound, metric, v="planted", miss=False):
        k = n = 0
        for pair in selected_pairs:
            winner = decided_winner(pair)
            if winner is None or pair["version"] != v:
                continue
            a, b = (score(pair[key], selected, bound, metric) for key in ("review_1", "review_2"))
            if a == b:
                continue
            n += 1
            better = pair["review_1"] if a > b else pair["review_2"]
            k += (winner != better) if miss else (winner == better)
        return {"k": k, "n": n, "share": k/n if n else None}

    output = {}
    types = {c: register.get("concerns", {}).get(c, {}).get("type", "Unspecified") for c in concerns}
    prompt_order = register.get("prompt_order", sorted({r["prompt"] for r in rows}))
    for judge in sorted({p["judge"] for p in pairs}):
        selected = [p for p in pairs if p["judge"] == judge]
        require(len({p['pair_id'] for p in selected}) == len(selected), "Duplicate pair–judge record")
        review_coverage = Counter(p[k] for p in selected for k in ('review_1', 'review_2'))
        require(set(review_coverage) == main_review_ids
                and set(review_coverage.values()) == {1},
                "Every main review must appear once in the pairing for each judge")
        first = sum(p["winner_review_1_shown_first"] == p["review_1"] for p in selected)
        first += sum(p["winner_review_2_shown_first"] == p["review_2"] for p in selected)
        item = {"pairs": len(selected), "decided": sum(decided_winner(p) is not None for p in selected),
                "first_position_wins": {"k": first, "n": 2*len(selected),
                                        "share": first/(2*len(selected))}, "variants": {}}
        bounds = ("lower", "higher", "sonnet") if "qwen" in judge else ("lower", "higher")
        for bound in bounds:
            for metric in METRICS:
                for subset in ("all pairs", "no OpenAI pairs"):
                    ps = [p for p in selected if subset == "all pairs" or not
                          (p["model_1"].startswith("gpt-") or p["model_2"].startswith("gpt-"))]
                    groups = {"all 8 concerns": concerns,
                              "reliably coded only": original_restriction}
                    variant = {
                        "agreement": {name: summarize(ps, cs, bound, metric) for name, cs in groups.items()},
                        "raised_on_baseline": {name: summarize(ps, cs, bound, metric, "baseline")
                                               for name, cs in groups.items()},
                        "agreement_by_prompt": {p: summarize([x for x in ps if x["prompt"] == p],
                                                             concerns, bound, metric) for p in prompt_order},
                        "agreement_by_type": {t: summarize(ps, [c for c in concerns if types[c] == t], bound, metric)
                                              for t in sorted(set(types.values()))},
                        "preferred_but_missed": {c: summarize(ps, [c], bound, metric, miss=True) for c in concerns}}
                    item["variants"][f"{bound}|{metric}|{subset}"] = variant
        output[judge] = item
    return output


def recommendation_analysis(rows, prompt_order):
    categories = ("Reject", "Major revision", "Minor revision", "Accept", "None")
    groups = {p: [p] for p in prompt_order}
    groups["Both requested prompts"] = [p for p in prompt_order if p != "Bare"]
    output = {}
    for group, prompts in groups.items():
        output[group] = {}
        for v in VERSIONS:
            rs = [r for r in rows if r["prompt"] in prompts and r["version"] == v]
            tally = Counter(r["recommendation"] or "None" for r in rs)
            require(not (set(tally)-set(categories)), "Unexpected publication recommendation")
            output[group][v] = {c: tally[c] for c in categories} | {"n": len(rs)}
    requested = [r for r in rows if r["prompt"] != "Bare"]
    by_model = defaultdict(list)
    for row in requested:
        by_model[row["model"]].append(row["recommendation"])
    always_major = [m for m, values in by_model.items() if values and set(values) == {"Major revision"}]
    return output, sorted(always_major)


def compute(original, pairs, recommendations, changes, human, register, concerns):
    corrected, applied = apply_corrections(original, changes)
    main = [r for r in corrected if r["purpose"] == "main"]
    original_main = [r for r in original if r["purpose"] == "main"]
    threshold = int(register["calibration_threshold"])
    require(threshold > 0, "Calibration threshold must be positive")
    old_cal = calibration(original, concerns, threshold)
    new_cal = calibration(corrected, concerns, threshold)
    qualification = original_qualification(old_cal)
    # This describes the observed post-disclosure rejection, not a prespecified general rule.
    rejected = [r["concern"] for r in human if r["no"] > r["n"]/2]
    six = qualification["included"]
    five = [c for c in six if c not in rejected]
    single = qualification["single_scorers"]
    sensitivities = {}
    for name, data, selected, scorer in (
        ("original_all_eight", original_main, concerns, {}),
        ("all_eight", main, concerns, {}),
        ("exclude_C5_C7_Qwen_C3", main, six, single),
        ("exclude_C2_C5_C7_Qwen_C3", main, five, single)):
        sensitivities[name] = {m: {v: counts([r for r in data if r["concern"] in selected
                                             and r["version"] == v], m, scorer)
                                    for v in VERSIONS} for m in METRICS}
    models = register.get("model_order", sorted({r["model"] for r in main}))
    require(set(models) == {r["model"] for r in main}, "Main-model register and CSV disagree")
    prompts = register.get("prompt_order", sorted({r["prompt"] for r in main}))
    require(set(prompts) == {r['prompt'] for r in main}, "Prompt register and main data disagree")
    cells = Counter((r['model'], r['version'], r['prompt']) for r in
                    {r['blind_id']: r for r in main}.values())
    require(len(cells) == len(models)*len(VERSIONS)*len(prompts)
            and len(set(cells.values())) == 1,
            "Main design is not balanced across model, version and prompt")
    run_keys = [(r['model'], r['version'], r['prompt'], r['run']) for r in
                {r['blind_id']: r for r in main}.values()]
    require(len(run_keys) == len(set(run_keys)), "Duplicate run within a main design cell")
    per_model = {model: {v: {m: counts([r for r in main if r["model"] == model and r["version"] == v], m)
                                  for m in METRICS} | {"reviews": len({r['blind_id'] for r in main
                                                                      if r['model'] == model and r['version'] == v})}
                         for v in VERSIONS} for model in models}
    per_prompt = {p: {m: {v: counts([r for r in main if r["prompt"] == p and r["version"] == v], m)
                          for v in VERSIONS} for m in METRICS} for p in prompts}
    ever = {model: {m: {bound: sum(any(matches(r, m, bound) for r in main
                                                 if r["model"] == model and r["version"] == "planted"
                                                 and r["concern"] == c) for c in concerns)
                             for bound in ("lower", "higher")} for m in METRICS} for model in models}
    construction = {}
    for metric in METRICS:
        construction[metric] = {}
        for group, used in (("used in construction", True), ("not used in construction", False)):
            construction[metric][group] = {}
            for v in VERSIONS:
                rs = [r for r in main if r["version"] == v
                      and r["model"].startswith(("claude", "gpt-")) == used]
                n = len({r['blind_id'] for r in rs})
                s = counts(rs, metric)
                construction[metric][group][v] = {b: s[b]/n for b in ("lower", "higher")}
    criticisms = {"all": {v: criticism_summary([r for r in main if r["version"] == v]) for v in VERSIONS},
                  "by_model": {model: {v: criticism_summary([r for r in main if r['model'] == model
                                                             and r['version'] == v]) for v in VERSIONS}
                               for model in models},
                  "by_prompt": {p: {v: criticism_summary([r for r in main if r['prompt'] == p
                                                          and r['version'] == v]) for v in VERSIONS}
                                for p in prompts}}
    rec, always_major = recommendation_analysis(recommendations, prompts)
    shared = [r for r in original if r["human_agreed"]]
    shared_reviews = {r["blind_id"] for r in shared}
    repeat_cells = Counter((r['model'], r['version'], r['prompt']) for r in
                           {r['blind_id']: r for r in main}.values())
    reviewer_totals = Counter(r['purpose'] for r in {r['blind_id']: r for r in corrected}.values())
    scalar = {"reviews_by_purpose": dict(reviewer_totals), "main_reviews": len({r['blind_id'] for r in main}),
              "main_reviews_per_version": {v: len({r['blind_id'] for r in main if r['version'] == v})
                                           for v in VERSIONS}, "main_models": len(models), "main_prompts": len(prompts),
              "repeats_per_model_version_prompt": sorted(set(repeat_cells.values())),
              "scoring_rows": len(original), "scorer_review_assignments": len({r['blind_id'] for r in original})*2,
              "corrections": len(applied), "corrected_review_concern_cases": len({(r['blind_id'],r['concern']) for r in applied}),
              "investigator_check_reviews": len(shared_reviews), "investigator_check_cells": len(shared),
              "investigator_initial_agreement": agreement_summary(shared, "human_coder_1", "human_coder_2"),
              "investigator_disagreements": sum(r['human_coder_1'] != r['human_coder_2'] for r in shared),
              "final_reference_equals_investigator_2": all(r['human_agreed'] == r['human_coder_2'] for r in shared),
              "scorer_agreement_original": agreement_summary(original, "code_sonnet", "code_qwen"),
              "scorer_agreement_corrected": agreement_summary(corrected, "code_sonnet", "code_qwen"),
              "human_validation_readers": human[0]['n'],
              "concerns_with_at_least_three_endorsements_including_qualified": sum(r['yes']+r['qualified'] >= 3 for r in human),
              "observed_majority_rejected_concerns": rejected, "always_major_models_requested_prompts": always_major,
              "always_major_model_count": len(always_major),
              "recommendations_extracted_by_method": dict(Counter(r['how_read'] for r in recommendations)),
              "requested_recommendations_present": sum(r['recommendation'] != 'None' for r in recommendations if r['prompt'] != 'Bare'),
              "criticisms": criticisms}
    result = {"primary": primary(main, concerns), "original_primary": primary(original_main, concerns),
              "sensitivities": sensitivities, "per_model": per_model, "prompts": per_prompt,
              "per_model_ever": ever, "diagnostics": diagnostics(corrected), "calibration_original": old_cal,
              "calibration_corrected": new_cal, "original_qualification": qualification,
              "post_hoc_human_exclusion": {"concerns": rejected, "basis": "Observed majority No after disclosure; post hoc, not a prespecified exclusion rule"},
              "judge": judge_analysis(corrected, pairs, concerns, six, register),
              "recommendations": rec, "construction": construction, "criticisms": criticisms,
              "applied_corrections": applied, "scalar_claims": scalar,
              "study_metadata_not_recomputed": register.get("metadata", {})}
    return result, corrected


def check_expected(result, expected):
    checks = []
    for assertion in expected.get("assertions", []):
        actual = result
        for part in assertion["path"].split("."):
            actual = actual[int(part)] if isinstance(actual, list) else actual[part]
        wanted = assertion["value"]
        tolerance = assertion.get("absolute_tolerance", 1e-10)
        same = math.isclose(actual, wanted, rel_tol=0, abs_tol=tolerance) if (
            isinstance(actual, (float, int)) and not isinstance(actual, bool)
            and isinstance(wanted, (float, int))) else actual == wanted
        checks.append({"path": assertion["path"], "pass": same,
                       "actual": actual, "expected": wanted})
    return checks

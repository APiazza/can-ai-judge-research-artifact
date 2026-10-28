# Offline numerical reproduction

Requires **Python 3.10 or later**, using only its standard library. Run from any working directory:

```text
python path/to/package/analysis/code/reproduce.py --output-dir path/to/new/generated
```

`python -I -S` may be used for an isolated run without site packages. Optional rule checks: `python -m unittest discover -s path/to/package/analysis/code -p test_analysis.py`.

The only inputs read are the named files in `analysis/data`, located relative to the script. No installation, network, API credentials, manuscript access, or paid model calls are needed. Inputs are never overwritten. Numerical reproduction differs from generating new AI reviews.

## Input contract

- `llm_codes_by_review_and_concern.csv`: one concern in one AI review. Required columns: `blind_id,purpose,model,provider,version,prompt,run,concern,code_sonnet,code_qwen,code_lower,code_higher,criticisms_sonnet,criticisms_qwen,human_coder_1,human_coder_2,human_agreed`. Codes are `F`, `P`, or `–` (ASCII `-` is accepted). Human columns are blank outside the investigator check. Human identities must not appear in column names.
- `judge_verdicts_by_pair.csv`: `pair_id,version,prompt,review_1,model_1,review_2,model_2,judge,winner_review_1_shown_first,winner_review_2_shown_first,decided_winner`. Winners are review IDs. A decided choice is independently recomputed from agreement across orders.
- `recommendations_by_review.csv`: `blind_id,model,version,prompt,recommendation,how_read`. Recommendations are `Reject`, `Major revision`, `Minor revision`, `Accept`, or `None`/`none stated`/blank. This analysis reproduces extracted verdicts; it does not repeat extraction from raw review text.
- `corrections.json`: list of dated audit corrections. Each has `blind_id,coder,concern,old_code,recommended_code`. Scorer names may be `claude-sonnet-5-5`/`qwen3p8-2p4t-a95b` or `sonnet`/`qwen`. The original code must agree exactly with the original CSV. Duplicate corrections are rejected. A top-level object containing `changes`, `corrections`, or `records` is also accepted.
- `human_validation_aggregate.csv`: `concern,yes,qualified,no,cannot_judge,n`, one row per concern. Only aggregate post-disclosure endorsement counts enter; no original external human reports are read.
- `study_register.json`: `model_labels` (ID-to-label object), `model_order` (main-model IDs), `concerns` (ID-to-object with `title,short_title,type`), `prompt_order` (display labels), and `calibration_threshold` (matches required per concern). Optional `metadata` stores retained run/processing provenance. Metadata are carried separately and are not represented as calculations from the scoring CSV.

Input version labels `clean` or `baseline` become **baseline**; `flawed` or `planted` become **planted**. These aliases describe archival labels, not construction chronology. Every generated display uses baseline/planted wording.

Optional `expected.json` contains independently assembled assertions:

```json
{"assertions": [{"path": "primary.F.All.planted.lower", "value": 894}]}
```

Paths traverse the generated `results.json`; array indices are numeric path components. Each assertion may supply `absolute_tolerance` (default `1e-10`). Expected values never enter a calculation. `--expected filename.json` selects a different file inside the package analysis directory (relative names resolve from `analysis/data`); it cannot read an external expected file. `--skip-expected` omits these checks. Exit codes: 0 success, 1 failed expected assertion, 2 invalid input or other reported failure.

## Calculations and outputs

The scoring CSV is preserved in memory as the original endpoint. The six-record correction overlay produces a separate corrected copy. Full-match lower/upper counts require F from both/either scorer at each review–concern observation; full-or-partial counts analogously accept F/P. These ranges are not confidence intervals.

Original exact-category investigator agreement determines scorer qualification. The six-concern detection restriction excludes concerns for which neither scorer originally passed and uses the originally passing scorer alone when only one passed. Corrected answers never retroactively qualify a scorer. The additional human-informed exclusion identifies the observed majority-No concern and is reported **post hoc**; it is not a prespecified general exclusion policy.

The delivered judge restriction uses the same retained concern set but both-scorer bounds for C3, matching the exploratory analysis. It does not substitute the single passing C3 scorer. Pairs with inconsistent order choices or equal detection totals are excluded. Original and corrected calibration, all numerical tables S3–S11, matched-version totals, model/prompt/diagnostic results, judge variants, recommendation counts, criticism means, construction groups, and repeated-run coverage are calculated directly.

Validation checks include original per-row bound agreement, complete concern coverage, consistent review metadata, balanced main-model/version/prompt cells, distinct repeat IDs, complete investigator-reference rows, correction old-code agreement and uniqueness, recommendation coverage/metadata, judge matching/choice consistency, and one pairing per main review for each judge. Exact study counts and published values are checked separately by the independent expected assertions.

Generated files: `results.json`, `scalar_claims.json`, `tables.md`, long-format `tables.csv`, `figure_data.csv`, `figure_1.svg`, `report.md`, `input_hashes.json`, and `expected_checks.json`. In `tables.csv`, each row is one displayed table cell (`table_id,table_title,row_number,column,value`); the JSON retains unrounded counts and denominators. Display rounding uses decimal half-up to one decimal place. Figure data contain all 16 corrected full-match ranges. SVG uses only standard XML, paths and text; exact font metrics can vary across viewers.

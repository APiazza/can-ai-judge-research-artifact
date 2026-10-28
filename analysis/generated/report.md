# Offline reproduction report

Calculated from 4,320 concern-level rows, covering 540 AI reviews. No network or model calls were made.

## Main full-match contrast

| Version | Original counts | Corrected counts | Denominator | Corrected % |
|---|---|---|---|---|
| planted | 893–936 | 894–936 | 1920 | 46.6–48.8 |
| baseline | 62–132 | 63–132 | 1920 | 3.3–6.9 |

Applied 6 dated classification corrections across 4 review–concern cases. Original data remain unchanged.

## Interpretation

Lower/upper full-match endpoints count both/either scorer for each observation. They are not confidence intervals. Original qualification controls all sensitivity restrictions; corrected calibration does not retroactively pass a scorer. The additional exclusion following observed human rejection is post hoc.

The delivered judge restriction excludes originally unqualified concerns but retains both-scorer bounds for C3. It therefore differs from the six-concern detection sensitivity, which uses the originally passing scorer alone for C3.

## Output files

- results.json: unrounded calculated counts, denominators, comparisons and metadata.
- scalar_claims.json: calculated scalar claims; supplied provenance metadata is separately labeled in results.json.
- tables.md and tables.csv: numerical Tables S3–S11, corrected calibration and correction register.
- figure_data.csv and figure_1.svg: all 16 corrected full-match segments.
- input_hashes.json: SHA-256 of each package input.
- expected_checks.json: optional independent expected-value assertions.

## Expected-value checks

1685/1685 supplied assertions passed.

## Input SHA-256

| Package input | SHA-256 |
|---|---|
| llm_codes_by_review_and_concern.csv | 5a8ce7b44afeb9421531a8acf3194a46e1934211003e3e648e67aa870e1d11d6 |
| judge_verdicts_by_pair.csv | d31bd23c349f148e3ad9e2f2e7ae1799d7bda1c94f0da8f50e3dce1f0e1bad1d |
| recommendations_by_review.csv | b16087d19a8e1c0adb36e07eb0d3328898473a3be9ee4deffccce3b85c6e099f |
| corrections.json | c121764cf4b16535dcc3122608651a7e24344309b4ca2f3e0e7e5eec88055e59 |
| human_validation_aggregate.csv | 2288e81197afe347c05628fc5e48cee0e28b77fc679e8a104f5ee91b04cf1d60 |
| study_register.json | bda8b7d2d530820cb9d65c5f12e203c825095d0a15c82b54117e71e5087ab8d2 |

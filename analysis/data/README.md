# Reading the data

Each review has a blind identifier (`B001`–`B540`). These identify AI-generated reports, not human participants. The three CSV files were copied from the retained analytical delivery. There are no changes to observations or classifications in these copies. Investigator initials in column headings and recommendation-checker labels were replaced with neutral labels; UTF-8 and line endings were standardized.

| File | Rows | What a row means |
|---|---:|---|
| `llm_codes_by_review_and_concern.csv` | 4,320 | One concern in one of 540 AI reviews. Each review has eight rows. |
| `judge_verdicts_by_pair.csv` | 480 | One review pair assessed by one of two judges; the row records both presentation orders. |
| `recommendations_by_review.csv` | 480 | One main AI review and its extracted publication recommendation, including missing recommendations. |
| `human_validation_aggregate.csv` | 8 | Counts of five external readers' post-disclosure judgments on one concern, including any reader who could not judge it. |

In the scoring file, `purpose` distinguishes the 480 main reviews from the 40 effort and 20 format checks. `model`, `prompt`, and `run` describe the reviewing condition. Historical `clean` means baseline; `planted` or `flawed` means the version into which problems were introduced. The program uses baseline/planted in its output.

`code_sonnet` and `code_qwen` are the original scorers' classifications: F (specified concern with the required reasoning), P (concern without that reasoning), or – (no match). `code_lower` and `code_higher` are the original weaker and stronger codes for that particular observation; they are checked against the scorer columns. They are recalculated after corrections. `criticisms_sonnet` and `criticisms_qwen` count all listed criticisms, including ones outside the eight intended concerns; they repeat across the eight rows for a review and must not be summed across those rows.

`human_coder_1`, `human_coder_2`, and `human_agreed` contain the two investigators' original codes and resolved reference for the core 24 AI reviews. They are blank elsewhere. These columns are distinct from the five external expert readers. The resolved reference equals investigator 2's original codes; it is not an independent external standard.

The judge file identifies the two AI reviews, their models, version and prompt, and the chosen review in each presentation order. A pair has a decided winner only when the same review wins both orders. The program recomputes that rule and checks the saved combined decision. The recommendation file reproduces already extracted decisions; it does not rerun language-based extraction.

`corrections.json` records each original and corrected classification and the reason for it. The confidential companion carries the complete underlying quotations and source text. The original scoring CSV is not overwritten.

`study_register.json` supplies display labels, the original calibration threshold, and clearly labeled study context. `expected.json` supplies independent expected results for verification after calculation. Expected results never enter the calculations. The human aggregate file is a privacy-preserving transcription of the included validation counts; private reader responses are not distributed in either archive.

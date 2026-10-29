# Release note: API-call runner

This folder is the code that made the pilot's model calls: reviewing, scoring (coding), judging, and recommendation extraction, plus the analysis that built the pilot tables. Start with `RUN.md`; its Dropbox paths describe the original investigators’ layout. In this release, use the manuscript inputs under `materials/manuscripts/input_text_and_figures/` and the frozen scoring sheet `materials/scoring/frozen_scoring_sheet.txt` in the separate confidential companion. Set `coding_sheet` to that file. Copy the exact-input `planted/` folder to a new local inputs folder as `pilot-v6/`, and copy `baseline/` as `clean-matched-v6/`; set `inputs_dir` to their new parent. Keep the supplied filenames and figures unchanged. Use these exact model inputs, not the scrubbed reading PDFs in the parent folder. Set `data_dir` and `dry_run_dir` to separate local output folders outside this repository, and enter the construction-key hashes in `key_sha256`. The full run records are withheld, as explained below.

The historical `corpus/README.md` describes the intended design. The pilot scored all eight concerns and reports exploratory sensitivity exclusions; it did not remove unendorsed concerns before scoring. Human validation is retained only as aggregates.

## What this copy is

It is the repository at the final pilot commit, with the following changes for anonymous review:

- `CITATION.cff` removed.
- `LICENSE`: author names in the two copyright lines replaced with "The authors (names withheld for anonymous review)".
- `config/paths.example.yaml`: example operator initials replaced with `XX`.
- `docs/run_record.md`, `harness/coding.py`, `plans/judge_v1.yaml`, and the three document scripts in `reports/`: investigators' names and initials replaced with "Investigator 1" or "the principal investigator". In `coding.py` this changes only the description string written into a read record; the codes it produces are unchanged. In `plans/judge_v1.yaml` it changes a comment line, so that file's SHA-256 no longer matches the value stored in the original judge records.
- `RUN.md` §4: commit identifiers replaced with `[withheld]`.

One test fixture also replaces identifying investigator initials. No scientific analysis or retained model output was changed. Commit identifiers and the git history are withheld during review because each commit records its author. They will be released with the de-anonymized package. Every commit named in the original `RUN.md` §4 is in that history.

## What runs without API keys

- `python -m pytest`, the harness's own tests, needs the packages in `requirements-lock.txt`.
- The review `dry-run` builds requests without calling any API, using exact manuscript inputs from the confidential companion and the directory mapping above. Coding and judge dry runs also need the withheld full run records; these are investigator-verified features, not self-contained reproduction commands in this release.
- The confidential companion’s frozen scoring sheet has identifying author text withheld (SHA-256 `f2ff1b08cb5222cadff10b37c57755d9c4c2d78fb486299b1f5ed3f9f8326b24`). The historical coding plan enforces the original hash `1fb2c0ca110c6dee0d7fa2209d4cff54a2e7683cfb78accc62dc72ed178dcc2f`. To use the anonymous sheet for new coding, create a new plan copy with its hash; this would be a new run, not an exact rebuild of the historical request. The release does not modify the original plan or bypass its integrity check.
- The offline rebuild in `RUN.md` §2 reads the full run records (all raw model outputs, about 640 MB). Those records are not in this package. The tables reported in the proposal and supplement are reproduced by `analysis/code/reproduce.py` from the exported data files instead.

The commands that write outputs require a committed, clean working tree, so the output names the code that produced it. In this copy, run `git init`, `git add -A`, and `git commit -m snapshot` first. Outputs will then name that local commit, not the original one.

## Additional release check (October 29, 2026)

A fresh copy configured solely with the released confidential exact manuscript inputs and the folder mapping above generated all 480 main-review requests in a dry run, passing key isolation. No API was called. The extracted runner passed 100 tests, with three local-manuscript-configuration tests skipped.

## What the investigators checked (October 28, 2026)

- The repository snapshot is identical to the head of the full history, and all commits cited in the run records are present. All 18 run records report a clean working tree.
- From a copy of the full run records, the four offline commands in `RUN.md` §2 reproduced the saved outputs. Code and selection files were byte-identical. Metadata differed only in time, commit, and operator. `tables.json` differed only in the last floating-point digits of nine agreement statistics (Python 3.13 here, 3.11 originally).
- The saved judge analysis was built against an earlier tables folder (`20261026T054634Z`), not the `20261026T201743Z` folder named in `RUN.md`. Rebuilding it against either gives identical results.
- Dry runs build 480 review, 1,080 coding, and 960 judge requests. All 483 saved main-review requests, including three errored attempts, are identical to the requests this code builds today.
- With the exact packages in `requirements-lock.txt` (Python 3.13), the harness's 103 tests pass on both the original code and this anonymized copy. Three of them need local manuscript inputs and are skipped without `config/paths.local.yaml`.

New API calls need your own keys, and will not reproduce the original texts: model outputs vary, and providers change or retire models.

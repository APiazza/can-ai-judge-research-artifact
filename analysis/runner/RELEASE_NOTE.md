# Release note: API-call runner

This folder is the code that made the pilot's model calls: reviewing, scoring (coding), judging, and recommendation extraction, plus the analysis that built the pilot tables. Start with `RUN.md`.

## What this copy is

It is the repository at the final pilot commit, with the following changes for anonymous review:

- `CITATION.cff` removed.
- `LICENSE`: author names in the two copyright lines replaced with "The authors (names withheld for anonymous review)".
- `config/paths.example.yaml`: example operator initials replaced with `XX`.
- `docs/run_record.md`, `harness/coding.py`, `plans/judge_v1.yaml`, and the three document scripts in `reports/`: investigators' names and initials replaced with "Investigator 1" or "the principal investigator". In `coding.py` this changes only the description string written into a read record; the codes it produces are unchanged. In `plans/judge_v1.yaml` it changes a comment line, so that file's SHA-256 no longer matches the value stored in the original judge records.
- `RUN.md` §4: commit identifiers replaced with `[withheld]`.

No other file differs. Commit identifiers and the git history are withheld during review because each commit records its author. They will be released with the de-anonymized package. Every commit named in the original `RUN.md` §4 is in that history.

## What runs without API keys

- `python -m pytest`, the harness's own tests, needs the packages in `requirements-lock.txt`.
- `dry-run` for reviewing, coding, and judging builds every request and writes it to disk without calling any API. It needs the manuscript inputs, which are in the confidential review materials.
- The offline rebuild in `RUN.md` §2 reads the full run records (all raw model outputs, about 640 MB). Those records are not in this package. The tables reported in the proposal and supplement are reproduced by `analysis/code/reproduce.py` from the exported data files instead.

The commands that write outputs require a committed, clean working tree, so the output names the code that produced it. In this copy, run `git init`, `git add -A`, and `git commit -m snapshot` first. Outputs will then name that local commit, not the original one.

## What the investigators checked (October 28, 2026)

- The repository snapshot is identical to the head of the full history, and all commits cited in the run records are present. All 18 run records report a clean working tree.
- From a copy of the full run records, the four offline commands in `RUN.md` §2 reproduced the saved outputs. Code and selection files were byte-identical. Metadata differed only in time, commit, and operator. `tables.json` differed only in the last floating-point digits of nine agreement statistics (Python 3.13 here, 3.11 originally).
- The saved judge analysis was built against an earlier tables folder (`20261026T054634Z`), not the `20261026T201743Z` folder named in `RUN.md`. Rebuilding it against either gives identical results.
- Dry runs build 480 review, 1,080 coding, and 960 judge requests. All 483 saved main-review requests, including three errored attempts, are identical to the requests this code builds today.
- With the exact packages in `requirements-lock.txt` (Python 3.13), the harness's 103 tests pass on both the original code and this anonymized copy. Three of them need local manuscript inputs and are skipped without `config/paths.local.yaml`.

New API calls need your own keys, and will not reproduce the original texts: model outputs vary, and providers change or retire models.

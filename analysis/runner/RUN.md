# Running the pilot

This repository holds all the code used for the STATUS-P01 pilot: the API-call runners for reviewing, coding
(scoring), judging and recommendation extraction; the analysis that makes the tables; and the scripts that build the
results documents, the run plan and the workflow figure. Every run record names the commit it was made with (table
below), so any step can be checked against the exact code.

The records themselves are in the Dropbox workspace under `harness/runs/`. The documents and data built from them are
under `harness/pilot_results/`.

## 1. Setup

Python 3.11.

```
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-lock.txt
python -m pytest                  # 103 tests, no API calls
```

`requirements.txt` lists the direct dependencies; `requirements-lock.txt` pins every package in the environment used for
all the runs (each batch record also lists the SDK versions). The scripts in `reports/` also need
`pip install -r reports/requirements.txt`.

Copy `config/paths.example.yaml` to `config/paths.local.yaml` and fill it in:

- `inputs_dir`: the AI copies of the manuscripts, `corpus/papers/STATUS-P01/ai-run-inputs/` in Dropbox.
- `data_dir`: a local folder for run records. To work from the pilot's records, copy `harness/runs/` from Dropbox
  here. Commands write new, time-stamped output folders, so do not point this at Dropbox itself.
- `keys_file`: a text file with lines `Anthropic: ...`, `Google: ...`, `OpenAI: ...`, `Fireworks AI: ...`. Keys are
  not part of this package. They are needed only for live calls.
- `key_sha256`: the SHA-256 of each answer-key file in `corpus/keys/`. The review runner checks that no input matches a
  key; it never reads the key.
- `coding_sheet`: `corpus/keys/STATUS-P01-coding-sheet-v1.0-frozen.md`, the text sent to the LLM coders (SHA-256
  1fb2c0ca…, checked against `plans/coding_v1.yaml`).

Run all commands from the repository folder; plan files are given relative to it. Every command that writes records or
outputs needs a clean, committed working tree, so the output can name its commit. Live calls also need `--live`.

## 2. Rebuild the tables and documents from the saved records (no API calls)

With `data_dir` holding a copy of `harness/runs/`:

```
python -m harness.code read coding_v1-20261024T191027Z --rules rules_2026_10_24
python -m harness.tables coding_v1-20261024T191027Z --read rules_2026_10_24-20261025T054512Z --human human_check/human_codes.json
python -m harness.judge_tables judge_v1-20261026T053102Z --coding coding_v1-20261024T191027Z --read rules_2026_10_24-20261025T054512Z --tables 20261026T201743Z
python -m harness.recommendations tables 20261026T195856Z --hand hand.json

python reports/export_raw_data.py   --runs <data_dir> --out <folder>
python reports/make_results_doc.py  --runs <data_dir> --out <folder>
python reports/make_judge_doc.py    --runs <data_dir> --out <folder>
python reports/make_workflow_fig.py --out <folder>
python reports/make_run_plan.py     --out <folder>
```

The `reports/` scripts read the outputs named above (reads `rules_2026_10_24-20261025T054512Z`, tables
`20261026T201743Z`, judge analysis `20261026T055439Z`, recommendation tables `20261026T200718Z`). A new run of the
analysis commands writes new folders with the same contents. The human-check codes were exported from the two coding
forms and the disagreement sheet with `python tools/export_human_codes.py CODER1.xlsx CODER2.xlsx DISAGREEMENTS.xlsx
OUT.json` (needs openpyxl); the forms are in the coding batch's `human_check/` folder.

## 3. Run the API calls again

Model outputs vary from call to call, and providers may change or retire models, so new runs give new texts. The
saved records are what the tables come from. Each step writes a new batch; `dry-run` builds every request without
calling any API.

Reviewing:

```
python -m harness.review dry-run plans/main_v1.yaml
python -m harness.review start   plans/main_v1.yaml --live
python -m harness.review resume  <batch_id> --live
python -m harness.review rerun   <batch_id> --slots 3 7 --reason "..." --live
python -m harness.review status  <batch_id>
python -m harness.report <batch_id>                  # tokens, time and cost; writes a usage summary into the batch folder
```

The pilot used `plans/practice_v1.yaml`, `effort_check_v1.yaml`, `main_v1.yaml`, `effort_v1.yaml` and
`format_v1.yaml`.

Coding (scoring), with both LLM coders:

```
python -m harness.code blind   plans/coding_v1.yaml   # blind IDs and the human-check sample
python -m harness.code dry-run plans/coding_v1.yaml
python -m harness.code start   plans/coding_v1.yaml --live
python -m harness.code resume  <batch_id> --live [--coders KEY ...] [--workers N]
python -m harness.code rerun   <batch_id> --slots 3 7 --reason "..." --live
python -m harness.code read    <batch_id> --rules rules_2026_10_24
```

Judging:

```
python -m harness.judge pair    plans/judge_v1.yaml   # 240 pairs within version x prompt
python -m harness.judge dry-run plans/judge_v1.yaml
python -m harness.judge start   plans/judge_v1.yaml --live
python -m harness.judge status  <batch_id>
```

Recommendations (no API calls):

```
python -m harness.recommendations extract             # writes extraction.jsonl and hand_check.csv
python -m harness.recommendations tables <folder> --hand hand.json
```

`hand.json` holds the decisions for the reviews that name more than one option, as
`{"rule": "...", "decisions": {"B006": "Minor revision", ...}}`.

More detail on what each record holds is in `docs/run_record.md`.

## 4. Which commit made which record

| Record | Commit |
|---|---|
| Practice reviews `practice_v1-20261015T213147Z` | [withheld] |
| Effort check `effort_check_v1-20261017T013543Z` | [withheld] |
| Main, effort and format reviews (`main_v1-20261018T210504Z`, `effort_v1-20261018T221245Z`, `format_v1-20261018T215347Z`) | [withheld] |
| Blinding and human-check sample (`coding/blinding/coding_v1/`) | [withheld] |
| Coding `coding_v1-20261024T191027Z`: start / resume and reruns | [withheld] / [withheld], [withheld], [withheld] |
| Coding re-read `rules_2026_10_24-20261025T054512Z` | [withheld] |
| Judge pairs (`judge/pairs/judge_v1/`) | [withheld] |
| Judging `judge_v1-20261026T053102Z` | [withheld] |
| Results tables `20261026T201743Z` | [withheld] |
| Judge analysis `20261026T055439Z` | [withheld] |
| Recommendations `20261026T195856Z` | [withheld] |

The `reports/` scripts and this file were added afterwards; they do not change any harness code.

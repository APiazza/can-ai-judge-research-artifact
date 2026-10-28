# Run record

One record per batch plus one log line per call. Review runs and coding runs are stored apart.

## Where things are kept

| Item | Location |
|---|---|
| Harness code, prompt templates, model and plan configuration | this repository; the commit hash is written into every call record |
| Manuscript inputs (`pilot-v6/`, `clean-matched-v6/`) | Dropbox `corpus/papers/STATUS-P01/ai-run-inputs/`; never in the repository |
| Answer key | Dropbox `corpus/keys/`; never in the repository and never readable by a review run |
| Review run records and raw responses | `data_dir/review/<batch_id>/`, outside the repository, copied to Dropbox |
| Coding run records | `data_dir/coding/<batch_id>/`, apart from the review runs, since they contain the key |
| Scored tables and summaries | `results/` in this repository |
| Human decisions (dropping a run, fixing a parsing error, recoding an item) | `worklog.md` in Dropbox, with the reason |

Local paths are set in `config/paths.local.yaml` (not committed; see `config/paths.example.yaml`). The harness refuses
input or data folders inside the repository.

## Prompt templates

Templates are files in `prompts/`, each listed in `prompts/manifest.yaml` with its SHA-256. A template is never edited
once a run has used it; a change is a new file and a new manifest entry. The harness stops if a template file no longer
matches its recorded hash. The text sent is the file content with trailing newlines removed. There is no system message.

## Batch record: `batch.json`

Written once when the batch is created: batch ID, the provider endpoints used (fixed in the code, not taken from the
environment), the first 12 hex digits of the SHA-256 of each API key used (identifies the account without revealing
the key; keys come from the local keys file, which overrides any key set in the environment), plan file and its SHA-256, purpose (practice, main, effort, format),
operator, git commit, harness version, SDK and Python versions, template hashes, the full configuration of every model
in the batch, the SHA-256 of every input file, the key isolation result, the price table used for cost estimates, and
the numbered list of slots (model configuration × prompt × manuscript × replicate). `events.jsonl` adds one line per
start, resume or rerun command, with time, commit and operator.

## Call record: one line in `calls.jsonl`

| Field | Content |
|---|---|
| `run_id` | `<batch_id>-s<slot>-a<attempt>` |
| `slot`, `attempt`, `parent_run_id`, `rerun_reason` | a rerun is a new attempt with its parent run and the reason |
| `git_commit`, `git_dirty`, `harness_version` | code that made the call |
| `provider`, `route` | e.g. `anthropic` / `anthropic_api`; `fireworks` / `fireworks_serverless` |
| `model_requested`, `model_returned` | model ID sent and model ID in the response |
| `construction` | `used in construction` or `not used in construction` |
| `manuscript`, `version` | `pilot-v6` (flawed) or `clean-matched-v6` (clean) |
| `input_format`, `input_route`, `input_files` | PDF, text plus figures, or text only; every file sent with its SHA-256 |
| `template_id`, `template_file`, `template_sha256`, `rung` | prompt as versioned |
| `request_file`, `request_sha256` | the exact request as sent, binary files shown as name and SHA-256 |
| `settings` | effort, thinking, temperature, token limit, caching, system message, tools; a setting not sent is recorded as `not set (provider default)` |
| `settings_reported` | settings the provider says it applied (Fireworks: sampling and reasoning options from response headers) |
| `effort_reported`, `effort_default_documented` | effort reported by the API, or `unknown`; the provider's documented default and its source |
| `time_sent_utc`, `time_received_utc`, `seconds` | |
| `request_id` | provider request ID |
| `status`, `stop_reason` | see below |
| `usage` | input, cached input, cache writes, billed output and reasoning tokens; `usage_provider_fields` keeps the provider's own fields |
| `cost_estimate` | USD at list price (`config/prices.yaml`, dated) or `unknown`; billed amounts are on the provider consoles |
| `raw_file`, `raw_sha256` | the response or error, complete and unedited |
| `text_file`, `text_sha256`, `text_chars` | the review text exactly as returned |
| `error` | type, message, HTTP status and request ID for a failed call, or the error from reading a saved response |

The request file is written before the call is sent. A request file without a call record means the process stopped
during the call; the next resume or rerun records that attempt as `interrupted`.

## Status

`ok` (normal stop, non-empty text), `truncated` (token limit), `refused` (refusal or safety stop), `empty`, `other`
(any other stop reason), `error` (no response), `parse_error` (response saved in `raw/` but could not be read), `interrupted`. Every attempt is kept. A slot that has an `ok` attempt is
not rerun. Which statuses enter the analysis is set in the analysis plan.

## Settings

No system message, no tools, no web access. Temperature is not sent. Effort is sent where the model configuration
gives it: for Anthropic and Google, which do not report effort, the documented default (high for Claude Fable 5.1, medium
for Claude Haiku 5.5 and Gemini 4 Argon, minimal for Gemini 3.5 Flash-Lite), so the record shows a value and a change
of default during the runs has no effect; low and max in the effort comparison. OpenAI and DeepSeek report the effort
they apply, and Kimi K3's default is not documented; those are left unset. SDK retries are off, so every attempt is a recorded
call. No automatic switch to another model is enabled. Anthropic and Fireworks responses are streamed and assembled
before saving. The raw response is saved before any field is read from it. Anthropic requests place a cache breakpoint
after the manuscript; OpenAI requests carry a `prompt_cache_key` (the manuscript file's hash) so repeated calls on the
same file reach OpenAI's cache; Gemini caches repeated input automatically. Each underlying model has one queue, so its
configurations (effort levels, input formats) run one call at a time, in the order replicate → manuscript → prompt;
different models run in parallel.

## Key isolation

The review runner is given only the inputs folder and the SHA-256 of each key file, never the key's location. Before a
batch it checks that every file it will send is inside the inputs folder and unchanged since hashing, that no file in
the inputs folder matches a key hash or is named like a key, and that no file sent contains a version, folder or key
label. The result is written into `batch.json`.

## Commands

```
python -m harness.review dry-run plans/practice_v1.yaml          # builds every request, no API call; kept local
python -m harness.review start   plans/practice_v1.yaml --live   # paid calls; needs a clean, committed tree
python -m harness.review resume  <batch_id> --live [--models KEY ...]
python -m harness.review rerun   <batch_id> --slots 3 7 --reason "HTTP 529 overloaded" --live
python -m harness.review status  <batch_id>                     # a model queue stops after 3 errors in a row; resume continues it
python -m harness.report <batch_id>                               # tokens, time and cost per call and per account
python -m pytest
```

## Coding runs

Separate entry point, `harness.code`, with records in `data_dir/coding/`, apart from the review runs.

```
python -m harness.code blind   plans/coding_v1.yaml          # blinding.json and human_sample.json; no API call
python -m harness.code dry-run plans/coding_v1.yaml          # builds every request; no API call; kept local
python -m harness.code start   plans/coding_v1.yaml --live   # paid calls; needs a clean, committed tree
python -m harness.code resume  <batch_id> --live
python -m harness.code rerun   <batch_id> --slots 3 7 --reason "..." --live
python -m harness.code status  <batch_id>
```

**Blinding.** `blind` collects the complete review of every slot in the review batches named in the plan, checks
each text against its call record's SHA-256, shuffles them with the plan's seed and numbers them B001, B002, ....
`blinding.json` joins each blind ID to its review run; it is used again only to unblind. The same command draws the
human sample (coding sheet v1.0, section 5) into `human_sample.json`, before any review is coded. Both files are
written once.

**What a coder receives.** One user message: the coding template (`prompts/coding/`), with the frozen coding sheet
in its first slot and the review text, exactly as the reviewing model returned it, in its second. Nothing else: no
model, manuscript version, prompt or run label, no manuscript, no system message, no tools. The coding sheet is
read from the local path in `config/paths.local.yaml` (read only by `harness.code`, never by the review runner) and
must match the SHA-256 in the plan. Settings follow the review runs: Claude Sonnet 5.5 receives its documented default
effort (high) explicitly; Qwen3.8 is left at the provider default. Anthropic requests place a cache breakpoint after
the coding sheet, which is the same in every call. Each coder's slots are split into `workers_per_coder` queues
that run in parallel; the order was already shuffled at blinding.

**Call record.** As for review runs, plus `blind_id`, `review_text_sha256`, `coding_sheet_version`,
`coding_sheet_sha256`, `codes_file` (`codes/<run_id>.json`: the codes read from the answer), `problems`,
`quote_flags` and `criticism_count`. An answer is `ok` when it holds one JSON object with all eight concerns, codes F,
P or –, a quote and a reason for every F and P, a different alternative code and a reason for every unsure code, and a
criticism count equal to the number of criticisms listed; otherwise it is `invalid_output`, kept, and may be rerun with
a reason. Each quote is checked against the review text (case, quote marks, dashes, emphasis and spacing ignored);
a quote not found, or longer than 40 words, is flagged, not rejected.

**Reading again.** `python -m harness.code read <batch_id> --rules <rules>` reads every saved answer again without
calling any API and writes `reads/<rules>-<time>/` (`codes.jsonl`: one row per attempt; `selected.jsonl`: per slot,
the latest attempt that reads without problems; `read.json`: the rules, commit and counts). Call records and answers
are not changed. `rules_2026_10_24` (decided by Investigator 1, worklog 2026-10-24): a concern without an "unsure" field is read
as not unsure, and a criticism_count that differs from the list is replaced by the list length, with the stated count
kept. Any other problem still leaves the attempt unusable.

**Batch record.** As for review runs, plus the coding sheet version and SHA-256 (the Markdown sent and the frozen
Word file), the SHA-256 of the answer-key files, the blinding file's SHA-256 and seed, the isolation results of each
review batch (so the record shows that no review run could read the key), the provider metadata of each coder, and
a note that Fireworks serverless does not expose the open-weight coder's weight files, so no weight hash can be
recorded.

## Judge runs (exploratory)

Entry point `harness.judge`, records in `data_dir/judge/`. Added on 24 Oct 2026 after the coding sheet was frozen,
following the principal investigator's plan (project workspace `harness/pilot_run_plan/preference_vs_detection_plan_2026-10-24.md`) and the
details settled in the worklog of 24 Oct. Reported as exploratory.

```
python -m harness.judge pair    plans/judge_v1.yaml          # pairs.json; no API call
python -m harness.judge dry-run plans/judge_v1.yaml          # builds every request; no API call; kept local
python -m harness.judge start   plans/judge_v1.yaml --live [--judges KEY ...]
python -m harness.judge resume  <batch_id> --live [--judges KEY ...] [--workers N]
python -m harness.judge rerun   <batch_id> --slots 3 7 --reason "..." --live [--workers N]
python -m harness.judge status  <batch_id>
```

**Pairs.** The main reviews keep their blind IDs from the coding blinding. Within each version × prompt cell the
reviews are shuffled with the plan's seed and paired so that the two reviews of a pair come from different models;
every main review is in exactly one pair (240 pairs). Each pair is judged in both orders, in a shuffled running order.

**What a judge receives.** System message: King and Worthington (2026), Supplementary Appendix D(b), with their
abbreviated Appendix B guidelines inserted (`prompts/judge/kw_pairwise_reviews_only_v1.txt`; see the manifest for
how it was taken from the PDF). User message: the two review texts, exactly as returned, in `<review_a>` and
`<review_b>` tags. No manuscript and no ID, model, version or prompt label. GPT-5.5 runs at its maximum reasoning
effort (xhigh), sent explicitly; Qwen3.8 at the provider default, as in coding.

**Call record.** As for review runs, plus `pair_id`, `order`, `review_a` and `review_b` (blind IDs) with their text
hashes, the two template hashes, `winner` (A or B), `winner_blind_id`, `rationale` and `problems`. A verdict is `ok`
when the answer holds a JSON object whose winner is A or B; otherwise `invalid_output`, kept, and rerun only with a
reason. A win counts in the analysis only if the same review wins in both orders.

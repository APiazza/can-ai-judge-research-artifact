# Recorded model and prompt configuration

This directory contains configuration recovered from the retained pilot execution records. It was assembled before the original API-call runner was received. That runner is now in `../runner`. These files remain as an independent record of what the requests contained, and they do not make new review, coding, or judging calls.

- `recorded_configuration.json` records the requested models, response limits, effort settings, software versions, batch counts, and recorded key-isolation checks.
- `prompts/review/` contains the three exact prompt strings recovered from successful requests. The original template-file hashes match after adding a terminal newline, which the requests omit; this distinction is recorded in the JSON.
- `prompts/judge/` contains the exact judge instruction string recovered from a request, excluding the paired AI reviews.
- `input_hash_manifest.json` inventories the twenty manuscript/figure inputs and the restricted key/scoring-sheet hashes. Manuscript and key contents are not included here.
- `blank_instrument_inventory.json` inventories historical blank reader-instrument documents; it is not an export of the current live survey.
- `validate_configuration.py` is a newly written offline consistency check for these exported records. It is not part of the historical harness.

Run `python validate_configuration.py` from this directory, or supply its path from any directory. This requires only Python's standard library and makes no network or model calls. It checks recovered prompt hashes, batch counts, recorded isolation status, and key-hash consistency. It does not establish that the unavailable runner enforced the recorded isolation or reproduce an API response. The artifact's separate analysis scripts reproduce results from retained outputs.

The main-batch README's generic statement that effort was omitted is stale for four providers/models. The recorded configuration and actual call settings preserve explicitly requested effort for Fable, Haiku, Argon, and Flash-Lite. Requested settings and provider-reported effort are separate fields.

Release hashes identify these sanitized files. They are not Git commit identifiers and do not establish byte identity with the original execution checkout. Original commit provenance is retained separately. Coding-call counts describe raw attempt records; the final response-reading rules produced 1,080 classifications from 1,087 retained attempts, including initially flagged outputs.

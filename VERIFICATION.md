# Verification of the anonymous v0.15 artifact

**Result: the package reproduces the corrected numerical results in the proposal and supplement. No further numerical correction was needed.**

The proposal's main contrast remains 47–49% of planted-version comparisons versus 3–7% of baseline comparisons. Before rounding, the corrected counts are 894–936/1,920 and 63–132/1,920. The six classification changes remain a dated overlay on the original data.

## What was checked

| Check | Result |
|---|---|
| Corrected supplement Tables S3–S11 | All 239 numerical display cells agree, including judge denominators and original calibration decisions. |
| Proposal figure | All 16 rows agree: 112 cells including labels, counts, denominators, and percentages. The regenerated SVG displays the same evidence; its drawing code and typography differ from the reference image. |
| Exact expected values | 1,685 independently retained numerical and qualification assertions pass. Expected values are used only after calculation. |
| Run and inventory Tables S1, S2, S12, S13 | 51 checks agree with recorded batch dates/counts, actual input/effort settings, model identifiers, response limits, and CSV sizes. These describe retained records, not new model calls. |
| Configuration and prompts | 21 offline consistency checks pass; exact recovered prompt strings are included. |
| Original AI-review evidence | All 540 source-text hashes match; 1,080 structured scorer assignments link to all 8,640 original classifications in the analysis CSV. |
| Quotation audit | All 128 flagged assignments and four counterpart assignments are present; 308 replacement fragments match exact source positions. The six corrections agree across archives. |
| Processing rules | The structured scorer records reproduce the 75 answers with missing uncertainty fields, 23 corrected criticism totals, 3,736 quotations, 108 not-found flags, and 20 overlength flags. |
| Exact model inputs | All 20 files match their retained hashes: two PDFs, two Markdown manuscripts, and sixteen figures. |
| Consequential calculation rules | Seven small tests pass, covering both/either counting, scorer restrictions, original qualification, correction integrity, judge order consistency, expected assertions, and rounding. |

## Fresh-extraction test

Both archives were extracted into two new folders and executed from a separate working directory, with Python 3.12.14 on Windows. Python ran with `-I -S -B`: it ignored user/environment imports, omitted site packages, and did not create bytecode caches. An additional audit guard blocked network and subprocess calls and limited file access to the extracted package, its new output folder, and the Python runtime.

Both extractions passed all 1,685 expected assertions, the configuration check, the complete evidence-linkage check, and the file manifests. Each regenerated all nine analysis output files byte-for-byte identically to the supplied outputs and to the other extraction. This is an isolated execution test on the available Windows runtime, not a claim of testing every operating system or Python version. The code requires Python 3.10 or later and uses only the standard library.

## Documents and anonymity

The tracked working drafts were preserved. The proposal reading copy retains the opening and substantive text and remains 1,932 words including the caption, before references; figure text is excluded. The supplement reading copy changes only three source-provenance paragraphs to withhold repository identifiers and point to this completed verification. Its results and methodological interpretation are unchanged.

Metadata scrubbing preserved all pixels across the four reading PDFs (147 pages). The supplement's changed provenance pages and pages affected by comment removal were visually checked. The generated figure was rendered and inspected. Source names, revision authors, comments, local paths, and source Git identifiers were excluded from release copies. Human reader data appear only as aggregate counts. Legitimate scholarly citations remain. The exact baseline model-input PDF retains four anonymous MathML equation attachments; those are documented in its input inventory, not reader records.

## What this verification does not establish

The check starts from retained, parsed model outputs. It does not regenerate AI reviews, repeat all natural-language recommendation extraction, or independently rejudge every classification. The complete AI-review evidence and selected scorer records are supplied for inspection in the confidential companion.

The offline checker in `analysis/code` is newly assembled analysis code. The original API-call runner, received afterwards, is included separately in `analysis/runner`. From the full run records (not included here), the investigators confirmed that it reproduces the saved scoring, judge, and recommendation outputs, rebuilds all 483 recorded main-review requests exactly, and passes its own 103 tests. Details are in `analysis/runner/RELEASE_NOTE.md`. A new API run would require provider access and would yield different responses.

The external-reader table is reproduced from supplied aggregate counts; raw human responses and referee reports are excluded, so their extraction cannot be independently repeated from this package. No completed power or sample-size simulation is claimed. Repeated reviews of one invented manuscript pair do not establish results across papers or populations of reviewers.

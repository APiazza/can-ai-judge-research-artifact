> **About this repository.** It holds the same analysis files as the anonymous analysis artifact
> provided through Figshare, except the technical-supplement reading copy
> (`analysis/documents/`), which is submitted through the journal portal. The proposal is supplied separately through that portal. Steps below that open
> that PDF refers to the submitted copy. The confidential review materials (invented manuscripts,
> key, and AI review texts) are not in this repository; reviewers receive them through the private
> link in the submission. `MANIFEST.json` lists the fingerprints of the files in this repository. Git attribute files additionally disable line-ending conversion, including the runner’s nested attributes, to preserve released file bytes.

# Anonymous analysis artifact — release 2026-10-29

**Can AI Judge Research? Technical Competence and Scholarly Taste in Peer Review**

This package lets a reader reproduce the corrected pilot results without buying model access or installing statistical software. It contains saved observations from one invented manuscript pair, a short Python analysis, the resulting tables and figure, and an anonymous reading copy of the technical supplement. It does not contain the identities or original reports of the external human readers.

## Access

We provide the prototype through Figshare’s anonymous private links so reviewers can download the code, data, and supporting materials without signing in. The analysis files are also available in a GitHub repository. The analysis runs locally; no GitHub account is required.

## Start here

1. Read `analysis/documents/technical_supplement.pdf` for methods, interpretation, and limits. The proposal is supplied separately through the journal portal.
2. Read `analysis/generated/report.md` for the main comparison, or `analysis/generated/tables.md` for the numerical supplement tables.
3. To check the calculations yourself, use Python 3.10 or later. No extra packages, API keys, or network access are needed. From the folder containing this README, run:

```text
python -I -S -B analysis/code/reproduce.py --output-dir reproduced
python -I -S -B analysis/harness/validate_configuration.py
python -I -S -B verify_manifest.py
```

The first command writes a new `reproduced` folder. It reads the supplied data and applies six dated quotation-audit corrections. It then compares the calculations with independently retained expected values. A nonzero exit status signals a failed check. The second command checks the recorded prompts and run configuration. The third checks the released files against their SHA-256 fingerprints; these fingerprints detect changes to files, not the truth of their contents. Additional output folders do not alter the supplied files.

The completed extraction test, exact comparisons, and remaining limits are described in `VERIFICATION.md`.

## What the result means

Across 240 reviews of each version and eight concerns, the corrected full-match counts are **894–936 of 1,920 comparisons on the planted version (46.6–48.8%)**, versus **63–132 of 1,920 on the baseline (3.3–6.9%)**. A full match requires both the specified criticism and its reasoning. The lower count requires both scorers to assign a full match; the upper count requires either scorer. These ranges describe scorer disagreement, not statistical uncertainty across papers. They reproduce the proposal's rounded **47–49% versus 3–7%** contrast.

The baseline was written first; problems were then introduced into a separate copy. A criticism of the baseline can still be defensible. The experiment concerns one manuscript pair and does not establish performance across papers, superiority to human reviewers, or a general technical-versus-taste difference.

## What is in each folder

| Folder | Purpose |
|---|---|
| `analysis/data` | Original classifications, extracted publication recommendations, judge decisions, aggregate human validation, six corrections, and expected checks. |
| `analysis/code` | Newly assembled, readable Python code that calculates Tables S3–S11, narrative comparisons, and the figure from those inputs. |
| `analysis/generated` | The verified output. JSON preserves counts and denominators; Markdown and CSV provide displayed tables; SVG provides a portable figure. |
| `analysis/reference` | The corrected figure and its data as used in v0.15, retained for comparison. The numerical analysis never reads this folder. |
| `analysis/harness` | Exact recovered review/judge prompts, recorded settings, input hashes, and an offline configuration check. |
| `analysis/runner` | The original API-call runner for reviewing, scoring, judging, and recommendation extraction, with identifying details removed. Start with its `RELEASE_NOTE.md` and `RUN.md`. |
| `analysis/documents` | Anonymous technical-supplement PDF reading copy. The supplement explains methods, interpretation, and limits in ordinary language. |

`analysis/data/README.md` explains the observations and the few changes made for anonymity. `analysis/code/README.md` describes calculation rules and the complete output schema.

## How the corrections and human evidence are handled

The original classification file remains visible. `corrections.json` is a separate overlay: six scorer assignments change across four review–concern cases. The original and corrected all-eight results are both reproduced. The original 24-review calibration determines which scorers qualified; corrected answers on selectively audited reviews do not retroactively qualify a scorer. The six-concern detection check therefore still excludes C5/C7 and uses Qwen alone for C3. The additional C2 exclusion follows three of five external readers' rejection and is explicitly exploratory. The judge sensitivity keeps both scorers for C3, as explained in the supplement.

Human validation is supplied only as eight aggregate rows. Reproduction checks those counts and their summaries; it cannot independently reconstruct them from private responses. The five readers' original referee reports have not been scored here. Investigator calibration codes in the main CSV concern investigator assessments of AI reviews; they are separate from the external readers' validation responses.

## Confidential companion and limits

The separate confidential materials archive supplies the invented manuscripts, construction key, frozen scoring instructions, 540 original AI reviews, 1,080 structured scorer records, and all 132 quotation-audit assignments. The key is kept separate from manuscript inputs. That companion permits inspection of the evidence and verification of exact quotation fragments without including raw human responses. Keep it with the confidential reviewer materials rather than putting its contents into a public code repository.

The original API-call runner is in `analysis/runner`. Without API keys, its review dry run builds requests from the confidential companion’s exact manuscript inputs. Scoring and judge request rebuilding also requires the full run records, which are withheld; those checks were performed by the investigators. The released scoring sheet is anonymized, so its hash differs from the original enforced in the historical coding plan; see the runner release note. With provider keys it can make new calls, but new calls will not reproduce the original texts: model outputs vary, and providers change or retire models. The runner's own offline rebuild needs the full run records, which are not included here. The investigators confirmed from those records that it reproduces the saved outputs (see its `RELEASE_NOTE.md`). The numerical results in this package are reproduced from the exported data files by `analysis/code/reproduce.py`. No sample-size or power simulations have yet been completed, and none are presented as reproduced results.

## Anonymous reading copies

Working drafts retain their tracked changes and comments. The technical supplement was exported as a separate clean anonymous copy; the proposal is not included in this release. PDF authoring metadata, annotations, and attachments were removed. Source Git identifiers in supplement provenance paragraphs were withheld because they could link to an author-bearing repository; the source identifiers remain in the private archive. The supplement copy describes the included runner and completed offline reproduction checks. Numerical claims, tables, and substantive interpretation are unchanged. Package file hashes identify the released bytes; they do not replace the provenance of the original source commits. Legitimate author names in scholarly citations remain intact.

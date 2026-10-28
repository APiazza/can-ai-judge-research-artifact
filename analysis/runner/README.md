# ai-reviewer-audit

**An instrument for measuring what an AI reviewer can and cannot see.**

AI systems are increasingly used to evaluate research: reviewing manuscripts, screening proposals, and — inside automated research pipelines — deciding which machine-written work survives to the next round. There is substantial work validating AI that simulates survey respondents, and AI that writes papers. There is very little on AI that *judges*, despite that being the role which gates the other two.

This repository contains the materials and code for measuring it.

---

## The distinction being tested

Expert evaluation arguably splits in two.

**Technical problems** are ones any competent reader agrees about once shown: a table that contradicts the abstract, a citation that does not say what it is cited for, an estimator that does not fit the described data structure. They are settled by looking.

**Taste problems** have to be argued for: whether the paper matters, whether its novelty claim is honest against the literature it itself cites, whether the design can distinguish the proposed mechanism from an obvious alternative. Competent readers can disagree about these with the whole paper in front of them — and yet do not disagree randomly.

The hypothesis is that current models absorb the first kind entirely and do not reach the second **from a single prompt**, however well constructed. The claim is deliberately scoped to one-shot evaluation; iterative human-in-the-loop review is a separate question this instrument does not address.

## How it works

1. **A corpus of fabricated papers.** Short quantitative papers in the organizational-theory and strategy genre. Everything is invented — the data, the results, the tables, the references. No real manuscript, dataset, or review is used anywhere in this project.
2. **A key.** Each paper carries a private record of what was planted: the problem, its kind (technical or taste), its location, and its intended severity. Each paper also contains **planted strengths** — sound elements that should *not* be criticised. Without them, a reviewer who complains about everything scores as discerning.
3. **Human referees.** Experienced reviewers in the same genre write full referee reports on the papers, cold, having seen no key. They then review the key item by item and say whether each planted problem is genuinely a problem and how serious. The first task establishes the human comparison point; the second establishes that the planted problems are real rather than merely asserted by us.
4. **Models, with the prompt as the variable.** The same papers go to models across a ladder of prompt quality — from a bare instruction to review the paper, through a version following a journal's published reviewer guidelines, to a more generous formulation. Prompt quality is the manipulated variable, not a fixed choice, so that a miss cannot be attributed to having asked badly.
5. **Scoring against the key**, by problem kind and prompt rung.

The result of interest is not that models miss things. It is the *shape* of the response across the ladder, and whether that shape differs between the two kinds of problem.

## Repository layout

```
corpus/     the fabricated papers and their keys
prompts/    the prompt ladder
R/          harness and scoring code
results/    run outputs
docs/       protocol, schema, and pre-registered decision rules
```

## Two design constraints enforced in code

**The key is unreachable from a review run.** A model reviewing a paper cannot read the key. This is enforced structurally rather than by convention: a run that could have seen the key is not evidence of anything.

**Prompts name problem *types*, never instances.** Telling a model to check whether a novelty claim is honest is part of the design. Telling it which paper has a dishonest novelty claim hands over the answer.

## A note on publishing the key

Releasing the corpus and its key makes the work reproducible, which matters more to us than the cost. The cost is real, though: once public, these materials may enter future training data, and detection scores on this corpus will stop being interpretable for models trained after its release. Anyone extending this work should treat the public corpus as a development set and hold out freshly authored papers as a test set. Release dates are recorded so that any model's training cutoff can be compared against them.

## Reproducibility

The core runs on open-weight models, so that results can be reproduced without access to a commercial API. Frontier-model results are reported as a dated supplement, since they are not stable over time and not equally accessible.

## Status

Under active development toward a Stage 1 submission to the *Organization Science* special issue on AI-enabled frontiers in organizational science (November 2026). Interfaces and schema should be expected to change.

## Licence

Code is MIT. Corpus materials, keys, schema, and documentation are CC BY 4.0. See `LICENSE`.

## Citation

See `CITATION.cff`.

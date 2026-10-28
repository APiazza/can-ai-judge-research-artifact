# Corpus

Fabricated quantitative papers in the organizational-theory and strategy genre, each with a key.

**Everything is invented** — the data, the analyses, the tables, the references, the authors. No real manuscript, dataset, or review is used anywhere in this project. This is a design choice, not only an ethical one: it is what makes the key possible, since we can only know exactly what is wrong with a paper we wrote.

A consequence worth stating plainly: because no real estimates underlie these papers, planted technical problems are **internally inconsistent** rather than wrong against a true value — an abstract that contradicts its own table, an estimator that does not fit the data structure the paper describes, a robustness claim its own summary does not support. That is sufficient for the problem types under test, and it is a limit on what the instrument can measure.

## Layout

```
papers/   the papers as given to reviewers and models
keys/     what was planted in each: kind, location, intended severity
schema.md the specification governing both
```

## Each key records, per planted item

- what the problem is
- its **kind** — technical or taste
- where it sits in the paper
- how serious it is meant to be
- whether human referees **endorsed** it as a real problem, and at what rate

That last field matters most. A planted item that experienced referees decline to endorse is removed from the key before anything is scored. We do not get to decide unilaterally what counts as a flaw — which is the difference between an instrument and a list of our own opinions, and the respect in which this differs from existing planted-error benchmarks.

## Planted strengths

Every paper also contains sound elements that should **not** be criticised. Without false-alarm opportunities there is no way to distinguish a discerning reviewer from a harsh one: on a test where everything is broken, a reviewer who objects to everything scores perfectly.

## Contamination

See the note in the top-level README. Once public, this corpus may enter training data. Treat it as a development set; hold out freshly authored papers to test models released after the corpus date.

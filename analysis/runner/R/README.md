# Code

The harness: prompt-ladder execution, model runs, and scoring.

Written in R. Reproducibility is a design requirement, not an afterthought — the core runs on open-weight models so results can be reproduced without a commercial API key, with frontier-model results reported as a dated supplement.

## Structural requirement

**The key must be unreachable from a review run.** A function that produces a model review must not be able to read `corpus/keys/`. Enforce this in the code path rather than by convention — a run that *could* have seen the key is not evidence of anything, and "we were careful" is not a control.

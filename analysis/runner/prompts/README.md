# The prompt ladder

Prompt quality is the manipulated variable, not a fixed choice. The point is to close the obvious objection — *you simply did not ask it properly* — before anyone raises it. If a model misses taste problems under the most generous instruction we can write, that is a finding. If it misses them under a lazy one, that is nothing.

Each rung is a versioned template. Runs record which rung, which template version, and which model.

| Rung | What it is | Why it is in the ladder |
|---|---|---|
| `00_bare` | "Review this paper." | Not a fair test — an *ecological* one. This is what a busy person actually does. |
| `01_guidelines` | The same, plus a journal's published reviewer instructions verbatim. | What a conscientious reviewer using AI would paste in. |
| `02_targeted` | Names the kinds of deep problem to look for — significance, honesty of the novelty claim against cited work, whether the design distinguishes the proposed mechanism from alternatives. | Closes the instruction escape hatch. |

## The rule that keeps it fair

**Prompts name problem *types*, never instances.** "Check whether the novelty claim is honest" is legitimate and is the point of rung 2. "The novelty claim in paper 2 does not survive Smith (2019)" hands over the answer and invalidates the run.

## Why rising complaint volume is not the same as discernment

A model pushed hard to hunt for taste problems may start flagging them everywhere, including in papers where the contribution is sound. That is why every paper carries **planted strengths** — sound elements that should not be criticised. Scoring accounts for false alarms as well as hits, so a model that simply complains more does not score as more discerning.

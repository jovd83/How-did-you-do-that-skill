# How it was done: {{title}}

<!-- how-did-you-do-that report v2 -->

| | |
|---|---|
| About | {{about}} |
| AI used | {{ai_used}} |
| Report | Generated {{generated}} by the how-did-you-do-that skill {{skill_version}}. Numbers come from the session logs. Ratings, reasons and summaries are the writer's assessment. |

## 1. Summary

| | |
|---|---|
| Goal | <!-- WRITE: the goal in one sentence --> |
| Outcome | <!-- WRITE: what came out of it, in one sentence --> |
| Verdict | <!-- WRITE: the overall rating from section 10, with the main reason --> |
| Prompts | {{prompt_summary}} |
| Time | {{time_summary}} |
| Model(s) | {{model_summary}} |
| Tokens | {{token_summary}} |
| Cost | {{cost_summary}} |

## 2. The request

**Original prompt**, {{first_prompt_meta}}:

{{first_prompt_block}}

**In plain words:** <!-- WRITE: what was asked, without jargon, in one to three sentences -->

## 3. Follow-up prompts

{{followups_table}}

Kinds: correction, refinement, continue, approval, new scope, question, slash command.

## 4. Setup

{{setup_table}}

## 5. Tokens and cost

{{usage_table}}

{{cost_block}}

**What drove the cost:** <!-- WRITE: one to three sentences, for example a long context re-read on every turn, many sub-agents, or retries -->

## 6. Skills, plugins, MCP servers, sub-agents and hooks

{{extensions_table}}

## 7. Non-AI tools and libraries

{{tools_block}}

**Needed to replicate:** <!-- WRITE: which of these someone must have installed beforehand, and which were incidental -->

## 8. What was done

### By the human

{{human_facts}}

<!-- WRITE: how the human steered the work (asks, corrections, approvals, refusals, interruptions, manual steps), citing prompt numbers -->

### By the AI

{{ai_facts}}

<!-- WRITE: the AI's approach in phases (explore, plan, build, verify, deliver), citing prompt numbers and naming the dead ends -->

### Files created or changed

{{files_table}}

## 9. What was achieved

{{achieved_facts}}

<!-- WRITE: the deliverables, the evidence that they work (tests run, checks passed, the user accepting them), and what was left open -->

## 10. Review

| Criterion | Rating | Evidence |
|---|---|---|
| Goal met | <!-- WRITE --> | <!-- WRITE --> |
| Quality of the result | <!-- WRITE --> | <!-- WRITE --> |
| Verification | <!-- WRITE --> | <!-- WRITE --> |
| Efficiency (time and tokens) | <!-- WRITE --> | <!-- WRITE --> |
| Steering needed | <!-- WRITE --> | <!-- WRITE --> |
| Model and settings fit | <!-- WRITE --> | <!-- WRITE --> |

Ratings: Good, Partly, Poor, Can't tell.

**Overall:** <!-- WRITE: one paragraph -->

**Try next time:** <!-- WRITE: one to three concrete changes, or "Nothing: the setup fit the task." -->

## 11. Replicate it

### What you need

{{prerequisites}}

### Inputs

<!-- WRITE: the files, data, repositories or accounts the work started from, and where to get them -->

### Steps

<!-- WRITE: numbered steps: the setup, which prompts to paste (by number, from appendix B), and any manual steps in between -->

### One-shot prompt

<!-- WRITE: one prompt in a fenced block that folds the corrections in, so a replicator can skip the dead ends -->

### Check the result

<!-- WRITE: how to tell that the replication worked -->

### Watch out for

<!-- WRITE: paths or accounts specific to this machine, secrets, randomness, model or version differences -->

## 12. Appendix

### A. Sessions

{{sessions_table}}

### B. All prompts, word for word

{{all_prompts}}

### C. Timing

{{timing_block}}

### D. Data gaps and provenance

{{provenance_block}}

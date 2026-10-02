# Review guide (section 10)

The review is the part a reviewer reads first and the easiest to get wrong. Aim for an honest
judgment grounded in the logs: not praise, and not a reflexive "a bigger model would have been
better". Each rating names its evidence: prompt numbers, files, commands, counts from the report.

Ratings: **Good**, **Partly**, **Poor**, **Can't tell**. Use "Can't tell" when the logs don't show
enough. That is more useful than a guess.

## The six criteria

### Goal met
Compare the original prompt and later scope changes (section 3) with what was delivered
(section 9).
- Good: everything asked for was delivered, or the user explicitly accepted the result.
- Partly: some parts were delivered, some were dropped, deferred or replaced without the user
  agreeing.
- Poor: the main ask was not delivered, or the session ended with the user still correcting.
- Look at the last prompts: "push it", "thanks" or a new task usually means acceptance; a
  repeated complaint means it wasn't.

### Quality of the result
Judge the deliverable, not the process. Use what is visible: the files written, the last replies,
review comments the user made, follow-up fixes. If you can open the deliverables (they are in the
folder), skim the important ones.

### Verification
Was the result checked before it was called done?
- Good: tests, linters, builds or a validator ran and passed after the last change (look for the
  commands in the timeline), or the user tested it and confirmed.
- Partly: checks ran earlier but not after the final changes, or only some parts were checked.
- Poor: nothing ran; the work was declared done on the AI's word.

### Efficiency (time and tokens)
Set the active time and tokens against the size of the task.
- Signals of waste: long stretches of retries on the same error, the same files read again and
  again, sub-agents doing duplicate work, several context compactions on a modest task, heavy
  reasoning on mechanical steps.
- Signals of a good fit: few prompts, steady progress, tokens dominated by cheap cache reads.
- Don't penalise a big task for being big.

### Steering needed
How much did the human have to correct the AI? Count corrections (not refinements or new ideas),
interruptions, permission refusals and repeated asks.
- Good: the human only gave direction and approvals.
- Partly: a few corrections, each fixed quickly.
- Poor: the human repeatedly had to point out the same kind of mistake, or took over.

### Model and settings fit
Judge the model, reasoning effort, mode and speed against the task. Raise an alternative only when
it plausibly would have changed the outcome. Check current facts before any claim about a model's
price or abilities (see `pricing-sources.md`); model lineups and prices change constantly.

- **Bigger vs smaller model.**
  - A smaller model would have done: the work was mechanical (file edits, reformatting,
    boilerplate), there were few corrections, and reasoning was barely used.
    Impact: lower cost, often faster, similar result.
  - A bigger model was warranted or would have helped: many retries, mistakes a stronger model
    would have caught, deep reasoning or large-context synthesis. Impact: fewer dead ends, higher
    first-try quality, more cost.
- **More vs less reasoning effort.**
  - More would have helped when the AI made avoidable logic mistakes or the user had to fix flawed
    plans while effort was low.
  - Less was fine when high effort ran on trivial turns: output tokens and latency for no gain.
  - Evidence: the effort distribution, thinking tokens, and where the corrections fell.
- **Mode.**
  - Plan mode or approval gates are worth it on risky or ambiguous work; on routine work they only
    add round-trips.
  - Auto or bypass modes on destructive work deserve a remark.
- **Speed.** Fast output modes change latency, not quality. Mention them only if the session was
  long and interactive, with the user clearly waiting.
- **Provider.** Stay within the tool and provider that was used unless the user asks for a
  comparison. The review is about their setup, not a vendor pitch.

If the setup was well matched, say so in one line. A short, honest "this fit the task" is more
credible than four paragraphs of hedged alternatives.

## Overall and "Try next time"

The overall paragraph weighs the six ratings. Goal met and quality count most; efficiency counts
least. "Try next time" gives one to three concrete changes a person could actually make: a prompt
that states the acceptance check up front, a smaller model for the bulk edits, a test run before
"done". Frame them as advice for next time, not as blame.

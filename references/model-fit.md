# Model-fit critique guidance

The "was this the right setup?" section is the part colleagues find most valuable and the
easiest to get wrong. The goal is an honest, evidence-grounded judgment — not praise, not a
generic "you could always use a bigger model". Raise a direction **only when it plausibly
would have changed the outcome**.

## Always check current facts first

Before any cost number or "model X would have been better" claim, consult the **`claude-api`
skill** for current model IDs, capabilities, pricing, and reasoning options. Model lineups
and prices change; do not answer from memory. Quote the pricing date/source in the appendix.

## The four axes

Evaluate each only if the evidence makes it relevant.

### 1. Bigger vs smaller model
- **Smaller would have sufficed** when: the task was mechanical/repetitive (file edits,
  reformatting, boilerplate), few or no thinking blocks were needed, and the assistant
  rarely backtracked. Impact: lower cost, often faster, similar result.
- **Bigger was warranted / would have helped** when: there were many retries, the assistant
  produced wrong answers a smaller model wouldn't have caught, the task needed deep
  reasoning or large-context synthesis. Impact: fewer dead-ends, higher first-try quality,
  more cost.
- Use `tokens_by_model` and the retry pattern in the prompts as evidence.

### 2. More vs less reasoning (extended thinking)
- **More reasoning would have helped** when: the assistant made avoidable logical mistakes,
  the user had to correct flawed plans, and few/no thinking blocks were present on hard
  turns. Impact: better plans, fewer corrections, more output tokens.
- **Less reasoning was fine** when: heavy thinking appears on trivial turns — wasted output
  tokens and latency for no quality gain.
- Evidence: `reasoning.thinking_blocks` vs how hard the turns actually were.

### 3. Faster vs slower (fast mode)
- Fast mode (`speed: "fast"`) is the same Opus model with faster output, not a downgrade.
  Note it as a latency/throughput choice, not a quality one.
- **Faster would have helped** when the session was long and interactive and the user was
  clearly waiting (many short turns, long wall-clock).
- Rarely a quality issue — usually frame as time/UX, and only mention if the session
  pattern suggests waiting was a real cost.

### 4. Right provider/model family
- Stay within the provider that was actually used unless the user asks to compare across
  providers. The critique is about *their* setup, not a vendor pitch.

## Turning tokens into a cost estimate

Pricing is per million tokens and differs by type and model. Compute per model:

```
cost = (input_tokens        / 1e6) * input_price
     + (output_tokens       / 1e6) * output_price
     + (cache_creation      / 1e6) * cache_write_price
     + (cache_read          / 1e6) * cache_read_price
```

- Cache **read** is much cheaper than fresh input; cache **write** is slightly more than
  input. Using one blended rate badly distorts the result — that's why the extractor keeps
  the four types separate.
- Sum across models for the session total.
- **Label the result**: *exact* (you have authoritative current prices for every model
  present), *partial* (prices for some models/types only), or *estimated* (prices may be
  stale). Never present an unlabeled number as fact.
- If the user has the `token-usage-cost-report` skill and wants a rigorous, provenance-backed
  cost artifact, point them to it — this skill's estimate is a convenience figure.

## Tone

Frame critique as "here's what you could try next time", grounded in what the logs show.
If the setup was well-matched — appropriate model, reasoning used where it mattered, no
wasteful pattern — say that plainly in one or two lines and stop. A short honest "this was a
good fit" is more credible than four paragraphs of hedged alternatives.

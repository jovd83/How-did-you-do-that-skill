# Cost: reported figures, live prices and prices.json

Prices change often, so this skill never hardcodes them. The order of preference:

1. **Reported by the tool.** Claude Code writes its own running cost into the transcript
   (`cost-state` records). When `usage.reported_cost.complete` is true in `metrics.json`, that
   figure covers all selected work and is the cost; no price lookup is needed. It also covers
   background calls (titles, summaries) that the token table doesn't show.
2. **Estimated from current list prices.** In every other case: identify the provider of each
   model in `usage.rows`, fetch its current pricing page, and write `prices.json`. The renderer
   does the arithmetic. When a partial reported figure exists, the report shows it as a
   cross-check.

For an auditable figure (a budget, an invoice check, a comparison across repositories), point the
user to the `token-usage-cost-report` skill, if installed. It only reports costs it can trace to
runtime evidence and official pricing pages.

## Model id → provider → where to look

| Model id pattern | Provider | Current prices |
|---|---|---|
| `claude-*`, `anthropic.*`, `us.anthropic.*` | Anthropic | https://platform.claude.com/docs/en/about-claude/pricing. It lists the cache-write and cache-read rates, which the `claude-api` skill's model table lacks; those are the biggest cost lines. The skill is only a quick cross-check for input and output prices |
| `gpt-*`, `o1*`, `o3*`, `o4*`, `codex-*`, `chatgpt-*` | OpenAI | https://developers.openai.com/api/docs/pricing (the older platform.openai.com/docs/pricing redirects there across hosts, which a fetch tool may not follow) |
| `gemini-*` | Google | https://ai.google.dev/gemini-api/docs/pricing (Vertex AI: https://cloud.google.com/vertex-ai/generative-ai/pricing) |
| `mistral-*`, `magistral-*`, `codestral-*` | Mistral | https://mistral.ai/pricing |
| `grok-*` | xAI | https://docs.x.ai/docs/models |
| `deepseek-*` | DeepSeek | https://api-docs.deepseek.com/quick_start/pricing |
| `llama-*`, other hosted open models | the host | the host's own pricing page (Bedrock, Together, Groq, Fireworks…) |
| any model used through GitHub Copilot | GitHub | premium requests, see below |

If a model id matches nothing, search for `"<model id>" API pricing per million tokens` and cite
what you find. Don't price it from a sibling model.

**Subscriptions make every price-based figure notional.** Claude Code on a Pro or Max plan, Codex on
a ChatGPT plan and Copilot on a monthly allowance are not billed per token. The report states this
under the cost, and the extractor lists what the logs show about the plan in
`usage.billing_hints` (Claude Code rate-limit events; Codex rate-limit percentages sit in its
`token_count` records). Say in the cost basis that the number is the API equivalent.

## What to read off the pricing page

All rates per **million tokens**, per model:

- `input`: fresh input tokens
- `output`: generated tokens (thinking or reasoning tokens are billed as output and are already
  included in the output count)
- `cache_read`: cached input. Usually about a tenth of the input price. On long agent sessions
  this is the largest token count, so getting this rate right matters more than any other.
- `cache_write_5m` and `cache_write_1h` (Anthropic): writes to the 5-minute cache cost more than
  input, and writes to the 1-hour cache cost more again. Claude Code uses both, and the metrics
  keep them apart. Use `cache_write` when a provider has a single rate.

Note any tier you assumed: long-context surcharges, batch or flex discounts, regional pricing.

## prices.json

```json
{
  "source": "https://platform.claude.com/docs/en/about-claude/pricing",
  "fetched": "2026-10-01",
  "currency": "USD",
  "models": {
    "claude-opus-5-5": {"input": 0, "output": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0},
    "gpt-5.6-sol": {"input": 0, "output": 0, "cache_read": 0}
  }
}
```

The zeros are placeholders: fill in the real numbers you fetched. Keys must match the model ids in
`metrics.json` (a date suffix or `[1m]` suffix is matched loosely). When models come from different
pages, put the main page in `source` and mention the others in the report's cost basis. The
renderer labels the result "estimate", or "partial estimate" when a model or token type has no
price.

## GitHub Copilot: premium requests, not tokens

Copilot plans bill **premium requests** against a monthly allowance. Each prompt in chat, agent or
edit mode costs one request times the model's multiplier; some models have a multiplier of 0
(included). Requests beyond the allowance are billed at a fixed price per premium request.

- VS Code often logs the multiplier with each response (for example "Claude Sonnet 4 • 1x"); the
  extractor picks it up.
- When it is missing, fetch the current multipliers and the overage price from GitHub's docs. Start
  at https://docs.github.com/en/copilot/concepts/billing/copilot-requests; if the page has moved,
  search for "GitHub Copilot premium requests model multipliers". Then add them to `prices.json`:

```json
"models": {
  "claude-sonnet-4": {"premium_request_multiplier": 1, "premium_request_usd": 0},
  "gpt-4.1": {"premium_request_multiplier": 0, "premium_request_usd": 0}
}
```

Again, the zeros are placeholders for the numbers you fetched. The report shows premium requests
used and, if over the allowance, their price. Token counts for Copilot are usually absent; that's
expected and the report says so.

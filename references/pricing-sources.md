# Pricing sources (look these up live)

Model prices change often, so this skill **never hardcodes them**. When the report needs a
cost figure, identify the provider(s) of the model IDs actually present in the session, then
**fetch the current pricing table** from that provider before computing anything. Use
`WebFetch`/`WebSearch` for the live page; fall back to the provider's docs if the marketing
page is unparseable. Always record the source URL and the date you fetched it in the report's
cost section, and label the number `exact` / `partial` / `estimated` accordingly.

## Map model IDs to a provider

| Model id pattern | Provider | Where to get current prices |
|---|---|---|
| `claude-*`, `anthropic.*`, `us.anthropic.*` | **Anthropic** | Prefer the `claude-api` skill (fast, authoritative for Claude). Else: https://platform.claude.com/docs/en/about-claude/pricing (API) and https://claude.com/pricing (plans) |
| `gpt-*`, `o1*`, `o3*`, `o4*`, `chatgpt-*` | **OpenAI** | https://openai.com/api/pricing/ and https://platform.openai.com/docs/pricing |
| `gemini-*`, `models/gemini-*` | **Google (Gemini API)** | https://ai.google.dev/gemini-api/docs/pricing and https://cloud.google.com/vertex-ai/generative-ai/pricing |
| `mistral-*`, `mixtral-*`, `magistral-*` | **Mistral** | https://mistral.ai/pricing |
| `llama-*`, `meta-*` (hosted) | depends on host | Check the actual host (Bedrock / Together / Groq / Fireworks) pricing page |
| `command-*`, `cohere.*` | **Cohere** | https://cohere.com/pricing |
| `deepseek-*` | **DeepSeek** | https://api-docs.deepseek.com/quick_start/pricing |
| `grok-*`, `xai-*` | **xAI** | https://docs.x.ai/docs/models |

If a model id doesn't match any pattern, search for `"<model-id>" API pricing per million
tokens` and cite what you find — don't guess from a sibling model.

## What to pull from each table

Pricing is per **million tokens** and almost always splits by direction and cache state. Pull
every rate that applies to the token types the extractor reported:

- **Input** (fresh prompt tokens)
- **Output** (generated tokens)
- **Cache write / cache creation** (Anthropic: ~1.25× input for 5-min, more for 1-h)
- **Cache read / cached input** (Anthropic & OpenAI & Gemini all price this far below fresh
  input — often 0.1×). This usually dominates long agent sessions, so getting it right matters
  more than any other rate.

Watch for **per-model tiers** (e.g. Gemini context-length tiers, OpenAI batch/flex discounts,
Anthropic long-context surcharges). Note the tier you assumed.

## Computing the estimate

Per model present in the session:

```
cost = input/1e6      * input_price
     + output/1e6     * output_price
     + cache_write/1e6 * cache_write_price
     + cache_read/1e6  * cache_read_price
```

Sum across models for the session total. A session that spans providers (e.g. a Claude Code
run that also called an OpenAI model via MCP) needs each provider priced from its own table —
do not blend rates across providers.

## Labels

- **exact** — you have current authoritative per-type prices for every model present.
- **partial** — you have prices for some models/types but not all (say which are missing).
- **estimated** — prices may be stale or inferred; state why.

If the user wants a rigorous, provenance-backed cost artifact rather than this convenience
figure, point them to the `token-usage-cost-report` skill.

This file is for the story's **estimate**. For an auditable figure, the `token-usage-cost-report` skill keeps its own, stricter pricing rules: official provider pages only, and no estimate labelled as exact.

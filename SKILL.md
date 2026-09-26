---
name: how-did-you-do-that
description: "Use when the user wants to show a colleague (or themselves) how they got an AI result and answer \"how did you do that\" — to document their prompting process, do a retro on an AI session, or respond to questions like \"explain how I built this with AI\", \"write up my Claude session\", \"what prompts did I use\", \"how much did this cost in tokens\", \"which model/skills/tools/MCP did I use\", or \"was this the right model for the job\". It examines the logged session transcripts for a folder (Claude Code JSONL under ~/.claude/projects, best-effort for other tools) and produces one Markdown file: a colleague-friendly narrative plus a full technical appendix (prompts and why each was sent, model + reasoning + speed, token breakdown by type, tools/skills/MCP/sub-agents, elapsed vs active time) and a model-fit critique. Trigger it even when the user only gestures at \"explain what I did with AI here\" without naming transcripts or tokens."
license: MIT
metadata:
  version: "1.1.1"
  maturity: "stable"
  author: "jovd83"
  dispatcher-category: "documentation"
  dispatcher-layer: "analysis"
  dispatcher-lifecycle: "active"
  dispatcher-risk: "low"
  dispatcher-writes-files: "true"
  dispatcher-capabilities: "session-reconstruction, prompt-history, token-accounting, model-fit-critique, ai-usage-explainer, transcript-analysis"
  dispatcher-accepted-intents: "explain_ai_session, document_prompting_process, account_session_tokens, critique_model_choice, write_how_did_you_do_that"
---

# How did you do that

## What this skill is for

You do something impressive with AI, a colleague asks **"how did you do that?"**, and
you want a clear artifact you can hand them instead of re-explaining from memory. This
skill reconstructs the real session from its logs and writes a single Markdown file that
answers: what was the opening prompt, which follow-ups and *why*, where it ran, which
model at what reasoning/speed, how many tokens of each type, which tools/skills/MCP, how
long it actually took — and whether the model choice was right.

The output has two halves in one file: a **narrative** anyone can read, and a **technical
appendix** with every metric tabulated. Both come from the same evidence.

## The golden rule: measure, don't guess

The whole value of this artifact is that the numbers are *real*. Token counts, model IDs,
timings, and tool counts come from the logs — never estimate them from the conversation in
front of you. The `extract_session.py` script does this deterministically. Your job is to
**interpret** what the script can't: why each prompt was sent, what it changed, and whether
the setup fit the task. If a number isn't in the evidence, say so rather than inventing it.

## Workflow

### 1. Identify the target folder

This is the folder where the work happened (the project/workspace the user is asking
about). Default to the current working directory if the user is clearly asking about
"this" work. If ambiguous, ask which folder.

### 2. Run the extractor

```bash
python scripts/extract_session.py "<target-folder>" --out "<target-folder>/session-metrics.json"
```

This locates the Claude Code transcripts for that folder (it reproduces Claude Code's
`~/.claude/projects/<encoded-path>/` naming), parses **every** session for the folder, and
merges them into one metrics bundle. It prints a summary and writes the full JSON.

If the folder isn't where Claude Code ran, point it directly at transcripts:

```bash
python scripts/extract_session.py --transcripts "<dir-or-glob-of-jsonl>" --out metrics.json
```

The JSON `warnings` array tells you if no transcripts were found, or if non-Claude-Code
logs (Codex, Cursor, Gemini/antigravity, generic chat logs) were detected in the folder.

### 3. Read the evidence

Read the emitted JSON in full. Then **read the relevant transcript(s)** — the JSON gives
you the prompts and metrics, but to explain *why* a prompt was sent and *what it altered*
you need to see the assistant's responses between prompts. Skim the assistant turns that
follow each human prompt; that is where the "reason" and "what changed" come from.

For best-effort other-tool logs, open the files listed under `other_tool_logs` and pull
out whatever you can (usually prompts and timestamps; rarely tokens/model). Be explicit in
the report about what was and wasn't available from those sources.

### 4. Reconstruct the prompt story

For each human prompt in `prompts.list` (they're in chronological order across all merged
sessions), determine:

- **What was asked** — paraphrase the intent, don't just quote 500 words.
- **Why it was sent** — was it the opening ask? a correction? a refinement? a "continue"?
  a reaction to something the assistant got wrong or a new idea? The text plus the
  preceding assistant turn tells you.
- **What it altered** — what changed in the result because of this prompt.

Short prompts like "continue", "retry", "go on" are real and meaningful — they usually mean
"the previous direction was right, keep going" or "that failed, try again". Group runs of
them rather than listing each separately, and explain what the user was steering.

### 5. Do the model-fit critique

Using the model(s), `speed_distribution`, `reasoning.thinking_blocks`, token totals, and
how hard the task actually was, judge whether the setup fit the work. **Only raise an
alternative when it genuinely applies** — don't manufacture all four directions.

Get current facts before making cost or "better model" claims — never rely on memory for
prices or model IDs, they change constantly:

- For **Claude/Anthropic** models, consult the `claude-api` skill.
- For **any other provider** in the session (OpenAI, Gemini, Mistral, …), look up that
  provider's **live pricing table** — `references/pricing-sources.md` has the model-id→provider
  map and the canonical URLs to fetch with WebFetch/WebSearch. Price each model from its own
  provider's table; one session can span providers. Cite the source URL and fetch date.

See `references/model-fit.md` for how to reason about each axis (bigger/smaller model, more/less
reasoning, faster/slower) and how to turn token counts into a labelled cost estimate.

### 6. Write the Markdown file

Write to `<target-folder>/how-did-you-do-that.md` (or a name the user prefers). Follow the
template in `references/report-template.md` exactly — narrative first, technical appendix
second. Fill the facts table from the JSON; write the narrative from the transcripts.

Keep the narrative honest and specific: real prompt counts, real hours, real dead-ends.
A colleague learns more from "it took 3 retries to get the regex right" than from a glossy
summary. Convert raw seconds to human units (e.g. "≈3.2 h of active work spread over 5
days"). Distinguish **wall-clock span** (first to last event) from **active engaged time**
(the script's gap-filtered estimate) — they're often very different and that difference is
itself interesting.

### 7. Tell the user where it is

Report the file path and give a one-paragraph summary of the headline facts (model, prompts,
tokens, time). Offer to tweak depth or audience (more technical, more story, shorter).

## Notes on the data

- **Where it ran**: `environment.entrypoints` — `claude-vscode` = the VS Code / Claude Code
  IDE extension; `cli` = terminal; other values map to desktop/web. Combine with
  `claude_code_versions` for the exact tool version.
- **Reasoning**: Claude Code doesn't log the exact thinking budget. Presence and volume of
  `thinking` blocks (`reasoning.thinking_blocks`, `thinking_chars`) is the proxy — report it
  as "extended reasoning was used on N turns", not a fabricated budget number.
- **Speed**: `speed: "standard"` vs `"fast"` distinguishes normal vs fast-mode Opus.
- **Tokens**: report all four types separately — `input`, `output`, `cache_creation`,
  `cache_read`. Cache-read tokens are usually the largest and cheapest; lumping them into
  one "total" is misleading, which is why the appendix breaks them out.
- **Skills vs MCP vs tools**: `skills_invoked` (the `Skill` tool), `mcp_tools` (`mcp__*`
  names), and `tool_calls` (built-ins like Bash/Read/Edit) are tracked separately because
  colleagues usually want to know which *skills* were used, distinct from raw tool calls.
- **Multiple models in one bundle**: a session often spans models (e.g. a cheap model for
  routing, Opus for the hard part). `tokens_by_model` shows the split; explain it rather
  than averaging it away.

## When there's nothing to report

If no transcripts are found and no other-tool logs exist, don't invent a story. Tell the
user plainly that no AI session logs were found for that folder, show the path the script
searched, and ask whether the work happened elsewhere (different folder, a tool that
doesn't keep logs, or logs that were cleared).

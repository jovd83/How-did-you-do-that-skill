# How Did You Do That — AI session explainer skill

[![version](https://img.shields.io/badge/version-1.1.2-blue)](CHANGELOG.md)
[![status](https://img.shields.io/badge/status-stable-3fb950)](SKILL.md)
[![category](https://img.shields.io/badge/category-documentation-0a7ea4)](SKILL.md)
[![validation](https://img.shields.io/badge/validation-GitHub%20Actions-2088ff)](.github/workflows/validate.yml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=flat&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/jovd83)

`how-did-you-do-that` reconstructs a finished AI working session from its logs and writes a
single shareable Markdown file that answers the question colleagues keep asking: **"how did
you do that?"** — the prompts you used and *why*, where it ran, which model at what
reasoning and speed, a token breakdown by type, the tools/skills/MCP/sub-agents involved,
how long it really took, and whether the model choice fit the job.

The output has two halves in one file: a **narrative** anyone can read, and a **technical
appendix** with every metric tabulated. Every number is measured from the logs — never
estimated — so the artifact is something you can actually stand behind.

## What This Skill Does

- Locates the **Claude Code transcripts** for a folder (`~/.claude/projects/<encoded-path>/`)
  and merges **all** sessions into one story; best-effort detection of other tool logs
  (Codex, Cursor, Gemini/antigravity, generic chat logs) found inside the folder.
- Extracts, deterministically: the real human prompts (filtering out injected
  system-reminders and sub-agent notifications), model IDs and per-model token splits, the
  four token types (input / output / cache-write / cache-read), speed (standard vs fast),
  reasoning via thinking-block counts, entrypoint/version, tool/skill/MCP/sub-agent counts,
  and **wall-clock span vs active engaged time**.
- Reconstructs the **prompt-by-prompt story** (why each prompt was sent, what it altered),
  collapsing runs of "continue"/"retry".
- Produces a **model-fit critique** — was the model/reasoning/speed right, and what a
  bigger/smaller/faster/slower alternative would have meant — raising only the angles that
  genuinely apply.
- Writes one Markdown file: colleague narrative + technical appendix.

## When To Use It

Use it whenever you want to explain or document how an AI result was achieved — a colleague
asks "how did you do that", you want a retro of a Claude session, you need to report token
spend or model choice to a team lead, or you want a reproducible record of your prompting
process. It triggers even when you only gesture at "explain what I did with AI here" without
naming transcripts or tokens.

## What This Skill Does Not Do

- It does **not** estimate token counts, timings, or model IDs from memory — if a number
  isn't in the logs it says so. For a rigorous, provenance-backed cost artifact, use the
  `token-usage-cost-report` skill instead.
- It does **not** analyze your project's source code for runtime LLM usage — it explains the
  *session you ran*, not what the code does.
- It is **not** a live monitor — it works from completed session transcripts.
- It does **not** fetch current model pricing itself; it defers to the `claude-api` skill for
  authoritative prices and model facts.

## Installation

Install with the [`skills` CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add jovd83/How-did-you-do-that-skill
```

The only runtime dependency is **Python 3** (standard library only — no packages to install).

## Usage

Ask naturally, e.g. *"write up how I did this with AI for my colleague"*, or run the
extractor directly:

```bash
python scripts/extract_session.py "c:/path/to/project" --out "c:/path/to/project/session-metrics.json"
```

Then the skill reads that JSON plus the transcripts and writes
`how-did-you-do-that.md` into the target folder. See [SKILL.md](SKILL.md) for the full
workflow and [references/report-template.md](references/report-template.md) for the exact
output structure.

## License

MIT — see [LICENSE](LICENSE).

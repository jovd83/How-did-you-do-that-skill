# How Did You Do That

[![version](https://img.shields.io/badge/version-2.0.0-blue)](CHANGELOG.md)
[![status](https://img.shields.io/badge/status-stable-3fb950)](SKILL.md)
[![category](https://img.shields.io/badge/category-documentation-0a7ea4)](SKILL.md)
[![validation](https://img.shields.io/badge/validation-GitHub%20Actions-2088ff)](.github/workflows/validate.yml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=flat&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/jovd83)

`how-did-you-do-that` reads the logs of an AI coding session (Claude Code, GitHub Copilot or Codex) and writes a
report that lets someone review how well the task was done, or replicate it on another computer. Every report has
the same 12 sections, so reports about different tasks, people and tools can be compared side by side.

## What This Skill Does

"How did you do that?" has two honest answers, and they need different things. A reviewer wants to know whether
the work was any good: was the goal met, was it checked, how much did the human have to correct, what did it cost.
A replicator wants a recipe: which tool, model and settings, which skills and programs, which prompts in which
order. Both answers live in the session logs, and memory is a poor substitute for them.

The skill splits the work between scripts and the model. `extract_session.py` measures everything that can be
measured: prompts, models, effort, mode, context, tokens per model and type, cost, skills, plugins, MCP servers,
sub-agents, hooks, shell programs, installed packages, files written, commits, errors and time.
`render_report.py` copies those numbers into a fixed template. The model writes only what needs judgement: why
each prompt was sent, how the work went, the review ratings and the replication steps. A `--check` pass then
refuses the report until every section is present and filled.

| Report section | What it holds |
|---|---|
| 1. Summary | Goal, outcome, verdict, prompts, time, models, tokens, cost |
| 2. The request | The original prompt, word for word, and in plain words |
| 3. Follow-up prompts | Each prompt with its kind, why it was sent and what it changed |
| 4. Setup | Tool and version, model, context window and peak use, mode, reasoning effort, instruction files |
| 5. Tokens and cost | Per model and per scope (main or sub-agent), with the cost basis stated |
| 6. Skills, plugins, MCP servers, sub-agents and hooks | What was used, how often, and for what |
| 7. Non-AI tools and libraries | Programs run, packages installed, libraries imported, web lookups |
| 8. What was done | The human's steering and the AI's approach, plus the files changed |
| 9. What was achieved | Deliverables, the evidence they work, what was left open |
| 10. Review | Six criteria rated Good, Partly, Poor or Can't tell, each with evidence |
| 11. Replicate it | Checklist, inputs, steps, a one-shot prompt, how to check, what to watch out for |
| 12. Appendix | Sessions, every prompt word for word, timing, data gaps and provenance |

Details that make the numbers trustworthy:

- Claude Code writes one API response as several log records that repeat the same usage. Counting each record
  overstates tokens about threefold, so the extractor counts each message once.
- Sub-agent transcripts are counted as their own rows.
- When Claude Code logged its own cost and that figure covers the whole session, the report uses it. Otherwise the
  cost is computed from a price table fetched at run time, and the report names the source and date.
- Likely secrets in prompt text are masked before anything is written.

## What This Skill Does Not Do

- **It does not produce an auditable cost statement.** Its cost figure serves the story. For budgets, invoices or
  cost comparisons across repositories, use `token-usage-cost-report`, which only reports what it can trace to
  runtime evidence and official pricing.
- **It does not analyse the LLM calls your code makes.** It explains the session in which the work was done, not
  what the software does at runtime.
- **It does not read logs that are not on this computer.** That rules out the GitHub Copilot coding agent (its
  logs live on the pull request), claude.ai or ChatGPT web chats, and other people's machines. Copilot and Codex
  support is best effort, because their log formats are undocumented and change.
- **It does not guess.** Where the logs are silent, for example on token counts in Copilot Chat or the exact
  thinking budget anywhere, the report says "Not recorded in the logs".
- **It does not vet the report for leaks.** Prompts are quoted word for word with likely secrets masked; scan the
  report with `leak-canary` before sharing it outside the team.
- **It is not a live monitor.** It works from logs after the fact.

## When To Use It

Use it when:

- a colleague asks "how did you do that?" about something built with an AI assistant
- a team lead wants to know whether an agent run was done well, or whether Opus was the right model for it
- you want to redo a piece of AI work on another computer, or hand the recipe to someone else
- you need the prompts, model, settings, skills, tokens or cost of a past session
- you want a retro on an agent session, including the dead ends and retries

It triggers on phrasing like "write up this AI session", "what prompts did I use", "which model or settings did it
use", "how much did this cost" or "I want to redo this on my work laptop", even when nobody mentions logs. For an
audited cost figure, use `token-usage-cost-report` instead.

## Repository Layout

```
how-did-you-do-that/
├── SKILL.md                      # workflow: scope, extract, price, render, read, write, check
├── assets/
│   └── report-template.md        # the fixed 12-section report template
├── references/
│   ├── review-guide.md           # how to rate the six review criteria and judge model fit
│   ├── pricing-sources.md        # reported cost vs live prices, prices.json, Copilot premium requests
│   └── log-formats.md            # where Claude Code, Copilot and Codex log what, and the gotchas
├── scripts/
│   ├── extract_session.py        # finds and measures the sessions for a folder (stdlib only)
│   ├── render_report.py          # fills the template from the metrics; --check enforces the structure
│   └── validate_skill.py         # repository validation used in CI
├── tests/
│   └── test_scripts.py           # unit tests on synthetic Claude Code, Copilot and Codex logs
└── evals/evals.json              # 3 eval cases: review, replicate, ask-the-scope-first
```

## Installation

```bash
npx skills add jovd83/how-did-you-do-that
```

Manual alternative:

```bash
git clone https://github.com/jovd83/how-did-you-do-that.git
```

Then place the repository folder, named `how-did-you-do-that`, where your agent looks for local skills:
`~/.agents/skills/`, `~/.claude/skills/`, `~/.cursor/skills/`, or another IDE-specific directory. The skill needs
`SKILL.md`, `assets/`, `references/` and `scripts/`; `README.md`, `CHANGELOG.md`, `LICENSE`, `tests/`, `evals/`
and `.github/` can stay behind.

The only dependency is Python 3.8 or later, standard library only. The agent running the skill needs a shell, and
a web fetch tool when the cost has to be priced from a live price table.

## Usage

Ask in plain words, for example *"write up how I built this with AI for my team lead"*. The skill first lists the
sessions it found and asks which ones to cover and where to save the report, unless you already said. The default
location is the project root.

The scripts also work on their own:

```bash
# which sessions exist for a folder
python scripts/extract_session.py "C:/path/to/project" --list

# measure the chosen ones (or --since/--until, --latest N; nothing means all)
python scripts/extract_session.py "C:/path/to/project" --session 22d20d09 --out work/metrics.json

# fill the template, then check the finished report
python scripts/render_report.py work/metrics.json --out how-did-you-do-that-2026-10-01.md [--prices work/prices.json]
python scripts/render_report.py --check how-did-you-do-that-2026-10-01.md
```

Logs in unusual places can be passed directly with `--transcripts <file, folder or glob>`.

## Output Contract

One Markdown file, by default `<project>/how-did-you-do-that-<YYYY-MM-DD>.md`, with the 12 numbered sections
above in that order. `render_report.py --check` passes only when every heading is present and in order and no
`<!-- WRITE -->` slot is left. When no session logs exist for the folder or period, the report still renders and
states that no AI was used, as far as the logs show.

The extractor also writes `metrics.json` (schema `how-did-you-do-that/metrics@2`) and `metrics.timeline.md`, a
prompt-by-prompt digest. Both go to a work folder, not into the project.

## Validation

```bash
python -m unittest discover -s tests -v
python scripts/validate_skill.py .
```

The tests build synthetic logs for all three tools and check, among other things, that:

- repeated usage records count once and sub-agent usage gets its own row
- task notifications are not counted as prompts, while slash commands are
- secrets are masked
- Copilot's edit-log format replays correctly and premium-request multipliers are read
- Codex running totals become the right token split
- session selection by id, period and recency works
- a report with an unfilled slot or a missing section fails the check, and a no-AI report passes

## Evaluation Strategy

`evals/evals.json` has three cases run with the skill-creator workflow against the previous version:

1. A review of a Claude Code session with sub-agents
2. A replication write-up of a Codex session
3. A vague request in a folder with several sessions, where the right behaviour is to ask before writing

Their assertions are checked by script: structure check passes, sub-agent rows present, output tokens match the
deduplicated total, cost basis stated, all six review criteria rated, scope question asked. Narrative quality is
judged by a person in the review viewer.

## Optional Integrations

- `claude-api`: the fast source for current Claude prices when the cost has to be estimated.
- `token-usage-cost-report`: hand off when the user needs an auditable cost figure.
- `leak-canary`: scan the finished report before it leaves the team.

## Contributing

Edit in this repository, run the tests, then copy the skill files to `~/.agents/skills/how-did-you-do-that/`. The
installed copy is downstream and should never be edited directly.

## License

MIT — see [LICENSE](LICENSE).

# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-10-01

The report now serves two purposes, reviewing how well an AI task was done and replicating it elsewhere, and always has the same structure.

### Changed
- **Breaking:** the report follows a fixed 12-section template (`assets/report-template.md`):
  1. summary
  2. request
  3. follow-up prompts
  4. setup
  5. tokens and cost
  6. skills, plugins, MCP servers, sub-agents and hooks
  7. non-AI tools and libraries
  8. what was done
  9. what was achieved
  10. review scorecard
  11. replication steps
  12. appendix

  Missing data is written as "Not recorded in the logs" instead of dropping rows. The old narrative-plus-appendix layout is gone.
- `SKILL.md` workflow:
  - Settle the scope first: list the sessions, and ask which ones (`--session`, `--since`/`--until`, `--latest`, or all) and where to save the report, suggesting the project root.
  - Then extract, price only if needed, render, read the timeline, fill the slots, and run `--check`.
- `extract_session.py` rewritten (metrics schema `how-did-you-do-that/metrics@2`). It now records:
  - effort, permission mode, plan and auto mode, thinking tokens, peak context and compactions, and the context window (logged or inferred)
  - the instruction files and hooks that were loaded, skill sources and versions, MCP servers and plugins
  - programs run, packages installed, libraries imported by written code, web lookups
  - files written, commits, pull requests
  - tool errors, permission refusals, interruptions, and files edited outside the AI
  - a per-prompt timeline digest (`metrics.timeline.md`), so the model no longer reads multi-megabyte transcripts
- Human prompts are recognised by the `origin` field where the log has it.
- Cost: Claude Code's own cost figure is used when it covers all the selected work. Otherwise the cost is estimated from a `prices.json` the agent builds from live price pages, and the renderer does the arithmetic. 1-hour and 5-minute cache writes are priced separately.
- `references/model-fit.md` became `references/review-guide.md`, which covers all six review criteria.
- `references/pricing-sources.md` sends Claude prices to the pricing page (the `claude-api` skill's table lacks cache rates) and uses the current OpenAI pricing URL.
- The SKILL.md description triggers on review and replication requests.

### Added
- `scripts/render_report.py`: fills the template from the metrics, and `--check` refuses a report with a missing or reordered section or an unfilled slot.
- GitHub Copilot support, best effort: VS Code Copilot Chat sessions (including the newer edit-log `.jsonl` format), Copilot CLI logs, and cost as premium requests × model multiplier.
- Codex support, best effort, read from `~/.codex/sessions` and matched on the session's working folder. It was previously looked for inside the project folder, where it never is.
  - Tokens are split per model exactly, from the difference between Codex's running totals, so a session that switched models is priced correctly.
  - Sessions Codex starts itself (automatic reviews, helpers) are folded into their parent as sub-agents instead of showing up as the user's sessions and prompts.
  - Pasted-text prompts are read from the attachment file, so the original prompt is the real one.
- Masking of likely secrets in prompt text.
- Files written through shell commands (redirections, `sed -i`, `tee`, `cp`, `mv`, PowerShell writers) are counted next to the edit-tool writes, and spellings of one path are merged.
- The timeline digest shows the AI's progress messages, the questions it asked the human with the answers, error messages, and local times.
- Programs are checked against the PATH, so folder names and shell functions no longer pass as programs, and `python -m` modules are listed separately.
- The cost section says that price-based figures are API equivalents on a subscription plan, and says what the log shows about the plan.
- A no-AI report: when no logs exist for the folder or period, the report states that no AI was used.
- `references/log-formats.md`, `tests/test_scripts.py` (unit tests on synthetic logs) and a test step in CI.
- Three new evals: review, replicate, and ask-the-scope-first.

### Fixed
- Tokens were overcounted about threefold: Claude Code repeats a response's usage on every content-block record, and these are now merged per message.
- Sub-agent transcripts (`<session>/subagents/`) were never read, so their tokens and tool use were missing.
- Projects whose path contains `_`, a space or a `.` were not found. Claude Code replaces every non-alphanumeric character in the log folder name.
- Slash-command prompts were dropped as injected text.

### Removed
- The `dispatcher-*` routing keys from the SKILL.md metadata. Nothing reads them since skill-dispatcher 5.0.0, which builds its registry from names and descriptions.

## [1.1.2] - 2026-09-27

### Changed
- The cost figure is labelled as an estimate. For an auditable number, the skill hands off to `token-usage-cost-report`. The two skills stay separate by decision: one tells the story, the other audits.
- `references/pricing-sources.md` points to the current Anthropic pricing page (`platform.claude.com`; the old `docs.claude.com` URL redirects there) and names the audit skill's stricter rules.

## [1.1.1] - 2026-06-23

### Changed
- `README.md`: install command is now `npx skills add jovd83/How-did-you-do-that-skill`
  (via the `skills` CLI) instead of a raw `git clone` into the runtime tree.

## [1.1.0] - 2026-06-21

### Added
- `references/pricing-sources.md`: a model-id→provider map (Anthropic, OpenAI, Google Gemini,
  Mistral, Cohere, DeepSeek, xAI, hosted Llama) plus the canonical **live** pricing-table URLs
  to fetch, and the per-type cost formula. Cost figures must now be computed from the current
  provider table at run time, never from memory.

### Changed
- `SKILL.md` and `references/model-fit.md`: cost/model-fit guidance is now provider-agnostic —
  look up each present model's provider and fetch its current pricing table (the `claude-api`
  skill stays the fast path for Claude); price each model from its own provider and never blend
  rates across providers; cite source URL + fetch date and label exact/partial/estimated.

## [1.0.0] - 2026-06-20

Initial release. Built and validated with the `skill-creator` workflow.

### Added
- `SKILL.md`: the workflow for reconstructing a logged AI session into a single Markdown
  explainer (narrative + technical appendix) with a "measure, don't guess" rule.
- `scripts/extract_session.py`: deterministic, stdlib-only parser that locates a folder's
  Claude Code transcripts (reproducing the `~/.claude/projects/<encoded-path>/` naming),
  merges all sessions, and emits a metrics JSON — real human prompts (filtering injected
  system-reminders and sub-agent notifications), per-model token splits, the four token
  types, speed, reasoning (thinking-block) counts, entrypoint/version, tool/skill/MCP/
  sub-agent counts, and wall-clock-span vs active-engaged-time. Best-effort detection of
  non-Claude-Code logs in the folder.
- `references/report-template.md`: the exact two-part output structure.
- `references/model-fit.md`: guidance for the "was this the right model?" critique and for
  turning token counts into a labelled cost estimate (deferring to `claude-api` for prices).
- `evals/evals.json`: three realistic test prompts.

### Validation
- Inline skill-creator validation against real transcripts. The baseline (no skill)
  misread "what I did with AI" as analysing repo source for LLM calls; the skill correctly
  parses session telemetry — confirming the skill closes a real capability gap.
- Fixed during validation: `<task-notification>` / Monitor sub-agent events were being
  counted as human prompts; they are now filtered, so prompt counts reflect real user turns.

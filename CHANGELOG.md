# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

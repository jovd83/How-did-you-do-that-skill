# What each tool logs

Read this when the metrics look odd, when logs live somewhere unusual, or when you need to open a
raw transcript. `scripts/extract_session.py` already handles everything below.

## Claude Code (full support)

- **Where:** `~/.claude/projects/<folder>/<session id>.jsonl`. The folder name is the project path
  with every character that isn't a letter or digit replaced by `-`
  (`C:\projects\VS_prj\App` → `C--projects-VS-prj-App`). Sub-agent transcripts sit in
  `<session id>/subagents/agent-*.jsonl`, each with a `.meta.json` holding the agent type and the
  task description.
- **Prompts:** user records whose `origin.kind` is `human`. Older logs lack `origin`; there,
  tool results, `isMeta` records, `<system-reminder>`, `<task-notification>`, hook output and the
  like are injected text, not prompts. Slash commands appear as `<command-name>` and are real
  prompts. A regression in this filter inflates the prompt count.
- **Tokens:** `message.usage` on assistant records. One API response is split into several records
  (one per content block) that **repeat the same usage**, so tokens are merged per `message.id`.
  Summing per record roughly triples the count. Thinking tokens are in
  `usage.output_tokens_details.thinking_tokens`, and cache writes are split into 5-minute and
  1-hour in `usage.cache_creation`.
- **Settings:**
  - `effort` on each assistant record (low, medium, high, xhigh, max)
  - `permissionMode` on prompts (default, plan, acceptEdits, auto, bypassPermissions)
  - `usage.speed` (standard or fast)
  - attachments: `model` (marketing name), `instructions` (the CLAUDE.md and memory files that
    were loaded), `invoked_skills`, `hook_success` (hook event and command), `auto_mode`,
    `plan_mode`, `environment` (OS, shell)
- **Context:** not logged as a window size. Peak use is input + cache read + cache write on one
  turn; above 200k tokens the 1M window was in use. `compact_boundary` system records mark
  compactions, with the token count before each one.
- **Cost:** `cost-state` records hold Claude Code's own running total (`totalCostUSD`, `costUSD`
  per model, lines added and removed). They are written now and then, so a session that went on
  afterwards is only partly covered; the extractor compares their output tokens with the
  transcript before trusting them.
- **Human actions besides prompts:** `toolDenialKind` (a permission refused),
  `[Request interrupted by user]`, `edited_text_file` attachments (a file changed outside the AI),
  `AskUserQuestion` and `ExitPlanMode` tool calls (questions and plan approvals).
- **Not logged:** the exact thinking budget, the context window size, background calls (only
  reflected in the reported cost).

## GitHub Copilot (best effort)

- **VS Code Copilot Chat:**
  - Where: `<VS Code user folder>/workspaceStorage/<hash>/chatSessions/*.json` or `*.jsonl`. The
    user folder is `%APPDATA%\Code\User` on Windows, `~/Library/Application Support/Code/User` on
    macOS and `~/.config/Code/User` on Linux, with "Code - Insiders" alongside. Each
    `workspaceStorage/<hash>/workspace.json` names its folder.
  - Format: newer `.jsonl` files are an edit log, replayed in order. Kind 0 is the initial state;
    kind 1 sets the value at key path `k`; kind 2 appends to the array at `k`; kind 3 deletes.
    Older `.json` files hold the whole session.
  - Per request:
    - `message.text` (the prompt) and `timestamp`
    - `modelId` or `result.details`, such as "Claude Sonnet 4 • 1x", which also gives the
      premium-request multiplier
    - `modeInfo.kind` (ask, edit or agent), `variableData` (context the user attached) and
      `result.timings`
    - response parts: `toolInvocationSerialized` (tool calls; terminal commands in
      `toolSpecificData`), `textEditGroup` (files edited) and markdown (the reply)
  - Token counts are rarely present.
- **Copilot CLI:** `~/.copilot/session-state/` and `history-session-state/`, as JSONL event logs
  (`session.*`, `user.message`, `assistant.message`, `tool.*`). The format is undocumented and
  changes; the extractor reads what it recognises.
- **Instruction files:** Copilot doesn't log which ones it loaded. The report lists the ones in the
  folder now: `.github/copilot-instructions.md`, `.github/instructions/*.md`, `AGENTS.md`, prompt
  files and agent files.
- **Cost:** premium requests, not tokens (see `pricing-sources.md`).
- **Copilot coding agent** (the cloud agent that opens pull requests) keeps its logs on GitHub, not
  on this computer. Point the user to the pull request's session log; it can't be extracted
  locally.

## Codex (best effort)

- **Where:** `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (and `archived_sessions/`), matched to
  the folder by `session_meta.cwd`. `CODEX_HOME` moves it.
- **What it records:**
  - `turn_context`: model, effort, approval policy, sandbox and collaboration mode, per turn
  - `event_msg` `token_count`: running totals, including cached input and reasoning tokens, plus
    `model_context_window`
  - prompts: `response_item` messages with role user (skip the injected `<environment_context>`
    and AGENTS.md blocks)
  - tool calls: `function_call` / `custom_tool_call`; commands are inside `exec_command` calls,
    and `apply_patch` names the files
  - `compacted` marks a compaction
- **Limits:** totals are per session, so a session that switched models can't be split per model
  (the extractor warns). Sessions spawned by Codex itself (reviewers, helpers) show up as separate
  sessions in the list.

## Anything else

`--transcripts <file, folder or glob>` reads explicit files and detects the format per file. For
tools not covered here (Cursor, Gemini CLI, Windsurf…), open their logs by hand, take what you can
(prompts and timestamps, usually), and record in section 12.D what was and wasn't available.

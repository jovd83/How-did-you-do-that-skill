---
name: how-did-you-do-that
description: "Use when the user wants to know how a piece of AI-assisted work was done, either to review how well the AI did the task or to replicate it on another computer or for another person. Reconstructs the logged sessions of Claude Code, GitHub Copilot (VS Code chat or CLI) or Codex for a project folder and writes one Markdown report with a fixed structure: the original and follow-up prompts, model, context window, mode, reasoning effort, tokens per model and type, cost, skills, plugins, MCP servers, sub-agents, hooks, non-AI tools and libraries, what the human and the AI did, what was achieved, a review scorecard and replication steps. Trigger on \"how did you do that\", \"write up this AI session\", \"what prompts did I use\", \"which model or settings did it use\", \"how much did this cost\", \"was this done well\", \"retro on this agent run\" or \"I want to redo this on my work laptop\", even when nobody mentions logs or transcripts."
license: MIT
metadata:
  version: "2.0.0"
  maturity: "stable"
  author: "jovd83"
---

# How did you do that

## What this skill is for

Someone did something with an AI assistant, and now a person wants to know how. The report this
skill writes serves two readers:

1. **The reviewer** wants to judge how well the task was done: was the goal met, was the result
   checked, how much steering did the human have to do, was the model and setup a good fit, and
   what did it cost.
2. **The replicator** wants to do the same thing elsewhere: which tool, model and settings, which
   skills, plugins, MCP servers and programs, which prompts in which order, and what to watch out
   for.

Every report has the same 12 sections in the same order (`assets/report-template.md`). That fixed
shape is the point: reports about different tasks, people and tools can be compared side by side,
and a reader always knows where to look. Write freely inside a section, but never add, drop,
rename or reorder the numbered headings.

## Ground rules

- **Measure, don't guess.** Token counts, times, model ids, file lists and tool counts come from
  `scripts/extract_session.py`, and `scripts/render_report.py` copies them into the report. Never
  type such a number yourself and never estimate one from the conversation you are in. Your job is
  the part a script can't do: why each prompt was sent, what it changed, how the work went, the
  ratings and the replication steps.
- **Missing is not zero.** When the logs don't record something (Copilot often has no token
  counts, no harness logs the exact reasoning budget), the report says "Not recorded in the logs".
  Say what is missing rather than leaving it out.
- **No AI, no story.** When no session logs exist for the folder or period, the report says that no
  AI was used as far as the logs show. The renderer handles that case; don't invent a narrative.
- **Evidence over adjectives.** Every rating and claim in the report should point to something a
  reader can check: a prompt number, a file, a command, a number in the appendix.

## Workflow

### 1. Settle the scope with the user

Three things decide what the report covers. Settle all of them before extracting anything, in one
message to the user, and skip what the user already told you.

- **Folder.** The project folder where the work happened. If the user says "this" or "here", use
  the current working directory.
- **Which sessions.** Run the listing first, so the question comes with real choices:

  ```bash
  python scripts/extract_session.py "<folder>" --list
  ```

  It prints every session found for the folder (Claude Code, Copilot, Codex), with id, tool, start
  and end time in local time, prompt count, AI turns, title and first prompt. Sessions a tool
  started by itself (sub-agents, Codex's automatic reviews) are already folded into their parent
  session, so don't offer them as separate choices. A session with 0 AI turns never got going and
  can be pointed out as such. A folder often holds sessions about
  unrelated tasks, and mixing them ruins both the review and the replication. So if the user has
  not said which work they mean, show the list and ask them to choose one of these:
  - particular sessions → `--session <id or id prefix>` (repeatable)
  - a period → `--since 2026-09-26 --until 2026-09-28` (local time; a bare `--until` date
    includes that whole day; a time can be added as `2026-09-26T14:00`)
  - the most recent ones → `--latest N`
  - everything → no option

  Translate what the user says ("yesterday afternoon", "the last one", "the Copilot chat about the
  login page") into these options yourself, and confirm only if it is ambiguous.
- **Where to save the report.** Ask, and suggest the project root as the default:
  `<folder>/how-did-you-do-that-<YYYY-MM-DD>.md`. Mention that the report quotes the prompts word
  for word (likely secrets are masked), which matters if the folder is a shared repository.

If the session being explained is the one you are running in, that's fine: the report covers it up
to now.

### 2. Extract the metrics

```bash
python scripts/extract_session.py "<folder>" [--session ... | --since ... --until ... | --latest N] --out "<work dir>/metrics.json"
```

Use a temporary or scratch folder as the work dir, not the project, so the repository stays clean.
This writes `metrics.json` and a readable digest next to it, `metrics.timeline.md`. Read the
printed summary and any warnings; they flag things like a Codex session that switched models.

The script finds Claude Code transcripts (including sub-agent transcripts), VS Code Copilot Chat
sessions, Copilot CLI logs and Codex logs for the folder. If the user's logs live somewhere
unusual, pass them directly with `--transcripts <file, folder or glob>`; the format is detected per
file. See `references/log-formats.md` for what each tool records and what it doesn't.

### 3. Get prices, only if the cost isn't reported

Look at `usage.reported_cost` in `metrics.json`. When `complete` is true, Claude Code reported the
cost itself and covered all selected work: skip this step.

Otherwise, the cost has to be computed from current list prices. Prices change often, so look them
up now and never quote them from memory. `references/pricing-sources.md` maps model ids to
providers, lists the pages to fetch, and gives the `prices.json` format. For GitHub Copilot, the
cost is premium requests (requests × model multiplier), not tokens; the same file explains it.
Save the result as `<work dir>/prices.json`.

### 4. Render the skeleton

```bash
python scripts/render_report.py "<work dir>/metrics.json" --prices "<work dir>/prices.json" --out "<report path>"
```

Leave out `--prices` when the cost was reported. Add `--title "..."` if the session title doesn't
describe the work well. The renderer fills every measured part of the template and leaves
`<!-- WRITE: ... -->` slots for you; it prints how many.

### 5. Read the evidence

Read `metrics.timeline.md` from top to bottom. It has one block per human prompt: the prompt, the
tools and commands that followed, the files written, sub-agents, errors, refusals, and the AI's
last reply before the next prompt. That is enough to explain almost every prompt.

Open a raw transcript only to settle a specific question, such as why a step failed. Transcripts
run to tens of megabytes, so search them for the timestamp the timeline gives rather than reading
them whole.

### 6. Fill the slots

Replace every `<!-- WRITE ... -->` with your text. Keep the measured content around the slots as it
is. Section by section:

- **1. Summary**: one sentence each. The verdict repeats the overall rating from section 10.
- **2. The request**: restate the original prompt in plain words for someone who wasn't there.
- **3. Follow-up prompts**: for each row, the kind, why it was sent (the reply before it usually
  tells you: something went wrong, something was missing, the user had a new idea) and what it
  changed. Runs of "continue" mean "keep going, the direction is right". You may merge
  consecutive rows like that into one, keeping the numbers ("5–7").
- **5. What drove the cost**: name the actual driver. On long agent sessions it is usually the
  context being re-read from cache on every turn, so cache-read tokens dominate.
- **6. Used for**: what each skill, MCP server, plugin or hook contributed, from the timeline.
- **7. Needed to replicate**: separate what a replicator must install from what was incidental
  (`ls`, `cat` and the like never matter).
- **8. What was done**: the human's steering and the AI's approach, in phases, citing prompt
  numbers. Dead ends and retries are the most useful part for both readers; name them plainly.
- **9. What was achieved**: deliverables, the evidence that they work (tests run, checks passed,
  the user accepting the result) and what was left open. "It was written" is not evidence that it
  works.
- **10. Review**: rate each criterion Good, Partly, Poor or Can't tell, with evidence. Use
  `references/review-guide.md`; it covers each criterion and the model-fit judgment.
- **11. Replicate it**: concrete steps that someone on another computer could follow. Point to
  prompts by number from appendix B instead of copying them again. The one-shot prompt folds the
  corrections into a single prompt so the replicator can skip the dead ends; put it in a fenced
  block. Under "Watch out for", name the paths, accounts and secrets specific to this machine.

You may improve the H1 title. Don't touch the numbered headings.

### 7. Check and hand over

```bash
python scripts/render_report.py --check "<report path>"
```

It fails while any slot is unfilled or a section is missing or out of order. Fix and rerun until it
passes.

Then tell the user:
- where the report is
- the headline in two or three lines: the goal, the verdict, the time and the cost
- how the cost was obtained (reported by the tool, or estimated from which price page)
- how many likely secrets were masked

Also suggest scanning the report with a secret or PII scanner (the `leak-canary` skill, if
installed) before sharing it outside the team. Offer to adjust the depth or the audience.

## When there's nothing to report

If `--list` finds no sessions, say so plainly and show where the script looked (the "searched"
part of its output). Ask whether the work happened in another folder, in a tool that keeps no
logs, or whether the logs were cleared. If the user still wants the report, render it anyway: it
states that no AI was used and passes the check without further writing.

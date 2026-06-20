#!/usr/bin/env python3
"""Extract a structured metrics bundle from logged AI sessions for a folder.

Primary source: Claude Code JSONL transcripts under ~/.claude/projects/<encoded-cwd>/.
Best-effort secondary sources: other AI tool logs found inside the target folder
(Codex, Cursor, Gemini/antigravity, generic *.jsonl chat logs).

The script does the *deterministic* work (parsing, counting, summing tokens, timing).
Interpretation (why a prompt was sent, what it altered, model-fit critique) is left to
the model reading the emitted JSON alongside the raw transcripts.

Usage:
    python extract_session.py <target-folder> [--out metrics.json] [--projects-dir DIR]
    python extract_session.py --transcripts <dir-or-glob> [--out metrics.json]

Stdlib only. Works on Windows and POSIX.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

# Gaps longer than this between consecutive events are treated as the human
# being away (thinking/reading/AFK) rather than active work, so we can separate
# "wall-clock span" from "active engaged time".
IDLE_GAP_SECONDS = 5 * 60

# Markers that identify injected (non-human) user-role content we must not treat
# as a real prompt the person typed.
INJECTED_PREFIXES = (
    "<system-reminder>",
    "Caveat:",
    "[Honcho Memory",
    "<command-message>",
    "<command-name>",
    "<local-command-stdout>",
    "Result of calling",
    "<task-notification>",   # sub-agent completion events re-injected as user turns
    "<task-id>",
    "<user-prompt-submit-hook>",
)


def encode_cwd(path: str) -> str:
    """Reproduce Claude Code's project-dir encoding: replace : / \\ with '-'."""
    return re.sub(r"[:/\\]", "-", path.rstrip("/\\"))


def find_projects_dir() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "projects")


def locate_transcripts(target_folder: str, projects_dir: str):
    """Return a list of .jsonl transcript files for the given folder, if any."""
    target_folder = os.path.abspath(target_folder)
    encoded = encode_cwd(target_folder)
    candidates = []
    if os.path.isdir(projects_dir):
        # exact encoded match
        exact = os.path.join(projects_dir, encoded)
        if os.path.isdir(exact):
            candidates.append(exact)
        # case-insensitive / drive-letter-case fallback
        if not candidates:
            enc_low = encoded.lower()
            for name in os.listdir(projects_dir):
                if name.lower() == enc_low:
                    candidates.append(os.path.join(projects_dir, name))
    files = []
    for d in candidates:
        files.extend(sorted(glob.glob(os.path.join(d, "*.jsonl"))))
    return files


def parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def iter_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def content_blocks(msg):
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, list):
        return c
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return []


def is_real_prompt(rec):
    """True if this user-role record is a human-typed prompt (not a tool result
    or an injected system reminder)."""
    if rec.get("type") != "user":
        return False
    if rec.get("isMeta"):
        return False
    if rec.get("isSidechain"):
        return False  # sub-agent traffic, not the human
    msg = rec.get("message") or {}
    blocks = content_blocks(msg)
    if not blocks:
        return False
    texts = []
    for b in blocks:
        if not isinstance(b, dict):
            return False
        if b.get("type") == "tool_result":
            return False
        if b.get("type") == "text":
            texts.append(b.get("text", ""))
    text = "\n".join(texts).strip()
    if not text:
        return False
    if text.startswith(INJECTED_PREFIXES):
        return False
    return True


def first_text(rec):
    blocks = content_blocks(rec.get("message") or {})
    return "\n".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text").strip()


def process_transcripts(files):
    sessions = {}
    prompts = []                 # ordered human prompts across all sessions
    models = Counter()
    model_tokens = defaultdict(lambda: Counter())
    speed_counter = Counter()
    service_tier = Counter()
    tools = Counter()
    skills = Counter()
    mcp = Counter()
    subagents = Counter()
    thinking_blocks = 0
    thinking_chars = 0
    web_search = 0
    web_fetch = 0
    versions = Counter()
    entrypoints = Counter()
    git_branches = Counter()
    all_events = []              # (timestamp, sessionId) for timing

    totals = Counter()           # input/output/cache_creation/cache_read

    for f in files:
        sid = os.path.splitext(os.path.basename(f))[0]
        s = sessions.setdefault(sid, {
            "session_id": sid, "file": f, "first_ts": None, "last_ts": None,
            "prompt_count": 0, "assistant_turns": 0,
        })
        for rec in iter_lines(f):
            ts = parse_ts(rec.get("timestamp"))
            if ts:
                all_events.append((ts, sid))
                if s["first_ts"] is None or ts < parse_ts(s["first_ts"]):
                    s["first_ts"] = rec["timestamp"]
                if s["last_ts"] is None or ts > parse_ts(s["last_ts"]):
                    s["last_ts"] = rec["timestamp"]
            if rec.get("version"):
                versions[rec["version"]] += 1
            if rec.get("entrypoint"):
                entrypoints[rec["entrypoint"]] += 1
            if rec.get("gitBranch"):
                git_branches[rec["gitBranch"]] += 1

            if is_real_prompt(rec):
                txt = first_text(rec)
                prompts.append({
                    "session_id": sid,
                    "timestamp": rec.get("timestamp"),
                    "text": txt if len(txt) <= 4000 else txt[:4000] + "\n…[truncated]",
                    "chars": len(txt),
                })
                s["prompt_count"] += 1

            if rec.get("type") == "assistant":
                s["assistant_turns"] += 1
                msg = rec.get("message") or {}
                model = msg.get("model")
                usage = msg.get("usage") or {}
                if model and model != "<synthetic>":
                    models[model] += 1
                    speed_counter[usage.get("speed", "unknown")] += 1
                    service_tier[usage.get("service_tier", "unknown")] += 1
                    for k in ("input_tokens", "output_tokens",
                              "cache_creation_input_tokens", "cache_read_input_tokens"):
                        v = usage.get(k, 0) or 0
                        totals[k] += v
                        model_tokens[model][k] += v
                stu = usage.get("server_tool_use") or {}
                web_search += stu.get("web_search_requests", 0) or 0
                web_fetch += stu.get("web_fetch_requests", 0) or 0

                for b in content_blocks(msg):
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "thinking":
                        thinking_blocks += 1
                        thinking_chars += len(b.get("thinking", "") or b.get("text", "") or "")
                    elif bt == "tool_use":
                        name = b.get("name", "")
                        if name.startswith("mcp__"):
                            mcp[name] += 1
                        elif name == "Skill":
                            inp = b.get("input") or {}
                            skills[str(inp.get("skill", "?"))] += 1
                        elif name == "Agent":
                            inp = b.get("input") or {}
                            subagents[str(inp.get("subagent_type", "agent"))] += 1
                            tools[name] += 1
                        else:
                            tools[name] += 1

    # Timing across all events.
    all_events.sort(key=lambda x: x[0])
    span_seconds = active_seconds = 0
    if all_events:
        span_seconds = (all_events[-1][0] - all_events[0][0]).total_seconds()
        for i in range(1, len(all_events)):
            gap = (all_events[i][0] - all_events[i - 1][0]).total_seconds()
            if 0 <= gap <= IDLE_GAP_SECONDS:
                active_seconds += gap

    started = all_events[0][0].isoformat() if all_events else None
    ended = all_events[-1][0].isoformat() if all_events else None

    return {
        "source": "claude-code",
        "transcript_files": files,
        "session_count": len(sessions),
        "sessions": sorted(sessions.values(), key=lambda s: s.get("first_ts") or ""),
        "timing": {
            "started_utc": started,
            "ended_utc": ended,
            "wall_clock_span_seconds": round(span_seconds),
            "active_engaged_seconds": round(active_seconds),
            "idle_gap_threshold_seconds": IDLE_GAP_SECONDS,
        },
        "prompts": {
            "human_prompt_count": len(prompts),
            "list": prompts,
        },
        "models": {
            "by_assistant_turns": dict(models),
            "tokens_by_model": {m: dict(c) for m, c in model_tokens.items()},
            "speed_distribution": dict(speed_counter),
            "service_tier_distribution": dict(service_tier),
        },
        "reasoning": {
            "thinking_blocks": thinking_blocks,
            "thinking_chars": thinking_chars,
            "note": "Thinking blocks present => extended/visible reasoning was used. "
                    "Claude Code does not record the exact thinking budget in usage; "
                    "block count and length are the available proxy.",
        },
        "tokens": {
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "cache_creation_input_tokens": totals["cache_creation_input_tokens"],
            "cache_read_input_tokens": totals["cache_read_input_tokens"],
            "server_tool_web_search_requests": web_search,
            "server_tool_web_fetch_requests": web_fetch,
            "total_billable_tokenish": (totals["input_tokens"] + totals["output_tokens"]
                                        + totals["cache_creation_input_tokens"]
                                        + totals["cache_read_input_tokens"]),
        },
        "tools": {
            "tool_calls": dict(tools.most_common()),
            "skills_invoked": dict(skills.most_common()),
            "mcp_tools": dict(mcp.most_common()),
            "subagents": dict(subagents.most_common()),
            "total_tool_calls": sum(tools.values()) + sum(skills.values()) + sum(mcp.values()),
        },
        "environment": {
            "entrypoints": dict(entrypoints),
            "claude_code_versions": dict(versions.most_common()),
            "git_branches": dict(git_branches),
        },
    }


def scan_other_tools(target_folder):
    """Best-effort detection of non-Claude-Code AI session logs inside the folder."""
    found = []
    patterns = {
        "codex": ["**/.codex/**/*.jsonl", "**/codex*session*.json*"],
        "cursor": ["**/.cursor/**/*.json", "**/cursor*chat*.json*"],
        "gemini/antigravity": ["**/.antigravity/**/*.json*", "**/.gemini/**/*.json*"],
        "generic-chatlog": ["**/*chat*.jsonl", "**/*session*.jsonl"],
    }
    for tool, pats in patterns.items():
        hits = []
        for p in pats:
            hits.extend(glob.glob(os.path.join(target_folder, p), recursive=True))
        # exclude anything inside the claude projects dir
        hits = [h for h in sorted(set(hits)) if ".claude" + os.sep + "projects" not in h]
        if hits:
            found.append({"tool": tool, "files": hits[:50], "count": len(hits)})
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target_folder", nargs="?", help="Folder where the AI work happened")
    ap.add_argument("--transcripts", help="Explicit transcripts dir or glob (skips folder->encoding lookup)")
    ap.add_argument("--projects-dir", default=find_projects_dir(), help="Override ~/.claude/projects")
    ap.add_argument("--out", help="Write JSON here (also printed to stdout)")
    args = ap.parse_args()

    if args.transcripts:
        files = sorted(glob.glob(args.transcripts)) if any(c in args.transcripts for c in "*?[") \
            else (sorted(glob.glob(os.path.join(args.transcripts, "*.jsonl")))
                  if os.path.isdir(args.transcripts) else [args.transcripts])
        target = os.path.abspath(args.transcripts)
    elif args.target_folder:
        target = os.path.abspath(args.target_folder)
        files = locate_transcripts(target, args.projects_dir)
    else:
        ap.error("provide a target folder or --transcripts")

    result = {
        "target_folder": target,
        "encoded_project_dir": encode_cwd(target) if args.target_folder else None,
        "claude_code": None,
        "other_tool_logs": [],
        "warnings": [],
    }

    if files:
        result["claude_code"] = process_transcripts(files)
    else:
        result["warnings"].append(
            "No Claude Code transcripts found for this folder. Looked in "
            f"{args.projects_dir} for encoded dir '{encode_cwd(target)}'.")

    if args.target_folder and os.path.isdir(target):
        result["other_tool_logs"] = scan_other_tools(target)
        if result["other_tool_logs"]:
            result["warnings"].append(
                "Found non-Claude-Code logs. These rarely contain token/model "
                "telemetry; extract prompts/timestamps best-effort by reading them directly.")

    out_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out_json)
        # Print a compact human summary to stdout, full JSON is in the file.
        cc = result["claude_code"]
        if cc:
            print(f"Wrote {args.out}")
            print(f"  sessions: {cc['session_count']}  human prompts: {cc['prompts']['human_prompt_count']}")
            print(f"  models: {cc['models']['by_assistant_turns']}")
            print(f"  tokens: in={cc['tokens']['input_tokens']:,} out={cc['tokens']['output_tokens']:,} "
                  f"cache_read={cc['tokens']['cache_read_input_tokens']:,} "
                  f"cache_create={cc['tokens']['cache_creation_input_tokens']:,}")
            print(f"  wall-clock: {cc['timing']['wall_clock_span_seconds']/3600:.1f}h  "
                  f"active: {cc['timing']['active_engaged_seconds']/3600:.1f}h")
            print(f"  tool calls: {cc['tools']['total_tool_calls']}  skills: {list(cc['tools']['skills_invoked'])}")
        for w in result["warnings"]:
            print("  ! " + w)
    else:
        print(out_json)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fill the fixed report template from a metrics bundle, or check a finished report.

Render (numbers are filled in; <!-- WRITE: ... --> slots are left for the writer):
  python render_report.py metrics.json --out report.md [--prices prices.json] [--title TEXT]

Check that a finished report kept the structure and has no unfilled slots:
  python render_report.py --check report.md

prices.json (only needed when the harness did not report the cost itself):
  {"source": "<pricing page URL>", "fetched": "YYYY-MM-DD", "currency": "USD",
   "models": {"<model id>": {"input": 5.0, "output": 25.0, "cache_write_5m": 6.25,
                             "cache_write_1h": 10.0, "cache_read": 0.5},
              "<copilot model>": {"premium_request_multiplier": 1, "premium_request_usd": 0.04}}}
Prices are per million tokens. Stdlib only, Python 3.8+.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "report-template.md")
SKILL_MD = os.path.join(HERE, "..", "SKILL.md")
MARKER = "<!-- how-did-you-do-that report v2 -->"
NOT_RECORDED = "Not recorded in the logs"
NO_AI = "No AI used."

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SOURCE_LABELS = {"claude-code": "Claude Code", "codex": "Codex", "copilot-vscode": "GitHub Copilot Chat (VS Code)",
                 "copilot-cli": "GitHub Copilot CLI"}


# ----------------------------------------------------------------------------- formatting

def n(v):
    return f"{int(v or 0):,}"


def short(v):
    v = int(v or 0)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f} M"
    if v >= 10_000:
        return f"{v / 1000:.0f} k"
    if v >= 1000:
        return f"{v / 1000:.1f} k"
    return str(v)


def dur(seconds):
    s = int(seconds or 0)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{round(s / 60)} min"
    if s < 48 * 3600:
        h, m = divmod(round(s / 60), 60)
        return f"{h} h {m} min" if m else f"{h} h"
    return f"{s / 86400:.1f} days"


def when(ts, with_time=True):
    if not ts:
        return "?"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    return dt.astimezone().strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


def cell(text, limit=None):
    text = re.sub(r"\s+", " ", str(text if text is not None else "")).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text.replace("|", "\\|")


def fenced(text):
    run = max((len(m) for m in re.findall(r"~{3,}", text or "")), default=2)
    fence = "~" * max(3, run + 1)
    return f"{fence}text\n{text}\n{fence}"


def money(v):
    if v is None:
        return "n/a"
    return f"${v:,.2f}" if v >= 0.995 else f"${v:,.3f}"


def model_label(mid, name=None):
    return f"{name} (`{mid}`)" if name and name != mid else f"`{mid}`"


def rel(path, target):
    if target and path:
        try:
            r = os.path.relpath(path, target)
            if not r.startswith(".."):
                return r
        except ValueError:
            pass
    return path


def skill_version():
    try:
        head = open(SKILL_MD, encoding="utf-8").read(4000)
    except OSError:
        return ""
    m = re.search(r"^\s*version:\s*['\"]?([^'\"\n]+)", head, re.M)
    return m.group(1).strip() if m else ""


# ----------------------------------------------------------------------------- prices

def load_prices(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data.get("models"), dict):
        raise SystemExit("prices.json needs a 'models' object keyed by model id.")
    return data


def price_for(prices, model):
    if not prices:
        return None
    table = prices["models"]
    if model in table:
        return table[model]
    low = {k.lower(): v for k, v in table.items()}
    m = model.lower()
    for cand in (m, re.sub(r"-\d{8}$", "", m), m.replace("[1m]", "")):
        if cand in low:
            return low[cand]
    keys = sorted(low, key=len, reverse=True)
    for k in keys:
        if m.startswith(k) or k.startswith(m):
            return low[k]
    return None


def row_cost(row, p):
    """Cost of one usage row, and the token types that had no price."""
    if not p or "premium_request_multiplier" in p:
        return None, []
    missing = []

    def rate(*keys):
        for k in keys:
            if p.get(k) is not None:
                return float(p[k])
        return None

    parts = [("input", row["input"], rate("input")),
             ("output", row["output"], rate("output")),
             ("cache_read", row["cache_read"], rate("cache_read", "cached_input")),
             ("cache_write_5m", row["cache_write_5m"], rate("cache_write_5m", "cache_write")),
             ("cache_write_1h", row["cache_write_1h"], rate("cache_write_1h", "cache_write")),
             ("cache_write", max(0, row["cache_write"] - row["cache_write_5m"] - row["cache_write_1h"]),
              rate("cache_write", "cache_write_5m"))]
    total = 0.0
    for name, tokens, r in parts:
        if not tokens:
            continue
        if r is None:
            missing.append(name)
            continue
        total += tokens / 1e6 * r
    return total, missing


# ----------------------------------------------------------------------------- blocks

def build_values(m, prices, title):
    target = m.get("target_folder")
    sessions = m["sessions"]
    prompts = m["prompts"]
    timing = m["timing"]
    setup = m["setup"]
    usage = m["usage"]
    ext = m["extensions"]
    tools = m["non_ai_tools"]
    work = m["work"]
    sources = sorted({s["source"] for s in sessions})
    source_text = ", ".join(SOURCE_LABELS.get(s, s) for s in sources) or "no AI tool"
    v = {}

    v["title"] = title or next((s["title"] for s in sessions if s.get("title")), None) or \
        (re.sub(r"\s+", " ", prompts[0]["text"])[:70] if prompts else os.path.basename(target or "") or "AI session")
    v["generated"] = when(m.get("generated_utc"))
    v["skill_version"] = skill_version()
    sel = m["selection"]
    sel_text = {"all": "all sessions found", "session": "chosen sessions", "latest": f"latest {sel.get('latest')}",
                "window": "a time window"}.get(sel["mode"], sel["mode"])
    span = f"{when(timing['started_utc'], False)} to {when(timing['ended_utc'], False)}" if timing["started_utc"] else ""
    v["about"] = cell(f"{len(sessions)} {source_text} session(s) in `{target}`" + (f", {span}" if span else "")
                      + f" ({sel_text}; {len(m['available_sessions'])} found in total)")
    v["ai_used"] = "Yes" if m["ai_used"] else "No. " + no_ai_reason(m)

    follow = max(0, len(prompts) - 1)
    slash = sum(1 for p in prompts if p["kind"] == "slash-command")
    cont = sum(1 for p in prompts if p["kind"] == "continue")
    v["prompt_summary"] = f"{len(prompts)} ({follow} follow-ups" + (f", {cont} of them 'continue'" if cont else "") + \
        (f", {slash} slash commands" if slash else "") + ")"
    v["time_summary"] = (f"≈{dur(timing['active_seconds'])} active, spread over {dur(timing['wall_clock_seconds'])} "
                         f"wall-clock ({len(sessions)} session(s))")
    models = setup["models"]
    v["model_summary"] = cell("; ".join(
        f"{model_label(x['id'], x.get('name'))}: {n(x['main_turns'])} turns"
        + (f" + {n(x['subagent_turns'])} in sub-agents" if x["subagent_turns"] else "") for x in models)) or NOT_RECORDED
    t = usage["totals"]
    if any(t.get(k) for k in ("input", "output", "cache_read", "cache_write")):
        v["token_summary"] = (f"{short(t.get('output'))} output, {short(t.get('input'))} input, "
                              f"{short(t.get('cache_read'))} cache read, {short(t.get('cache_write'))} cache write")
    else:
        v["token_summary"] = "No token counts in these logs"

    # cost
    usage_table, cost_block, cost_summary = usage_blocks(m, prices)
    v["usage_table"], v["cost_block"], v["cost_summary"] = usage_table, cost_block, cost_summary

    # request
    if prompts:
        p0 = prompts[0]
        v["first_prompt_meta"] = f"{when(p0['timestamp'])}, {SOURCE_LABELS.get(p0['source'], p0['source'])}, {n(p0['chars'])} characters"
        v["first_prompt_block"] = fenced(p0["text"])
    else:
        v["first_prompt_meta"] = "none found"
        v["first_prompt_block"] = NOT_RECORDED + "."

    # follow-ups
    if follow:
        rows = ["| # | When | Prompt (shortened) | Kind | Why it was sent | What it changed |", "|---|---|---|---|---|---|"]
        for p in prompts[1:]:
            kind = {"continue": "continue", "slash-command": "slash command"}.get(p["kind"], "<!-- WRITE -->")
            rows.append(f"| {p['n']} | {when(p['timestamp'])} | {cell(p['text'], 140)} | {kind} | <!-- WRITE --> | <!-- WRITE --> |")
        v["followups_table"] = "\n".join(rows)
    else:
        v["followups_table"] = "None. The work was done from the original prompt alone."

    v["setup_table"] = setup_table(m)
    v["extensions_table"] = extensions_table(m)
    v["tools_block"] = tools_block(m)
    v["human_facts"], v["ai_facts"] = work_facts(m)
    v["files_table"] = files_table(work, target)
    v["achieved_facts"] = achieved_facts(m)
    v["prerequisites"] = prerequisites(m)
    v["sessions_table"] = sessions_table(m)
    v["all_prompts"] = all_prompts(prompts)
    v["timing_block"] = timing_block(m)
    v["provenance_block"] = provenance_block(m, prices)
    return v


def no_ai_reason(m):
    looked = "; ".join(f"{s['source']}: {s['where']}" for s in m.get("searched", []))
    sel = m["selection"]
    extra = ""
    if sel["mode"] != "all":
        extra = " for the chosen sessions or period"
    return (f"No AI session logs were found for this folder{extra}, so as far as the logs show, no AI was used. "
            f"Looked in: {looked}.")


def usage_blocks(m, prices):
    usage = m["usage"]
    rows = usage["rows"]
    rc = usage.get("reported_cost")
    cop = usage.get("copilot")
    if not rows:
        return "No model usage was recorded.", "", NOT_RECORDED
    est_total, missing_any, unpriced = 0.0, set(), []
    lines = ["| Model | Scope | Turns | Input | Output | of which thinking | Cache write | Cache read | Est. cost |",
             "|---|---|---|---|---|---|---|---|---|"]
    totals = {"turns": 0, "input": 0, "output": 0, "thinking": 0, "cache_write": 0, "cache_read": 0}
    for r in rows:
        p = price_for(prices, r["model"])
        cost, missing = row_cost(r, p)
        if p is None and prices:
            unpriced.append(r["model"])
        if cost is not None:
            est_total += cost
        missing_any.update(missing)
        for k in totals:
            totals[k] += r.get(k, 0) or 0
        lines.append(f"| {model_label(r['model'], r.get('name'))} | {r['scope']} | {n(r['turns'])} | {n(r['input'])} | "
                     f"{n(r['output'])} | {n(r['thinking'])} | {n(r['cache_write'])} | {n(r['cache_read'])} | "
                     f"{money(cost) if cost is not None else '—'} |")
    lines.append(f"| **Total** | | {n(totals['turns'])} | {n(totals['input'])} | {n(totals['output'])} | "
                 f"{n(totals['thinking'])} | {n(totals['cache_write'])} | {n(totals['cache_read'])} | "
                 f"{money(est_total) if prices and est_total else '—'} |")
    t = usage["totals"]
    notes = []
    if t.get("cache_write_5m") or t.get("cache_write_1h"):
        notes.append(f"Cache writes: {n(t.get('cache_write_5m'))} with the 5-minute lifetime and "
                     f"{n(t.get('cache_write_1h'))} with the 1-hour lifetime, which is priced higher.")
    if t.get("web_search") or t.get("web_fetch"):
        notes.append(f"Server-side web searches: {n(t.get('web_search'))}; web fetches: {n(t.get('web_fetch'))}.")
    if any(r["scope"] == "subagent" for r in rows):
        notes.append("Sub-agent rows come from the sub-agents' own transcripts.")

    cost_lines = []
    if rc and rc.get("complete"):
        summary = f"{money(rc['total_usd'])}, reported by Claude Code"
        cost_lines.append(f"**Cost basis:** reported by Claude Code itself: {money(rc['total_usd'])} "
                          f"({'; '.join(f'`{k}` {money(v)}' for k, v in rc['by_model'].items())}). "
                          "It includes background calls that are not in the token table.")
        if prices and est_total:
            cost_lines.append(f"Cross-check from the price table: {money(est_total)} "
                              f"({prices.get('source')}, fetched {prices.get('fetched')}).")
    elif prices and est_total:
        label = "partial estimate" if (missing_any or unpriced) else "estimate"
        summary = f"≈{money(est_total)} ({label})"
        cost_lines.append(f"**Cost basis:** {label}, tokens × list prices from {prices.get('source')}, "
                          f"fetched {prices.get('fetched')} ({prices.get('currency', 'USD')}).")
        if missing_any:
            cost_lines.append(f"No price for token type(s): {', '.join(sorted(missing_any))}.")
        if unpriced:
            cost_lines.append(f"No price for model(s): {', '.join(sorted(set(unpriced)))}.")
        if rc:
            cost_lines.append(f"Claude Code reported {money(rc['total_usd'])} itself, but that figure covers only "
                              "part of this work. " + rc["note"])
    elif cop:
        summary = "premium requests, see below"
    else:
        summary = "Not priced"
        cost_lines.append("**Cost basis:** <!-- WRITE: no cost was reported in the logs and no price table was "
                          "supplied; fetch current prices, save prices.json and render again, or state why the "
                          "cost cannot be given -->")
        if rc:
            cost_lines.append(f"Claude Code reported {money(rc['total_usd'])} for part of this work. " + rc["note"])
    if cop:
        reqs, premium, unknown = 0, 0.0, []
        lines_c = ["| Model | Requests | Multiplier | Premium requests |", "|---|---|---|---|"]
        for model, d in cop["by_model"].items():
            mult = d.get("multiplier")
            if mult is None:
                pp = price_for(prices, model) or {}
                mult = pp.get("premium_request_multiplier")
            reqs += d["requests"]
            if mult is None:
                unknown.append(model)
            else:
                premium += d["requests"] * mult
            lines_c.append(f"| `{model}` | {d['requests']} | {mult if mult is not None else '?'} | "
                           f"{d['requests'] * mult if mult is not None else '?'} |")
        usd = None
        for d in (prices or {}).get("models", {}).values():
            if isinstance(d, dict) and d.get("premium_request_usd"):
                usd = float(d["premium_request_usd"])
        cost_lines.append("**GitHub Copilot** bills premium requests (requests × model multiplier) against the "
                          "plan's monthly allowance, not tokens.")
        cost_lines.append("\n".join(lines_c))
        cost_lines.append(f"Premium requests used: {premium:g}" + (f" (multiplier unknown for {', '.join(unknown)})" if unknown else "")
                          + (f"; beyond the allowance that is {money(premium * usd)}" if usd else "") + ".")
        if summary.startswith("premium"):
            summary = f"{premium:g} premium requests" + (f" (≈{money(premium * usd)} if over the allowance)" if usd else "")
    hints = usage.get("billing_hints") or []
    if rc or (prices and est_total):
        cost_lines.append("These are API list-price figures. " + (
            f"The log shows a {hints[0]}, so this is what the same tokens would cost on the API, not what was paid."
            if hints else "If the work ran on a subscription plan (Claude Pro or Max, ChatGPT, Copilot), "
                          "it is the API equivalent, not what was paid."))
    table = "\n".join(lines) + ("\n\n" + " ".join(notes) if notes else "")
    return table, "\n\n".join(cost_lines), summary


def setup_table(m):
    s = m["setup"]
    rows = ["| Setting | Value | Source |", "|---|---|---|"]

    def add(name, value, source="logged"):
        rows.append(f"| {name} | {cell(value) if value else NOT_RECORDED} | {source if value else '—'} |")

    add("Tool", "; ".join(f"{h['name']} {h['version']}" for h in s["harnesses"][:4]))
    add("Where it ran", "; ".join(f"{v['label']} ({v['count']} records)" if len(s['entrypoints']) > 1 else v["label"]
                                  for v in s["entrypoints"].values()))
    env = s.get("environment") or {}
    add("Computer", ", ".join(str(x) for x in (env.get("osVersion") or env.get("platform"), env.get("shell")) if x))
    add("Model(s)", "; ".join(f"{model_label(x['id'], x.get('name'))}: {n(x['main_turns'])} main turns"
                              + (f", {n(x['subagent_turns'])} sub-agent turns" if x["subagent_turns"] else "")
                              for x in s["models"]))
    ctx = s["context"]
    add("Context window", f"{n(ctx['window_tokens'])} tokens ({ctx['window_basis']})" if ctx["window_tokens"] else None,
        "logged" if ctx.get("window_basis") == "logged" else "inferred")
    add("Peak context used", f"{n(ctx['peak_tokens'])} tokens" + (f" (`{ctx['peak_model']}`)" if ctx.get("peak_model") else "")
        if ctx["peak_tokens"] else None)
    comp = ctx["compactions"]
    add("Context compactions", (f"{len(comp)}: " + ", ".join(
        f"{c.get('trigger') or 'auto'} at {short(c['pre_tokens'])}" if c.get("pre_tokens") else (c.get("trigger") or "compacted")
        for c in comp[:6])) if comp else "None")
    md = s["modes"]
    mode_bits = []
    if md["permission_modes"]:
        mode_bits.append("permission mode " + ", ".join(f"{k} ({v} prompts)" for k, v in md["permission_modes"].items()))
    if md["plan_mode_turns"]:
        mode_bits.append(f"plan mode on {md['plan_mode_turns']} turns")
    if md["auto_mode_seen"] and "auto" not in md["permission_modes"]:
        mode_bits.append("auto mode")
    if md["codex_approval"]:
        mode_bits.append("approval policy " + ", ".join(md["codex_approval"]))
    if md["codex_sandbox"]:
        mode_bits.append("sandbox " + ", ".join(md["codex_sandbox"]))
    if md["collaboration_modes"]:
        mode_bits.append("collaboration mode " + ", ".join(md["collaboration_modes"]))
    if md["copilot_modes"]:
        mode_bits.append("chat mode " + ", ".join(f"{k} ({v})" for k, v in md["copilot_modes"].items()))
    add("Mode", "; ".join(mode_bits))
    add("Reasoning effort", ", ".join(f"{k} on {n(v)} turns" for k, v in s["effort"].items()))
    th = s["thinking"]
    add("Thinking", (f"{n(th['tokens'])} thinking tokens" if th["tokens"] else "") +
        (f"{'; ' if th['tokens'] else ''}{n(th['blocks'])} thinking blocks" if th["blocks"] else "") or None)
    add("Speed", ", ".join(f"{k} on {n(v)} turns" for k, v in s["speed"].items()))
    add("Instruction files", "; ".join(f"`{i['path']}` ({i.get('type') or 'file'}, {n(i.get('chars'))} chars)"
                                       for i in s["instruction_files"][:8]),
        "logged" if any(i.get("type") != "in folder now" for i in s["instruction_files"]) else "folder now")
    add("Hooks", f"{len(s['hooks'])} hook command(s), see section 6" if s["hooks"] else "None")
    if s.get("local_command_output"):
        add("Changed during the session", "; ".join(f"{when(x['ts'])}: {x['text']}" for x in s["local_command_output"][:6]))
    for cs in s.get("current_settings") or []:
        vals = ", ".join(f"{k}={v}" for k, v in cs["values"].items() if k != "enabledPlugins")
        if vals:
            rows.append(f"| Settings file now | {cell(vals)} (`{cell(cs['path'])}`) | file now, may differ from the session |")
    return "\n".join(rows)


def extensions_table(m):
    e = m["extensions"]
    s = m["setup"]
    rows = ["| Name | Kind | Source or version | Uses | Used for |", "|---|---|---|---|---|"]
    for sk in e["skills"]:
        src = sk.get("source") or ""
        if sk.get("version_now"):
            src = (src + "; " if src else "") + f"version {sk['version_now']} installed now"
        rows.append(f"| {cell(sk['name'])} | skill | {cell(src) or '—'} | {sk['uses']} | <!-- WRITE --> |")
    for mc in e["mcp_servers"]:
        top = ", ".join(f"{k.split('__')[-1]} ×{v}" for k, v in list(mc["tools"].items())[:4])
        rows.append(f"| {cell(mc['server'])} | MCP server | {cell(top)} | {mc['calls']} | <!-- WRITE --> |")
    for pl in e["plugins"]:
        rows.append(f"| {cell(pl['name'])} | plugin | {cell('; '.join(pl['evidence']))} | — | <!-- WRITE --> |")
    for sa in e["subagents"]:
        models = ", ".join(f"`{k}`" for k in sa.get("models", {}))
        desc = "; ".join(sa.get("descriptions") or []) or "<!-- WRITE -->"
        rows.append(f"| {cell(sa['type'])} | sub-agent | {cell(models) or '—'} | {sa['count']} | {cell(desc, 300)} |")
    for h in s["hooks"]:
        rows.append(f"| {cell(h['command'], 80)} | hook ({h['event']}) | — | {h['runs']} | <!-- WRITE --> |")
    if len(rows) == 2:
        return "None used: no skills, plugins, MCP servers, sub-agents or hooks appear in the logs."
    return "\n".join(rows)


def tools_block(m):
    t = m["non_ai_tools"]
    out = []
    progs = [x for x in t["executables"] if x["category"] == "program"]
    other = [x for x in t["executables"] if x["category"] in ("shell utility", "PowerShell cmdlet")]
    modules = [x for x in t["executables"] if x["category"] == "python module"]
    unknown = [x for x in t["executables"] if x["category"] == "not on PATH now"]
    if progs:
        out.append("| Program | Runs |\n|---|---|\n" + "\n".join(f"| {cell(x['name'])} | {x['count']} |" for x in progs[:25]))
        if len(progs) > 25:
            out.append(f"…and {len(progs) - 25} more programs (see the metrics file).")
    else:
        out.append("No programs were run through the shell.")
    if modules:
        out.append("Python modules run with `python -m`: "
                   + ", ".join(f"{x['name'].split()[-1]} ×{x['count']}" for x in modules[:15]) + ".")
    if other:
        out.append("Shell utilities and PowerShell cmdlets: " + ", ".join(f"{x['name']} ×{x['count']}" for x in other[:20]) + ".")
    if unknown:
        out.append("Names run that are not on the PATH now (shell functions, scripts, aliases, or something the AI "
                   "installed and removed again): " + ", ".join(f"{x['name']} ×{x['count']}" for x in unknown[:15]) + ".")
    if t["installs"]:
        out.append("**Installed during the session:**\n\n" + "\n".join(
            f"- {x['manager']}: {', '.join(x['packages']) or '(see command)'} — `{cell(x['command'], 120)}`" for x in t["installs"][:20]))
    else:
        out.append("**Installed during the session:** nothing.")
    if t["imports"]:
        lines = []
        for lang, mods in t["imports"].items():
            ext = [k for k in mods if "(" not in k]
            std = [k.split(" ")[0] for k in mods if "(" in k]
            lines.append(f"- {lang}: " + (", ".join(ext) if ext else "no third-party imports")
                         + (f" (standard library: {', '.join(std[:12])})" if std else ""))
        out.append("**Libraries imported by code the AI wrote:**\n\n" + "\n".join(lines))
    if t["web_searches"] or t["web_domains"]:
        bits = []
        if t["web_searches"]:
            bits.append(f"{len(t['web_searches'])} web search(es), e.g. " + "; ".join(f"“{q}”" for q in t["web_searches"][:5]))
        if t["web_domains"]:
            bits.append("pages fetched from " + ", ".join(f"{d} ×{c}" for d, c in t["web_domains"].items()))
        out.append("**Web:** " + "; ".join(bits) + ".")
    return "\n\n".join(out)


def work_facts(m):
    w = m["work"]
    p = m["prompts"]
    slash = sorted({x["text"].split()[0] for x in p if x["kind"] == "slash-command"})
    cont = sum(1 for x in p if x["kind"] == "continue")
    human = [f"- Prompts: {len(p)}" + (f", of which {cont} were 'continue'-style nudges" if cont else "")
             + (f"; slash commands used: {', '.join(slash)}" if slash else "")]
    human.append("- Permission refusals: " + (", ".join(f"{k} ×{v}" for k, v in w["denials"].items()) if w["denials"] else "none"))
    human.append(f"- Interruptions: {w['interruptions']}")
    human.append(f"- Questions the AI asked the human: {w['questions_asked']}; plans presented for approval: {w['plans_presented']}")
    for t in m["timeline"]:
        for q in t.get("questions") or []:
            human.append(f"- Prompt {t['n']}: the AI asked “{cell(q['question'], 160)}” and the human answered "
                         f"“{cell(q['answer'] or 'no answer logged', 200)}”")
    if w.get("approval_requests"):
        human.append(f"- Approvals the AI needed to run commands outside its sandbox: {len(w['approval_requests'])}, e.g. "
                     + "; ".join(f"“{cell(a['what'], 110)}”" for a in w["approval_requests"][:4]))
    outside = [x for x in w["external_edits"] if not x.get("written_by_ai_shell")]
    if outside:
        human.append("- Files Claude Code noticed had changed on disk since it last read them. The log doesn't "
                     "say who changed them: the human, another program, or a script the AI itself ran: "
                     + ", ".join(f"`{rel(x['path'], m['target_folder'])}`" for x in outside[:10]))
    attached = sorted({c for t in m["timeline"] for c in t.get("attached_context", [])})
    if attached:
        human.append("- Context the human attached: " + ", ".join(attached[:15]))
    top = ", ".join(f"{k} ×{v}" for k, v in list(w["tool_calls"].items())[:8])
    sub = sum(a["count"] for a in m["extensions"]["subagents"])
    ai = [f"- Tool calls: {n(w['total_tool_calls'])}" + (f" ({top})" if top else ""),
          f"- Shell commands: {n(w['commands'])}",
          f"- Files written: {len(w['files_written'])}; files read: {w['files_read']}",
          f"- Sub-agents started: {sub}",
          f"- Errors: {w['tool_errors']} failed tool calls, {w['api_errors']} API errors",
          f"- Context compactions: {len(m['setup']['context']['compactions'])}"]
    return "\n".join(human), "\n".join(ai)


def files_table(w, target):
    # Shell commands and edit tools spell the same file differently (/c/x vs C:\x), so merge on a normal form.
    merged, temp = {}, 0
    for f in w["files_written"]:
        raw = re.sub(r"^/([A-Za-z])/", r"\1:/", f["path"])
        if raw.endswith(("/", "\\")):
            continue  # a folder, not a file
        if re.search(r"(^|[/\\])(tmp|temp)[/\\]|AppData[/\\]Local[/\\]Temp|^/tmp|^/dev/", raw, re.I):
            temp += 1
            continue
        key = os.path.normcase(os.path.normpath(raw))
        entry = merged.setdefault(key, {"path": raw, "edits": 0, "tools": {}, "gone": False})
        entry["edits"] += f["edits"]
        for k, v in f["tools"].items():
            entry["tools"][k] = entry["tools"].get(k, 0) + v
        entry["gone"] = entry["gone"] or f.get("exists_now") is False
    files = sorted(merged.values(), key=lambda f: -f["edits"])
    if not files:
        return "No files were written by the AI."
    rows = ["Edit tools and shell commands (redirections, `sed -i`, `tee`, `cp`, `mv`, PowerShell writers) both count.",
            "", "| File | Changes | How |", "|---|---|---|"]
    for f in files[:30]:
        gone = " (gone now)" if f["gone"] else ""
        rows.append(f"| `{cell(rel(f['path'], target))}`{gone} | {f['edits']} | {cell(', '.join(f['tools']))} |")
    if len(files) > 30:
        rows.append(f"| …and {len(files) - 30} more | | |")
    if temp:
        rows.append("")
        rows.append(f"{temp} temporary file(s) are left out.")
    return "\n".join(rows)


def achieved_facts(m):
    w = m["work"]
    out = []
    if w["git_commits"]:
        out.append("**Commits made:**\n\n" + "\n".join(f"- {when(c['ts'])}: {c['message']}" for c in w["git_commits"][:20]))
    else:
        out.append("**Commits made:** none in the logs.")
    if w["pull_requests"]:
        out.append("**Pull requests opened:** " + "; ".join(x.get("title") or "(title not parsed)" for x in w["pull_requests"]))
    if w.get("lines_added") is not None:
        out.append(f"**Lines changed** (Claude Code's count, for the part it covers): +{n(w['lines_added'])} / -{n(w['lines_removed'])}")
    if w.get("last_reply_excerpt"):
        out.append("**The AI's last reply** (excerpt):\n\n> " + w["last_reply_excerpt"].replace("\n", "\n> "))
    return "\n\n".join(out)


def prerequisites(m):
    s = m["setup"]
    e = m["extensions"]
    t = m["non_ai_tools"]
    items = []
    for h in s["harnesses"][:2]:
        where = ", ".join(v["label"] for v in s["entrypoints"].values())
        items.append(f"- [ ] {h['name']} {h['version']}" + (f", used from the {where}" if where else ""))
    for x in s["models"]:
        eff = ", ".join(s["effort"]) if s["effort"] else ""
        items.append(f"- [ ] Model {model_label(x['id'], x.get('name'))}" + (f", reasoning effort {eff}" if eff else "")
                     + (", fast mode" if s["speed"].get("fast") else ""))
    md = s["modes"]
    modes = []
    if md["permission_modes"]:
        modes.append("permission mode " + ", ".join(md["permission_modes"]))
    if md["codex_approval"]:
        modes.append("approval policy " + ", ".join(md["codex_approval"]))
    if md["codex_sandbox"]:
        modes.append("sandbox " + ", ".join(md["codex_sandbox"]))
    if md["copilot_modes"]:
        modes.append("chat mode " + ", ".join(md["copilot_modes"]))
    if modes:
        items.append(f"- [ ] Mode: {'; '.join(modes)}")
    for sk in e["skills"]:
        items.append(f"- [ ] Skill `{sk['name']}`" + (f" (version {sk['version_now']} installed now)" if sk.get("version_now") else "")
                     + (f", from {sk['source']}" if sk.get("source") else ""))
    for mc in e["mcp_servers"]:
        items.append(f"- [ ] MCP server `{mc['server']}`")
    for pl in e["plugins"]:
        items.append(f"- [ ] Plugin `{pl['name']}` ({'; '.join(pl['evidence'])})")
    progs = [x["name"] for x in t["executables"] if x["category"] == "program"]
    if progs:
        items.append("- [ ] Programs on the PATH: " + ", ".join(f"`{p}`" for p in progs[:20]))
    for ins in t["installs"][:10]:
        items.append(f"- [ ] {ins['manager']} packages: " + ", ".join(ins["packages"]))
    for i in s["instruction_files"][:8]:
        items.append(f"- [ ] Instruction file `{i['path']}` ({i.get('type') or 'file'}): copy the rules from it that shaped this work")
    return "\n".join(items) if items else NOT_RECORDED + "."


def sessions_table(m):
    rows = ["| Tool | Session | Title | Start | End | Prompts | Sub-agents |", "|---|---|---|---|---|---|---|"]
    for s in m["sessions"]:
        rows.append(f"| {SOURCE_LABELS.get(s['source'], s['source'])} | `{s['session_id'][:12]}` | {cell(s.get('title') or '', 60)} | "
                    f"{when(s['first_ts'])} | {when(s['last_ts'])} | {s.get('prompt_count') or 0} | {s.get('subagent_count') or 0} |")
    if not m["sessions"]:
        rows = ["No sessions."]
    chosen = {s["session_id"] for s in m["sessions"]}
    others = [s for s in m["available_sessions"] if s["session_id"] not in chosen]
    if others:
        rows.append("")
        rows.append(f"Not included ({len(others)} other session(s) found for this folder): " + "; ".join(
            f"`{s['session_id'][:12]}` {when(s['first_ts'], False)} {cell(s.get('title') or s.get('first_prompt') or '', 50)}"
            for s in others[:15]) + ("; …" if len(others) > 15 else ""))
    return "\n".join(rows)


def all_prompts(prompts):
    if not prompts:
        return NOT_RECORDED + "."
    out = []
    for p in prompts:
        kind = f" · {p['kind']}" if p["kind"] else ""
        out.append(f"<details><summary>Prompt {p['n']} · {when(p['timestamp'])}{kind} · {n(p['chars'])} chars</summary>\n\n"
                   f"{fenced(p['text'])}\n\n</details>")
    return "\n\n".join(out)


def timing_block(m):
    t = m["timing"]
    lines = [f"- First activity: {when(t['started_utc'])}", f"- Last activity: {when(t['ended_utc'])}",
             f"- Wall-clock span: {dur(t['wall_clock_seconds'])}",
             f"- Active time: {dur(t['active_seconds'])} (gaps longer than {t['idle_gap_seconds'] // 60} min between "
             "logged events count as time away)"]
    for tl in m["timeline"]:
        if tl.get("duration_seconds") and tl["duration_seconds"] >= 600:
            lines.append(f"- Prompt {tl['n']} kept the AI busy for {dur(tl['duration_seconds'])}")
    return "\n".join(lines[:20])


def provenance_block(m, prices):
    lines = ["Sources searched:"]
    for s in m.get("searched", []):
        lines.append(f"- {s['source']}: {s['where']} ({s['sessions_found']} session file(s))")
    if m["sessions"]:
        lines.append("")
        lines.append("Transcripts read: " + ", ".join(f"`{s['file']}`" for s in m["sessions"][:10]))
    r = m.get("redactions") or {}
    lines.append("")
    lines.append(f"Likely secrets masked in prompt text: {r.get('count', 0)}"
                 + (f" ({', '.join(f'{k} ×{v}' for k, v in r.get('by_kind', {}).items())})" if r.get("count") else "") + ".")
    if prices:
        lines.append(f"Prices: {prices.get('source')}, fetched {prices.get('fetched')}.")
    if m.get("data_gaps"):
        lines.append("")
        lines.append("Not in the logs, or only partly:")
        lines += [f"- {g}" for g in m["data_gaps"]]
    if m.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        lines += [f"- {w}" for w in m["warnings"]]
    lines.append("")
    lines.append(f"Numbers measured by `extract_session.py` ({m.get('schema')}) and rendered by `render_report.py`. "
                 "Ratings, reasons and summaries were written by the AI that made this report.")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- render / check

def render(metrics_path, out_path, prices_path=None, title=None):
    with open(metrics_path, encoding="utf-8") as fh:
        m = json.load(fh)
    if not str(m.get("schema", "")).endswith("@2"):
        raise SystemExit("This metrics file is not from extract_session.py v2; extract again.")
    prices = load_prices(prices_path)
    template = open(TEMPLATE, encoding="utf-8").read()
    if m["ai_used"]:
        values = build_values(m, prices, title)
    else:
        values = {k: NO_AI for k in re.findall(r"\{\{(\w+)\}\}", template)}
        values.update(title=title or os.path.basename(m.get("target_folder") or "") or "no AI session",
                      generated=when(m.get("generated_utc")), skill_version=skill_version(),
                      about=cell(f"`{m.get('target_folder')}`"), ai_used="No. " + no_ai_reason(m),
                      sessions_table="No sessions.", provenance_block=provenance_block(m, prices))
        template = re.sub(r"<!-- WRITE[^>]*-->", "Not applicable: no AI was used.", template)
    for key, val in values.items():
        template = template.replace("{{" + key + "}}", str(val))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(template)
    slots = template.count("<!-- WRITE")
    print(f"Wrote {out_path}: {slots} slot(s) to write" + ("" if m["ai_used"] else " (no AI used)"))


def check(report_path):
    template = open(TEMPLATE, encoding="utf-8").read()
    report = open(report_path, encoding="utf-8").read()
    wanted = [l.strip() for l in template.splitlines() if l.startswith(("## ", "### "))]
    have = [l.strip() for l in report.splitlines() if l.startswith(("## ", "### "))]
    problems = []
    if MARKER not in report:
        problems.append("the report marker comment is missing")
    pos = 0
    for h in wanted:
        try:
            pos = have.index(h, pos) + 1
        except ValueError:
            problems.append(f"heading missing or out of order: {h}")
    open_slots = len(re.findall(r"<!-- WRITE", report))
    if open_slots:
        problems.append(f"{open_slots} <!-- WRITE --> slot(s) still unfilled")
    if "{{" in report and re.search(r"\{\{\w+\}\}", report):
        problems.append("template placeholders left: " + ", ".join(sorted(set(re.findall(r"\{\{\w+\}\}", report)))[:5]))
    if problems:
        print(f"CHECK FAILED for {report_path}:")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"CHECK PASSED for {report_path}: all {len(wanted)} sections present in order, no open slots.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("metrics", nargs="?", help="metrics.json from extract_session.py")
    ap.add_argument("--out", help="Report path to write")
    ap.add_argument("--prices", help="prices.json with per-million-token prices (see above)")
    ap.add_argument("--title", help="Report title (default: the session title or first prompt)")
    ap.add_argument("--check", metavar="REPORT", help="Check a finished report and exit")
    args = ap.parse_args()
    if args.check:
        raise SystemExit(check(args.check))
    if not args.metrics or not args.out:
        ap.error("give metrics.json and --out, or --check REPORT")
    render(args.metrics, args.out, args.prices, args.title)


if __name__ == "__main__":
    main()

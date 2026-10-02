#!/usr/bin/env python3
"""Extract a metrics bundle from logged AI coding sessions for one project folder.

Sources, all read-only:
  * Claude Code     ~/.claude/projects/<encoded folder>/<session>.jsonl, plus each
                    session's sub-agent transcripts in <session>/subagents/.
  * GitHub Copilot  VS Code Copilot Chat sessions in <VS Code user dir>/workspaceStorage/
                    <hash>/chatSessions/ (best effort), and Copilot CLI session logs in
                    ~/.copilot/session-state/ (best effort).
  * Codex           ~/.codex/sessions/** (best effort).

The script does the deterministic work: finding the logs, choosing sessions, counting
prompts, tokens, tools, files and time. Interpretation (why a prompt was sent, whether the
work was good) is left to the model that reads the output.

Usage:
  python extract_session.py <folder> --list
  python extract_session.py <folder> [--session ID ...] [--since WHEN] [--until WHEN]
                            [--latest N] --out metrics.json
  python extract_session.py --transcripts <file|dir|glob> --out metrics.json

With --out, a readable timeline (<out>.timeline.md) is written next to the JSON.
Stdlib only, Python 3.8+.
"""
from __future__ import annotations

import argparse
import functools
import glob
import itertools
import json
import os
import re
import shutil
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

SCHEMA = "how-did-you-do-that/metrics@2"
# Gaps longer than this between consecutive events count as the human being away, so
# "active time" can be told apart from the wall-clock span.
IDLE_GAP_SECONDS = 5 * 60
PROMPT_LIMIT = 12000
EXCERPT_LIMIT = 600
COMMANDS_PER_PROMPT = 8

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# User-role text that the harness injected, not something the person typed. Only used for
# older Claude Code logs that lack the `origin` field.
INJECTED_PREFIXES = (
    "<system-reminder>",
    "Caveat:",
    "[Honcho Memory",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "Result of calling",
    "<task-notification>",
    "<task-id>",
    "<user-prompt-submit-hook>",
    "This session is being continued from a previous conversation",
)
INJECTED_BLOCKS = re.compile(
    r"<(system-reminder|ide_opened_file|ide_selection|ide_diagnostics|user-prompt-submit-hook)>.*?</\1>",
    re.S)
CONTINUE_RE = re.compile(
    r"^(continue|go on|go ahead|proceed|yes|y|ok|okay|retry|try again|again|do it|go|next|"
    r"keep going|ga verder|doe maar|ja|vas-y|continue please)\b[.! ]*$", re.I)

ENTRYPOINT_LABELS = {
    "claude-vscode": "VS Code extension",
    "cli": "terminal (CLI)",
    "sdk-ts": "Agent SDK (TypeScript)",
    "sdk-py": "Agent SDK (Python)",
    "sdk-cli": "Agent SDK",
    "claude-desktop": "Claude desktop app",
    "remote": "claude.ai/code (web)",
    "local-agent": "Claude desktop app",
    "copilot-vscode": "VS Code (GitHub Copilot Chat)",
    "codex-tui": "Codex CLI (terminal)",
    "codex_cli_rs": "Codex CLI (terminal)",
    "codex_exec": "codex exec (non-interactive)",
    "codex_vscode": "Codex extension in VS Code",
    "Codex Desktop": "Codex desktop app",
}

SHELL_UTILITIES = {
    "cd", "echo", "ls", "dir", "cat", "head", "tail", "grep", "egrep", "rg", "find", "sed", "awk",
    "wc", "sort", "uniq", "cut", "tr", "xargs", "mkdir", "rmdir", "rm", "cp", "mv", "pwd", "test",
    "true", "false", "sleep", "printf", "export", "set", "unset", "source", ".", "touch", "chmod",
    "diff", "tee", "basename", "dirname", "date", "which", "where", "type", "env", "realpath",
    "readlink", "stat", "file", "du", "df", "tar", "unzip", "zip", "gzip", "less", "more", "clear",
    "cmd", "start", "timeout", "for", "while", "if", "case", "function", "return", "exit", "local",
    "read", "shift", "eval", "trap", "wait", "kill", "ps", "jobs", "fg", "bg", "cygpath", "md5sum",
    "sha256sum", "base64", "od", "xxd", "column", "nl", "fold", "paste", "comm", "join", "split",
    "ln", "mktemp", "nproc", "uname", "whoami", "hostname", "id", "seq", "yes", "tac", "rev",
    "command", "builtin", "declare", "shopt", "pushd", "popd", "alias", "hash",
}

SECRET_PATTERNS = [
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
]
BEARER_RE = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]{20,}")
ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)"
    r"(\s*[:=]\s*)(['\"]?)([^\s'\"]{6,})\3")

INSTALL_PATTERNS = [
    ("pip", r"\b(?:pip3?|python3?\s+-m\s+pip|py\s+-m\s+pip|uv\s+pip)\s+install\s+([^\n;&|]+)"),
    ("uv", r"\buv\s+add\s+([^\n;&|]+)"),
    ("npm", r"\bnpm\s+(?:i|install|add)\s+([^\n;&|]+)"),
    ("pnpm", r"\bpnpm\s+(?:add|install|i)\s+([^\n;&|]+)"),
    ("yarn", r"\byarn\s+(?:global\s+)?add\s+([^\n;&|]+)"),
    ("bun", r"\bbun\s+(?:add|install|i)\s+([^\n;&|]+)"),
    ("winget", r"\bwinget\s+install\s+([^\n;&|]+)"),
    ("choco", r"\bchoco\s+install\s+([^\n;&|]+)"),
    ("scoop", r"\bscoop\s+install\s+([^\n;&|]+)"),
    ("brew", r"\bbrew\s+install\s+([^\n;&|]+)"),
    ("apt", r"\bapt(?:-get)?\s+install\s+([^\n;&|]+)"),
    ("cargo", r"\bcargo\s+(?:install|add)\s+([^\n;&|]+)"),
    ("go", r"\bgo\s+(?:install|get)\s+([^\n;&|]+)"),
    ("dotnet", r"\bdotnet\s+add\s+(?:\S+\s+)?package\s+([^\n;&|]+)"),
    ("powershell", r"\bInstall-Module\s+([^\n;&|]+)"),
    ("playwright", r"\bplaywright\s+install\b([^\n;&|]*)"),
    ("skills", r"\bnpx\s+(?:-y\s+)?skills\s+add\s+([^\n;&|]+)"),
]
HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1[ \t]*(?=\n|$)", re.S)
HERESTRING_RE = re.compile(r"@(['\"])\r?\n.*?\r?\n\1@", re.S)  # PowerShell here-strings
EXE_NAME_RE = re.compile(r"^[A-Za-z][\w.+-]*$")
CODE_KEYWORDS = {
    "import", "from", "def", "class", "return", "print", "else", "elif", "try", "except", "finally",
    "with", "const", "let", "var", "function", "lambda", "pass", "raise", "assert", "global", "async",
    "await", "yield", "in", "is", "not", "and", "or", "None", "True", "False", "null", "undefined",
    "this", "new", "catch", "switch", "break", "continue", "param", "foreach",
}
NODE_BUILTINS = {
    "fs", "path", "os", "child_process", "url", "http", "https", "crypto", "util", "events",
    "stream", "zlib", "readline", "assert", "buffer", "net", "dns", "tls", "process", "module",
    "worker_threads", "perf_hooks", "timers", "querystring", "string_decoder", "vm", "cluster",
}
PY_STDLIB = set(getattr(sys, "stdlib_module_names", ())) or {
    "os", "sys", "re", "json", "glob", "argparse", "pathlib", "subprocess", "datetime", "time",
    "collections", "itertools", "functools", "typing", "math", "random", "shutil", "tempfile",
    "logging", "unittest", "urllib", "csv", "io", "hashlib", "base64", "dataclasses", "textwrap",
}


# ----------------------------------------------------------------------------- helpers

def parse_ts(value):
    """Timestamp (ISO string or epoch s/ms) -> aware UTC datetime, or None."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        secs = value / 1000.0 if value > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        # Python < 3.11 only accepts 3 or 6 fractional digits.
        text = re.sub(r"\.(\d{1,6})\d*(?=[+-]\d\d:\d\d$|$)", lambda m: "." + m.group(1).ljust(6, "0"), text)
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def parse_user_when(text, end_of_day=False):
    """--since/--until value (local time unless it carries an offset) -> aware datetime."""
    if not text:
        return None
    raw = text.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(f"Cannot read date/time '{text}'. Use e.g. 2026-09-26 or 2026-09-26T14:00.")
    if len(raw) == 10 and end_of_day:
        dt = dt + timedelta(days=1) - timedelta(microseconds=1)
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive = local time
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def uri_to_path(uri):
    if not isinstance(uri, str):
        if isinstance(uri, dict):
            return uri.get("fsPath") or uri.get("path") or ""
        return ""
    if not uri.startswith("file:"):
        return uri
    path = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
    if re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return path


def norm_path(p):
    if not p:
        return ""
    p = uri_to_path(p) if str(p).startswith("file:") else str(p)
    if re.match(r"^/[A-Za-z]:", p):
        p = p[1:]
    return os.path.normcase(os.path.normpath(p)).rstrip("\\/")


def encode_claude_dir(path):
    """Claude Code names a project's log folder by replacing every non-alphanumeric char with '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path.rstrip("/\\"))


def iter_jsonl(path):
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def content_blocks(msg):
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, list):
        return [b for b in c if isinstance(b, dict)]
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return []


def block_text(blocks):
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text" and b.get("text")).strip()


def truncate(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def read_frontmatter_version(skill_md):
    try:
        with open(skill_md, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(6000)
    except OSError:
        return None
    m = re.match(r"^---\s*\n(.*?)\n---", head, re.S)
    if not m:
        return None
    v = re.search(r"^\s*version:\s*['\"]?([^'\"\n]+)", m.group(1), re.M)
    return v.group(1).strip() if v else None


class Redactor:
    """Masks likely secrets in text that ends up in a shareable report."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.by_kind = Counter()

    def __call__(self, text):
        if not self.enabled or not text:
            return text
        for kind, rx in SECRET_PATTERNS:
            text, n = rx.subn(f"[REDACTED:{kind}]", text)
            self.by_kind[kind] += n
        text, n = BEARER_RE.subn(lambda m: m.group(1) + "[REDACTED:bearer]", text)
        self.by_kind["bearer"] += n
        text, n = ASSIGNMENT_RE.subn(lambda m: m.group(1) + m.group(2) + "[REDACTED:value]", text)
        self.by_kind["assignment"] += n
        return text

    def summary(self):
        kinds = {k: v for k, v in self.by_kind.items() if v}
        return {"count": sum(kinds.values()), "by_kind": kinds}


def strip_inline_code(cmd):
    """Drop heredoc bodies and PowerShell here-strings from a command."""
    cmd = HEREDOC_RE.sub("\n", cmd or "")
    return HERESTRING_RE.sub("''", cmd)


def split_segments(cmd):
    """Split a command line on ; | & and newlines, but not inside quotes."""
    segs, buf, quote, i = [], [], None, 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(cmd):
                buf.append(cmd[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif c in ";\n|&":
            segs.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    segs.append("".join(buf))
    return segs


def executables(cmd):
    """Program names a shell command line runs (inline scripts ignored)."""
    out = []
    for seg in split_segments(strip_inline_code(cmd)):
        toks = seg.strip().lstrip("({!").strip().split()
        while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in (
                "sudo", "time", "exec", "nohup", "then", "do", "else", "elif", "!", "&", "call", "{", "(")):
            toks.pop(0)
        if not toks:
            continue
        if toks[0][0] in "'\"" and not toks[0].endswith(toks[0][0]):
            # A quoted program path with spaces, e.g. "C:\Program Files\nodejs\node.exe".
            quote = toks[0][0]
            joined = [toks.pop(0)]
            while toks and not joined[-1].endswith(quote):
                joined.append(toks.pop(0))
            toks.insert(0, " ".join(joined))
        exe = toks[0].strip("'\"`")
        if not exe or exe[0] in "$-#)}[<>0123456789" or exe in ("fi", "done", "esac", "end", "}"):
            continue
        exe = re.split(r"[\\/]", exe)[-1]
        exe = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", exe, flags=re.I)
        if not EXE_NAME_RE.match(exe) or exe in CODE_KEYWORDS:
            continue
        low = exe.lower()
        if low in ("python", "python3", "py") and len(toks) > 2 and toks[1] == "-m":
            exe = f"python -m {toks[2]}"
        elif low in ("npx", "pnpx", "bunx", "uvx") and len(toks) > 1:
            pkg = next((t for t in toks[1:] if not t.startswith("-")), None)
            if pkg:
                exe = f"{low} {pkg}"
        out.append(exe)
    return out


@functools.lru_cache(maxsize=None)
def on_path(name):
    return shutil.which(name) is not None


def exe_category(name):
    base = name.split()[0]
    if base.lower() in SHELL_UTILITIES:
        return "shell utility"
    if re.match(r"^[A-Z][A-Za-z]+-[A-Z][A-Za-z]+$", base):
        return "PowerShell cmdlet"
    if base.lower() in ("python", "python3", "py") and " -m " in f" {name} ":
        return "python module"
    # Shell functions, aliases, script names and parsing noise are not on the PATH.
    return "program" if on_path(base) else "not on PATH now"


def powershell_variables(cmd):
    """Simple `$name = 'literal'` and `$name = Join-Path $env:USERPROFILE 'rel'` assignments."""
    home = os.path.expanduser("~")
    values = {}
    for m in re.finditer(r"\$(\w+)\s*=\s*(?:(Join-Path)\s+\$env:USERPROFILE\s+)?(['\"])([^'\"\n]+)\3", cmd):
        values[m.group(1)] = os.path.join(home, m.group(4)) if m.group(2) else m.group(4)
    return values


def shell_write_targets(cmd):
    """Files a shell command line writes: redirections, sed -i, tee, PowerShell writers, cp/mv."""
    targets = []
    variables = powershell_variables(cmd)
    for m in re.finditer(r"WriteAll(?:Text|Lines|Bytes)\(\s*(['\"]?)([^,'\")]+)\1\s*,", cmd):
        targets.append(m.group(2))
    for seg in split_segments(strip_inline_code(cmd)):
        s = seg.strip()
        quote, i = None, 0
        while i < len(s):
            c = s[i]
            if quote:
                if c == quote:
                    quote = None
            elif c in "'\"":
                quote = c
            elif c == ">":
                j = i + 1 + (1 if s[i + 1:i + 2] == ">" else 0)
                while j < len(s) and s[j] == " ":
                    j += 1
                if j < len(s) and s[j] in "'\"":
                    k = s.find(s[j], j + 1)
                    k = k if k > j else len(s)
                    targets.append(s[j + 1:k])
                else:
                    k = j
                    while k < len(s) and s[k] not in " \t)":
                        k += 1
                    targets.append(s[j:k])
                i = k
            i += 1
        toks = s.split()
        if not toks:
            continue
        head = toks[0]
        if head == "sed" and any(t.startswith("-i") or t == "--in-place" for t in toks[1:]):
            targets.append(toks[-1])
        elif head == "tee":
            targets += [t for t in toks[1:] if not t.startswith("-")][:1]
        elif head in ("cp", "mv", "Copy-Item", "Move-Item") and len(toks) > 2:
            targets.append(toks[-1])
        else:
            # PowerShell writers can sit after an assignment or a pipe, so look anywhere in the segment.
            m = re.search(r"\b(?:Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|Copy-Item)\b[^|]*?"
                          r"-(?:LiteralPath|FilePath|Path|Destination)\s+(\"[^\"]+\"|'[^']+'|\S+)", s)
            if m:
                targets.append(m.group(1))
            elif head in ("Set-Content", "Add-Content", "Out-File") or (head == "New-Item" and "Directory" not in s):
                pos = [t for t in toks[1:] if not t.startswith("-")]
                targets.append(pos[0] if pos else "")
    clean = []
    for t in targets:
        t = t.strip().strip("'\"")
        if t.startswith("$") and t[1:] in variables:
            t = variables[t[1:]]
        if not t or "$" in t or t.startswith("&") or t.lower() in ("nul", "/dev/null", "/dev/stderr", "/dev/stdout"):
            continue
        if t not in clean:
            clean.append(t)
    return clean


def find_installs(cmd):
    found = []
    body = strip_inline_code(cmd)
    for manager, pattern in INSTALL_PATTERNS:
        for m in re.finditer(pattern, body):
            pkgs = []
            for tok in m.group(1).split():
                if tok.startswith(("-", ">", "2>", "<")) or tok in ("&", "1", "2"):
                    if tok.startswith((">", "2>")):
                        break
                    continue
                pkgs.append(tok.strip("'\""))
            found.append((manager, pkgs[:12]))
    return found


def imports_in(path, text):
    """(language, top-level module) pairs imported by code the AI wrote."""
    ext = os.path.splitext(path or "")[1].lower()
    res = []
    if not text:
        return res
    if ext == ".py":
        for m in re.finditer(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))", text, re.M):
            mod = (m.group(1) or m.group(2)).split(".")[0]
            if mod and not mod.startswith("_"):
                res.append(("python", mod + (" (stdlib)" if mod in PY_STDLIB else "")))
    elif ext in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte"):
        for m in re.finditer(r"""(?:from\s+|require\(\s*|import\s*\(\s*|^\s*import\s+)['"]([^'"]+)['"]""", text, re.M):
            mod = m.group(1)
            if mod.startswith((".", "/", "~", "@/")):
                continue
            mod = "/".join(mod.split("/")[:2]) if mod.startswith("@") else mod.split("/")[0]
            name = mod.replace("node:", "")
            res.append(("javascript", mod + (" (built-in)" if name in NODE_BUILTINS or mod.startswith("node:") else "")))
    elif ext in (".java", ".kt", ".scala"):
        for m in re.finditer(r"^\s*import\s+(?:static\s+)?([a-z][\w]*\.[\w]+)", text, re.M):
            res.append(("jvm", m.group(1)))
    elif ext == ".cs":
        for m in re.finditer(r"^\s*using\s+([A-Z][\w]*(?:\.[\w]+)?)\s*;", text, re.M):
            res.append(("dotnet", m.group(1)))
    elif ext == ".go":
        for m in re.finditer(r'"([a-z0-9.-]+\.[a-z]+/[^"]+)"', text):
            res.append(("go", "/".join(m.group(1).split("/")[:3])))
    return res


class Window:
    def __init__(self, since=None, until=None):
        self.since, self.until = since, until

    @property
    def active(self):
        return bool(self.since or self.until)

    def contains(self, ts):
        if ts is None:
            return not self.active
        if self.since and ts < self.since:
            return False
        if self.until and ts > self.until:
            return False
        return True


# ----------------------------------------------------------------------------- collector

class Collector:
    """Accumulates everything measured across the selected sessions."""

    def __init__(self, target, redactor):
        self.target = target
        self.redact = redactor
        self.sessions = []
        self.segments = []
        self.events = []
        self.usage = {}
        self.turns = Counter()
        self.model_names = {}
        self.effort = Counter()
        self.speed = Counter()
        self.service_tier = Counter()
        self.permission_modes = Counter()
        self.plan_mode_turns = 0
        self.auto_mode = False
        self.codex_approval = Counter()
        self.codex_sandbox = Counter()
        self.collab_modes = Counter()
        self.copilot_modes = Counter()
        self.copilot_requests = []
        self.thinking_blocks = 0
        self.peak_context = 0
        self.peak_context_model = None
        self.context_windows = Counter()
        self.compactions = []
        self.instruction_files = {}
        self.hooks = Counter()
        self.skill_uses = Counter()
        self.skill_sources = {}
        self.mcp = defaultdict(Counter)
        self.agents = []
        self.agent_calls = Counter()
        self.tool_calls = Counter()
        self.executables = Counter()
        self.installs = []
        self.imports = defaultdict(Counter)
        self.web_searches = []
        self.web_domains = Counter()
        self.files_written = defaultdict(Counter)
        self.files_read = set()
        self.external_edits = Counter()
        self.git_commits = []
        self.pull_requests = []
        self.command_count = 0
        self.tool_errors = 0
        self.api_errors = 0
        self.interruptions = 0
        self.denials = Counter()
        self.questions_asked = 0
        self.plans_presented = 0
        self.local_command_output = []
        self.reported_costs = []
        self.harness = Counter()
        self.entrypoints = Counter()
        self.git_branches = Counter()
        self.environment = {}
        self.sources_used = set()
        self.billing_hints = set()
        self.approvals = []
        self.warnings = []
        self.data_gaps = []

    # -- recording helpers
    def gap(self, text):
        if text not in self.data_gaps:
            self.data_gaps.append(text)

    def add_usage(self, source, model, scope, counter, turns=1):
        key = (source, model or "unknown", scope)
        self.usage.setdefault(key, Counter()).update(counter)
        self.turns[key] += turns

    def new_segment(self, source, session_id, ts, text, kind=None):
        clean = self.redact(text)
        if kind is None and len(clean) < 40 and CONTINUE_RE.match(clean.strip()):
            kind = "continue"
        seg = {
            "source": source, "session_id": session_id, "ts": ts, "end_ts": ts,
            "prompt": truncate(clean, PROMPT_LIMIT), "chars": len(text), "kind": kind,
            "tools": Counter(), "commands": [], "command_count": 0, "files": [], "skills": [],
            "subagents": [], "errors": 0, "denials": 0, "interrupted": False, "reply": "",
            "notes": [], "questions": [], "error_details": [], "approvals": [],
        }
        self.segments.append(seg)
        return seg

    def add_note(self, seg, text):
        """An AI progress message, kept short, for the timeline."""
        text = (text or "").strip()
        if seg is None or not text:
            return
        seg["reply"] = text
        if len(seg["notes"]) < 40:
            seg["notes"].append(truncate(self.redact(re.sub(r"\s+", " ", text)), 220))

    def add_error(self, seg, content):
        self.tool_errors += 1
        if seg is None:
            return
        seg["errors"] += 1
        if len(seg["error_details"]) < 5:
            text = content if isinstance(content, str) else " ".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict))
            line = first_line(re.sub(r"</?tool_use_error>", "", text or ""))
            if line:
                seg["error_details"].append(truncate(self.redact(line), 160))

    def add_command(self, cmd, seg, ts=None):
        if not cmd:
            return
        self.command_count += 1
        for exe in executables(cmd):
            self.executables[exe] += 1
        for manager, pkgs in find_installs(cmd):
            self.installs.append({"manager": manager, "packages": pkgs,
                                  "command": truncate(self.redact(first_line(cmd)), 160)})
        if re.search(r"\bgit\b[^\n]*\bcommit\b", cmd):
            msg = None
            m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n", cmd, re.S)
            if m:
                msg = first_line(m.group(2))
            if not msg:
                m = re.search(r"-m\s+(?:\"((?:[^\"\\]|\\.)*)\"|'([^']*)'|(\S+))", cmd)
                if m:
                    msg = first_line(m.group(1) or m.group(2) or m.group(3))
            if msg and not msg.startswith("$("):
                self.git_commits.append({"message": truncate(self.redact(msg), 160), "ts": iso(ts)})
        if re.search(r"\bgh\s+pr\s+create\b", cmd):
            m = re.search(r"--title\s+(?:\"([^\"]*)\"|'([^']*)')", cmd)
            self.pull_requests.append({"title": (m.group(1) or m.group(2)) if m else None, "ts": iso(ts)})
        for target in shell_write_targets(cmd):
            self.add_file_write(target, "shell", "", seg)
        if seg is not None:
            seg["command_count"] += 1
            if len(seg["commands"]) < COMMANDS_PER_PROMPT:
                seg["commands"].append(truncate(self.redact(first_line(strip_inline_code(cmd)) or first_line(cmd)), 160))

    def add_file_write(self, path, tool, text, seg):
        if not path:
            return
        self.files_written[path][tool] += 1
        for lang, mod in imports_in(path, text):
            self.imports[lang][mod] += 1
        if seg is not None and path not in seg["files"]:
            seg["files"].append(path)

    def tool_use(self, name, inp, seg, ts=None):
        """Record one Claude Code tool call."""
        inp = inp if isinstance(inp, dict) else {}
        self.tool_calls[name] += 1
        if seg is not None:
            seg["tools"][name] += 1
        if name.startswith("mcp__"):
            parts = name[5:].split("__", 1)
            self.mcp[parts[0]][parts[1] if len(parts) > 1 else "?"] += 1
        elif name == "Skill":
            skill = str(inp.get("skill") or inp.get("name") or "?")
            self.skill_uses[skill] += 1
            if seg is not None and skill not in seg["skills"]:
                seg["skills"].append(skill)
        elif name in ("Agent", "Task"):
            kind = str(inp.get("subagent_type") or "general-purpose")
            self.agent_calls[kind] += 1
            if seg is not None:
                seg["subagents"].append(truncate(f"{kind}: {inp.get('description') or ''}".strip(": "), 120))
        elif name in ("Bash", "PowerShell", "BashOutput"):
            if name != "BashOutput":
                self.add_command(inp.get("command") or "", seg, ts)
        elif name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            path = inp.get("file_path") or inp.get("notebook_path")
            text = inp.get("content") or inp.get("new_string") or inp.get("new_source") or ""
            if name == "MultiEdit":
                text = "\n".join(e.get("new_string", "") for e in inp.get("edits") or [] if isinstance(e, dict))
            self.add_file_write(path, name, text, seg)
        elif name in ("Read", "NotebookRead"):
            if inp.get("file_path"):
                self.files_read.add(inp["file_path"])
        elif name == "WebSearch":
            if inp.get("query"):
                self.web_searches.append(truncate(self.redact(str(inp["query"])), 160))
        elif name == "WebFetch":
            host = urllib.parse.urlparse(str(inp.get("url") or "")).netloc
            if host:
                self.web_domains[host] += 1
        elif name == "ExitPlanMode":
            self.plans_presented += 1
        elif name == "AskUserQuestion":
            self.questions_asked += 1
            if seg is not None:
                qs = [q.get("question", "") for q in inp.get("questions") or [] if isinstance(q, dict)]
                seg["questions"].append({"question": truncate(self.redact(" / ".join(qs)), 300), "answer": None})

    def touch(self, ts):
        if ts:
            self.events.append(ts)


# ----------------------------------------------------------------------------- Claude Code

def claude_usage(u):
    u = u or {}
    cc = u.get("cache_creation") or {}
    stu = u.get("server_tool_use") or {}
    otd = u.get("output_tokens_details") or {}
    return Counter({
        "input": u.get("input_tokens") or 0,
        "output": u.get("output_tokens") or 0,
        "cache_read": u.get("cache_read_input_tokens") or 0,
        "cache_write": u.get("cache_creation_input_tokens") or 0,
        "cache_write_5m": cc.get("ephemeral_5m_input_tokens") or 0,
        "cache_write_1h": cc.get("ephemeral_1h_input_tokens") or 0,
        "thinking": otd.get("thinking_tokens") or 0,
        "web_search": stu.get("web_search_requests") or 0,
        "web_fetch": stu.get("web_fetch_requests") or 0,
    })


def merge_max(target, new):
    for k, v in new.items():
        if v > target.get(k, 0):
            target[k] = v


def strip_injected(text):
    text = INJECTED_BLOCKS.sub("", text or "")
    # Pasted text keeps its content; only the wrapper tags go.
    text = re.sub(r"</?pasted_content[^>]*>", "", text)
    return text.strip()


def classify_claude_prompt(rec, blocks, text):
    """(prompt text, kind) when this user record is something the person typed, else None."""
    if rec.get("isMeta") or rec.get("isSidechain") or rec.get("isCompactSummary") \
            or rec.get("isVisibleInTranscriptOnly"):
        return None
    if any(b.get("type") == "tool_result" for b in blocks):
        return None
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None
    raw = (text or "").strip()
    if not raw:
        return None
    if "<command-name>" in raw[:400]:
        name = re.search(r"<command-name>(.*?)</command-name>", raw, re.S)
        args = re.search(r"<command-args>(.*?)</command-args>", raw, re.S)
        cmd = (name.group(1).strip() if name else "").strip() or "?"
        if not cmd.startswith("/"):
            cmd = "/" + cmd
        return (cmd + " " + (args.group(1).strip() if args else "")).strip(), "slash-command"
    if not isinstance(origin, dict) and raw.startswith(INJECTED_PREFIXES):
        return None
    if raw.startswith("[Request interrupted"):
        return None
    clean = strip_injected(raw)
    return (clean, None) if clean else None


class ClaudeReader:
    source = "claude-code"

    def __init__(self, col, window, scope="main", session_id=None):
        self.col = col
        self.window = window
        self.scope = scope
        self.session_id = session_id
        self.msgs = {}
        self.seg = None
        self.last_ts = None
        self.last_assistant_ts = None
        self.cost_states = []
        self.pending_questions = {}
        self.info = None

    def read(self, path):
        sid = self.session_id or os.path.splitext(os.path.basename(path))[0]
        self.session_id = sid
        self.info = {"source": self.source, "session_id": sid, "file": path, "title": None,
                     "first_ts": None, "last_ts": None, "prompt_count": 0, "first_prompt": None}
        col = self.col
        for rec in iter_jsonl(path):
            rtype = rec.get("type")
            if rtype == "ai-title":
                self.info["title"] = rec.get("aiTitle") or self.info["title"]
                continue
            if rtype == "cost-state":
                self.cost_states.append((rec, self.last_ts))
                continue
            ts = parse_ts(rec.get("timestamp"))
            if ts:
                self.last_ts = ts
            if rtype not in ("user", "assistant", "attachment", "system"):
                continue
            if not self.window.contains(ts):
                continue
            if ts:
                col.touch(ts)
                if self.info["first_ts"] is None or ts < self.info["first_ts"]:
                    self.info["first_ts"] = ts
                if self.info["last_ts"] is None or ts > self.info["last_ts"]:
                    self.info["last_ts"] = ts
            seg_before = self.seg
            if rec.get("quotaLimits"):
                col.billing_hints.add("subscription plan with usage limits (rate-limit events in the log)")
            if rec.get("version"):
                col.harness[("Claude Code", rec["version"])] += 1
            if rec.get("entrypoint"):
                col.entrypoints[rec["entrypoint"]] += 1
            if rec.get("gitBranch"):
                col.git_branches[rec["gitBranch"]] += 1
            if rtype == "user":
                self._user(rec, ts)
            elif rtype == "assistant":
                self._assistant(rec, ts)
            elif rtype == "attachment":
                self._attachment(rec)
            elif rtype == "system":
                self._system(rec, ts)
            # A prompt's activity ends with the last event before the next prompt.
            if ts and seg_before is not None and self.seg is seg_before and ts > seg_before["end_ts"]                     and (ts - seg_before["end_ts"]).total_seconds() <= IDLE_GAP_SECONDS:
                seg_before["end_ts"] = ts
        self._finish_usage()
        return self.info

    def _user(self, rec, ts):
        col = self.col
        if rec.get("permissionMode") and self.scope == "main":
            col.permission_modes[rec["permissionMode"]] += 1
        if rec.get("toolDenialKind"):
            col.denials[rec["toolDenialKind"]] += 1
            if self.seg is not None:
                self.seg["denials"] += 1
        blocks = content_blocks(rec.get("message") or {})
        for b in blocks:
            if b.get("type") != "tool_result":
                continue
            if b.get("is_error"):
                col.add_error(self.seg, b.get("content"))
            elif b.get("tool_use_id") in self.pending_questions:
                # The human's answer to an AskUserQuestion: a decision, not a typed prompt.
                q = self.pending_questions.pop(b["tool_use_id"])
                content = b.get("content")
                text = content if isinstance(content, str) else " ".join(
                    x.get("text", "") for x in content or [] if isinstance(x, dict))
                q["answer"] = truncate(col.redact(re.sub(r"\s+", " ", text or "")), 300)
        if self.scope != "main":
            return
        text = block_text(blocks)
        if text.startswith("[Request interrupted"):
            col.interruptions += 1
            if self.seg is not None:
                self.seg["interrupted"] = True
            return
        if text.startswith("<local-command-stdout>"):
            out = re.sub(r"</?local-command-stdout>", "", text).strip()
            if out and len(col.local_command_output) < 40:
                col.local_command_output.append({"ts": iso(ts), "text": truncate(col.redact(out), 200)})
            return
        found = classify_claude_prompt(rec, blocks, text)
        if not found:
            return
        prompt, kind = found
        self.seg = col.new_segment(self.source, self.session_id, ts, prompt, kind)
        self.info["prompt_count"] += 1
        if self.info["first_prompt"] is None:
            self.info["first_prompt"] = truncate(col.redact(prompt), 160)

    def _assistant(self, rec, ts):
        col = self.col
        msg = rec.get("message") or {}
        model = msg.get("model")
        if rec.get("isApiErrorMessage"):
            col.api_errors += 1
        if model and model != "<synthetic>":
            # Claude Code writes one record per content block and repeats the usage on each,
            # so usage is merged per API message id rather than summed per record.
            key = msg.get("id") or rec.get("requestId") or rec.get("uuid")
            m = self.msgs.setdefault(key, {"model": model, "u": Counter(), "effort": None,
                                           "speed": None, "tier": None})
            u = msg.get("usage") or {}
            merge_max(m["u"], claude_usage(u))
            m["speed"] = u.get("speed") or m["speed"]
            m["tier"] = u.get("service_tier") or m["tier"]
            m["effort"] = rec.get("effort") or m["effort"]
            if ts:
                self.last_assistant_ts = ts
        for b in content_blocks(msg):
            bt = b.get("type")
            if bt in ("thinking", "redacted_thinking"):
                col.thinking_blocks += 1
            elif bt == "text" and self.scope == "main":
                col.add_note(self.seg, b.get("text"))
            elif bt == "tool_use":
                col.tool_use(b.get("name", "?"), b.get("input"), self.seg, ts)
                if b.get("name") == "AskUserQuestion" and self.seg is not None and self.seg["questions"]:
                    self.pending_questions[b.get("id")] = self.seg["questions"][-1]

    def _attachment(self, rec):
        col = self.col
        a = rec.get("attachment") or {}
        t = a.get("type")
        if t == "model":
            ident = a.get("identity") or {}
            if ident.get("modelId"):
                col.model_names[ident["modelId"]] = ident.get("marketingName") or ident["modelId"]
        elif t == "instructions":
            for f in a.get("files") or []:
                if isinstance(f, dict) and f.get("path"):
                    col.instruction_files[f["path"]] = {"type": f.get("type"),
                                                        "chars": len(f.get("content") or "")}
        elif t and t.startswith("hook_") and a.get("hookEvent") and a.get("command"):
            col.hooks[(a["hookEvent"], a["command"])] += 1
        elif t == "invoked_skills":
            for s in a.get("skills") or []:
                if isinstance(s, dict) and s.get("name"):
                    col.skill_sources.setdefault(s["name"], s.get("path"))
        elif t == "plan_mode" and self.scope == "main":
            col.plan_mode_turns += 1
        elif t == "auto_mode":
            col.auto_mode = True
        elif t == "environment":
            col.environment = a.get("snapshot") or col.environment
        elif t == "edited_text_file" and a.get("filename"):
            col.external_edits[a["filename"]] += 1

    def _system(self, rec, ts):
        if rec.get("subtype") == "compact_boundary":
            md = rec.get("compactMetadata") or {}
            self.col.compactions.append({"ts": iso(ts), "trigger": md.get("trigger"),
                                         "pre_tokens": md.get("preTokens"), "source": self.source})

    def _finish_usage(self):
        col = self.col
        per_model = defaultdict(Counter)
        turns = Counter()
        for m in self.msgs.values():
            per_model[m["model"]].update(m["u"])
            turns[m["model"]] += 1
            if m["effort"]:
                col.effort[m["effort"]] += 1
            if m["speed"]:
                col.speed[m["speed"]] += 1
            if m["tier"]:
                col.service_tier[m["tier"]] += 1
            if self.scope == "main":
                ctx = m["u"]["input"] + m["u"]["cache_read"] + m["u"]["cache_write"]
                if ctx > col.peak_context:
                    col.peak_context, col.peak_context_model = ctx, m["model"]
        for model, counter in per_model.items():
            col.add_usage(self.source, model, self.scope, counter, turns[model])
        self.output_tokens = sum(c["output"] for c in per_model.values())
        self.models = dict(turns)


def find_claude_sessions(target, projects_dir):
    """Main transcripts for a folder: exact encoded dir name, else match on logged cwd."""
    if not os.path.isdir(projects_dir):
        return []
    encoded = encode_claude_dir(target).lower()
    dirs = [os.path.join(projects_dir, d) for d in os.listdir(projects_dir) if d.lower() == encoded]
    if not dirs:
        want = norm_path(target)
        for d in os.listdir(projects_dir):
            full = os.path.join(projects_dir, d)
            sample = sorted(glob.glob(os.path.join(full, "*.jsonl")))[:1]
            for rec in (itertools.islice(iter_jsonl(sample[0]), 50) if sample else []):
                if rec.get("cwd"):
                    if norm_path(rec["cwd"]) == want:
                        dirs.append(full)
                    break
    files = []
    for d in dirs:
        files.extend(sorted(glob.glob(os.path.join(d, "*.jsonl"))))
    return files


def read_claude(path, col, window, with_subagents=True):
    reader = ClaudeReader(col, window)
    info = reader.read(path)
    col.sources_used.add("claude-code")
    sid = info["session_id"]
    sub_out = 0
    sub_dir = os.path.join(os.path.dirname(path), sid, "subagents")
    sub_files = sorted(glob.glob(os.path.join(sub_dir, "*.jsonl")))
    info["subagent_count"] = len(sub_files)
    if with_subagents:
        for sf in sub_files:
            meta = load_json(sf[:-len(".jsonl")] + ".meta.json") or {}
            sub = ClaudeReader(col, window, scope="subagent", session_id=sid)
            sub.read(sf)
            if not sub.msgs:
                continue
            sub_out += sub.output_tokens
            col.agents.append({
                "session_id": sid,
                "agent_id": os.path.basename(sf)[:-len(".jsonl")],
                "type": meta.get("agentType") or "unknown",
                "description": meta.get("description"),
                "depth": meta.get("spawnDepth"),
                "models": sub.models,
                "output_tokens": sub.output_tokens,
            })
    # Claude Code's own cost figure. It is a running total written now and then, so the
    # session may have continued after the last one; compare it with the transcript.
    if reader.cost_states:
        rec, covered_until = reader.cost_states[-1]
        mu = rec.get("modelUsage") or {}
        reported_out = sum((v or {}).get("outputTokens", 0) for v in mu.values())
        seen_out = reader.output_tokens + sub_out
        ratio = (reported_out / seen_out) if seen_out else None
        col.reported_costs.append({
            "session_id": sid,
            "total_usd": rec.get("totalCostUSD"),
            "by_model": {m: (v or {}).get("costUSD") for m, v in mu.items()},
            "output_tokens_reported": reported_out,
            "output_tokens_in_transcript": seen_out,
            "coverage_ratio": round(ratio, 3) if ratio is not None else None,
            "activity_after": bool(reader.last_assistant_ts and covered_until
                                   and reader.last_assistant_ts > covered_until),
            "lines_added": rec.get("totalLinesAdded"),
            "lines_removed": rec.get("totalLinesRemoved"),
            "api_seconds": round((rec.get("totalAPIDuration") or 0) / 1000),
            "unknown_model_cost": rec.get("hasUnknownModelCost"),
            "window_applied": window.active,
        })
    return info


# ----------------------------------------------------------------------------- Codex (best effort)

CODEX_CHILDREN = defaultdict(list)  # parent thread id -> files of sessions Codex started itself


def codex_session_meta(path):
    for i, rec in enumerate(iter_jsonl(path)):
        if rec.get("type") == "session_meta":
            return rec.get("payload") or {}
        if i > 5:
            break
    return {}


def find_codex_sessions(target, codex_home):
    """Codex sessions run in the folder. Sessions Codex started itself (guardian reviews, helper
    agents) carry a parent_thread_id; they are kept aside and read as sub-agents of their parent."""
    want = norm_path(target)
    files = glob.glob(os.path.join(codex_home, "sessions", "**", "*.jsonl"), recursive=True)
    files += glob.glob(os.path.join(codex_home, "archived_sessions", "**", "*.jsonl"), recursive=True)
    mains = []
    for f in sorted(files):
        meta = codex_session_meta(f)
        if norm_path(meta.get("cwd")) != want:
            continue
        if meta.get("parent_thread_id"):
            CODEX_CHILDREN[meta["parent_thread_id"]].append(f)
        else:
            mains.append(f)
    return mains


def codex_prompt_text(text):
    t = (text or "").strip()
    if "## My request for Codex:" in t:
        t = t.split("## My request for Codex:", 1)[1].strip()
    elif t.startswith("# Files pasted by the user:"):
        # Codex keeps pasted text as an attachment file and logs only a reference to it.
        parts = []
        for m in re.finditer(r"^## .*?: (\S+\.(?:txt|md))\s*$", t, re.M):
            try:
                with open(m.group(1), encoding="utf-8", errors="replace") as fh:
                    parts.append(fh.read(PROMPT_LIMIT).strip())
            except OSError:
                parts.append(f"[pasted text, file no longer available: {m.group(1)}]")
        request = t.split("## My request:", 1)[1].strip() if "## My request:" in t else ""
        t = "\n\n".join(x for x in parts + [request] if x)
    if not t or t.startswith(("<", "# AGENTS.md", "# Context from my IDE")):
        return None
    return t


def codex_commands(name, payload):
    """Shell commands inside a Codex tool call (several call shapes exist)."""
    cmds = []
    raw = payload.get("arguments") if "arguments" in payload else payload.get("input")
    args = None
    if isinstance(raw, str):
        try:
            args = json.loads(raw)
        except ValueError:
            args = None
    if isinstance(args, dict):
        c = args.get("command") or args.get("cmd")
        if isinstance(c, list):
            c = " ".join(str(x) for x in c)
            c = re.sub(r"^(bash|sh|powershell(\.exe)?|pwsh)\s+(-lc|-c|-Command)\s+", "", c)
        if isinstance(c, str):
            cmds.append(c)
    elif isinstance(raw, str):
        # Codex "exec" calls carry JavaScript such as tools.exec_command({cmd:"..."}).
        for m in re.finditer(r'["\']?\b(?:cmd|command)["\']?\s*:\s*"((?:[^"\\]|\\.)*)"', raw):
            try:
                cmds.append(json.loads('"' + m.group(1) + '"'))
            except ValueError:
                cmds.append(m.group(1))
    action = payload.get("action") or {}
    if isinstance(action, dict) and isinstance(action.get("command"), list):
        cmds.append(" ".join(str(x) for x in action["command"]))
    return cmds


def read_codex(path, col, window, scope="main", with_children=True):
    col.sources_used.add("codex")
    sid = os.path.splitext(os.path.basename(path))[0]
    info = {"source": "codex", "session_id": sid, "file": path, "title": None, "first_ts": None,
            "last_ts": None, "prompt_count": 0, "first_prompt": None, "subagent_count": 0}
    meta = codex_session_meta(path)
    children = CODEX_CHILDREN.get(meta.get("id") or meta.get("session_id"), []) if scope == "main" else []
    info["subagent_count"] = len(children)
    models = Counter()
    # Codex logs running totals after each response. The difference between two totals belongs
    # to the model of the current turn, which splits the tokens per model exactly.
    per_model = defaultdict(Counter)
    responses = Counter()
    prev_total = None
    current_model = None
    seg = None
    seen_prompts = set()
    for rec in iter_jsonl(path):
        ts = parse_ts(rec.get("timestamp"))
        t = rec.get("type")
        p = rec.get("payload") or {}
        if t == "turn_context" and p.get("model") and p["model"] != current_model:
            if current_model and scope == "main" and window.contains(ts):
                col.local_command_output.append({"ts": iso(ts), "text": f"Codex model switched from "
                                                 f"{current_model} to {p['model']}"})
            current_model = p["model"]
        if t == "event_msg" and p.get("type") == "token_count":
            tot = (p.get("info") or {}).get("total_token_usage")
            if tot and tot != prev_total:
                if window.contains(ts):
                    base = prev_total or {}

                    def delta(k):
                        return max(0, (tot.get(k) or 0) - (base.get(k) or 0))

                    cached = delta("cached_input_tokens")
                    model = current_model or "unknown"
                    per_model[model].update({
                        "input": max(0, delta("input_tokens") - cached), "cache_read": cached,
                        "cache_write": delta("cache_write_input_tokens"), "output": delta("output_tokens"),
                        "thinking": delta("reasoning_output_tokens")})
                    responses[model] += 1
                    last = (p.get("info") or {}).get("last_token_usage") or {}
                    if scope == "main" and (last.get("input_tokens") or 0) > col.peak_context:
                        col.peak_context = last.get("input_tokens") or 0
                        col.peak_context_model = model
                prev_total = tot
            cw = (p.get("info") or {}).get("model_context_window")
            if isinstance(cw, int):
                col.context_windows[cw] += 1
            continue
        if t == "session_meta":
            col.harness[("Codex", p.get("cli_version") or "?")] += 1
            col.entrypoints[p.get("originator") or p.get("source") or "codex"] += 1
            if (p.get("git") or {}).get("branch"):
                col.git_branches[p["git"]["branch"]] += 1
            cw = p.get("context_window")
            if isinstance(cw, dict):
                cw = cw.get("context_window") or cw.get("max_tokens") or cw.get("tokens")
            if isinstance(cw, int):
                col.context_windows[cw] += 1
            continue
        if not window.contains(ts):
            continue
        is_user_turn = (t == "event_msg" and p.get("type") == "user_message") or             (t == "response_item" and p.get("type") == "message" and p.get("role") == "user")
        if ts:
            col.touch(ts)
            info["first_ts"] = info["first_ts"] or ts
            info["last_ts"] = ts
            if seg is not None and not is_user_turn and ts > seg["end_ts"] and                     (ts - seg["end_ts"]).total_seconds() <= IDLE_GAP_SECONDS:
                seg["end_ts"] = ts  # a longer silence is the human away, not the AI busy
        if t == "turn_context":
            if p.get("model"):
                models[p["model"]] += 1
            if p.get("effort"):
                col.effort[p["effort"]] += 1
            if p.get("approval_policy"):
                col.codex_approval[str(p["approval_policy"])] += 1
            sb = p.get("sandbox_policy")
            if isinstance(sb, dict) and sb.get("type"):
                col.codex_sandbox[sb["type"]] += 1
            mode = (p.get("collaboration_mode") or {}).get("mode")
            if mode:
                col.collab_modes[mode] += 1
        elif t == "compacted":
            col.compactions.append({"ts": iso(ts), "trigger": None, "pre_tokens": None, "source": "codex"})
        elif t == "event_msg":
            pt = p.get("type")
            if pt == "user_message" and isinstance(p.get("message"), str) and scope == "main":
                text = codex_prompt_text(p["message"])
                if text and text[:300] not in seen_prompts:
                    seen_prompts.add(text[:300])
                    seg = col.new_segment("codex", sid, ts, text)
                    info["prompt_count"] += 1
                    info["first_prompt"] = info["first_prompt"] or truncate(col.redact(text), 160)
            elif pt == "turn_aborted":
                col.interruptions += 1
                if seg is not None:
                    seg["interrupted"] = True
        elif t == "response_item":
            pt = p.get("type")
            if pt == "message":
                texts = [c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict)]
                text = "\n".join(x for x in texts if x).strip()
                if p.get("role") == "user" and scope == "main":
                    text = codex_prompt_text(text)
                    if text and text[:300] not in seen_prompts:
                        seen_prompts.add(text[:300])
                        seg = col.new_segment("codex", sid, ts, text)
                        info["prompt_count"] += 1
                        info["first_prompt"] = info["first_prompt"] or truncate(col.redact(text), 160)
                elif p.get("role") == "assistant" and text and scope == "main":
                    col.add_note(seg, text)
            elif pt == "reasoning":
                col.thinking_blocks += 1
            elif pt in ("function_call_output", "custom_tool_call_output"):
                out = p.get("output")
                out = out if isinstance(out, str) else json.dumps(out or "")
                m_exit = re.match(r"Exit code:\s*(-?\d+)", out)
                if m_exit and m_exit.group(1) != "0":
                    col.add_error(seg, f"exit code {m_exit.group(1)}: " + first_line(out.split("Output:", 1)[-1]))
            elif pt == "web_search_call":
                act = p.get("action") or {}
                if act.get("type") == "search" and (act.get("query") or act.get("queries")):
                    col.web_searches.append(truncate(col.redact(str(act.get("query") or act["queries"][0])), 160))
                elif act.get("url"):
                    host = urllib.parse.urlparse(str(act["url"])).netloc
                    if host:
                        col.web_domains[host] += 1
            elif pt in ("function_call", "custom_tool_call", "local_shell_call"):
                name = p.get("name") or pt
                col.tool_calls[name] += 1
                raw_args = p.get("arguments") if isinstance(p.get("arguments"), str) else ""
                if "require_escalated" in raw_args:
                    try:
                        just = json.loads(raw_args).get("justification")
                    except ValueError:
                        just = None
                    col.approvals.append({"ts": iso(ts), "what": truncate(col.redact(just or "command outside the sandbox"), 200)})
                    if seg is not None:
                        seg["approvals"].append(truncate(col.redact(just or "command outside the sandbox"), 160))
                if seg is not None:
                    seg["tools"][name] += 1
                if name.startswith("mcp__") or "__" in name:
                    server = name.replace("mcp__", "").split("__")[0]
                    col.mcp[server][name] += 1
                for cmd in codex_commands(name, p):
                    col.add_command(cmd, seg, ts)
                raw = p.get("input") if isinstance(p.get("input"), str) else p.get("arguments")
                if isinstance(raw, str):
                    # The patch may sit inside an escaped JS string, so "\n" can be literal.
                    for fm in re.finditer(r"\*\*\* (?:Add|Update|Delete) File: (.+?)(?=\\n|\n|\\\"|\"|$)", raw):
                        col.add_file_write(fm.group(1).strip().replace("\\\\", "\\"), "apply_patch", raw, seg)
    for model, counter in per_model.items():
        col.add_usage("codex", model, scope, counter, responses[model])
    if not per_model and models:
        col.add_usage("codex", models.most_common(1)[0][0], scope, Counter(), 0)
    if scope == "subagent":
        info["models"] = dict(responses) or dict(models)
        info["output_tokens"] = sum(int(c["output"]) for c in per_model.values())
        info["thread_source"] = meta.get("thread_source")
    if with_children:
        for child in children:
            ci = read_codex(child, col, window, scope="subagent", with_children=False)
            if ci.get("models") or ci.get("first_ts"):
                col.agents.append({
                    "session_id": sid, "agent_id": ci["session_id"],
                    "type": f"codex {ci.get('thread_source') or 'child session'}",
                    "description": "started by Codex itself, not by the user",
                    "depth": 1, "models": ci.get("models") or {}, "output_tokens": ci.get("output_tokens", 0),
                })
    return info


# ----------------------------------------------------------------------------- GitHub Copilot (best effort)

def vscode_user_dirs():
    eds = ("Code", "Code - Insiders", "VSCodium")
    home = os.path.expanduser("~")
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return [os.path.join(base, e, "User") for e in eds if os.path.isdir(os.path.join(base, e, "User"))]


def find_copilot_sessions(target, user_dirs):
    want = norm_path(target)
    files = []
    for ud in user_dirs:
        for wsj in glob.glob(os.path.join(ud, "workspaceStorage", "*", "workspace.json")):
            data = load_json(wsj) or {}
            folder = data.get("folder") or data.get("workspace") or ""
            if norm_path(uri_to_path(folder)) == want or \
                    (folder.endswith(".code-workspace") and norm_path(uri_to_path(folder)).startswith(want)):
                d = os.path.join(os.path.dirname(wsj), "chatSessions")
                files.extend(sorted(glob.glob(os.path.join(d, "*.json")) + glob.glob(os.path.join(d, "*.jsonl"))))
    return files


def replay_copilot_jsonl(path):
    """VS Code stores newer chat sessions as a mutation log: kind 0 = initial state,
    kind 1 = set value at key path k, kind 2 = append to the array at k, kind 3 = delete."""
    state = None
    for rec in iter_jsonl(path):
        kind = rec.get("kind")
        if kind == 0:
            state = rec.get("v")
            continue
        if not isinstance(state, (dict, list)):
            continue
        keys = rec.get("k") or []
        try:
            tgt = state
            for key in keys[:-1]:
                tgt = tgt[key]
            last = keys[-1] if keys else None
            if kind == 1 and last is not None:
                tgt[last] = rec.get("v")
            elif kind == 2:
                arr = tgt[last] if last is not None else tgt
                if isinstance(rec.get("i"), int):
                    del arr[rec["i"]:]
                v = rec.get("v")
                arr.extend(v if isinstance(v, list) else [v])
            elif kind == 3 and last is not None:
                del tgt[last]
        except (KeyError, IndexError, TypeError):
            continue
    return state if isinstance(state, dict) else None


def deep_numbers(obj, wanted, out=None, depth=0):
    out = out if out is not None else Counter()
    if depth > 6:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in wanted and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[wanted[k]] += int(v)
            elif isinstance(v, (dict, list)):
                deep_numbers(v, wanted, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            deep_numbers(v, wanted, out, depth + 1)
    return out


COPILOT_TOKEN_KEYS = {"promptTokens": "input", "inputTokens": "input", "prompt_tokens": "input",
                      "completionTokens": "output", "outputTokens": "output", "completion_tokens": "output",
                      "cachedTokens": "cache_read", "cached_tokens": "cache_read"}


def read_copilot_chat(path, col, window):
    data = replay_copilot_jsonl(path) if path.endswith(".jsonl") else load_json(path)
    if not isinstance(data, dict):
        return None
    requests = [r for r in data.get("requests") or [] if isinstance(r, dict)]
    sid = data.get("sessionId") or os.path.splitext(os.path.basename(path))[0]
    info = {"source": "copilot-vscode", "session_id": sid, "file": path,
            "title": data.get("customTitle") or data.get("computedTitle"), "first_ts": None,
            "last_ts": None, "prompt_count": 0, "first_prompt": None, "subagent_count": 0}
    col.sources_used.add("copilot-vscode")
    col.harness[("GitHub Copilot Chat", "version not logged")] += 1
    col.entrypoints["copilot-vscode"] += 1
    for req in requests:
        text = ((req.get("message") or {}).get("text") or "").strip()
        ts = parse_ts(req.get("timestamp"))
        if not text or not window.contains(ts):
            continue
        col.touch(ts)
        info["first_ts"] = info["first_ts"] or ts
        info["last_ts"] = ts
        result = req.get("result") or {}
        meta = result.get("metadata") or {}
        model = req.get("modelId") or meta.get("modelId") or meta.get("model")
        details = str(result.get("details") or "")
        if not model and details:
            model = details.split("•")[0].strip() or None
        model = re.sub(r"^copilot/", "", str(model)) if model else "unknown"
        mult = re.search(r"(\d+(?:\.\d+)?)\s*x\b", details)
        mode_info = req.get("modeInfo") or {}
        mode = mode_info.get("kind") or mode_info.get("modeId") or "unknown"
        col.copilot_modes[mode] += 1
        col.copilot_requests.append({"model": model, "multiplier": float(mult.group(1)) if mult else None,
                                     "mode": mode, "agent": (req.get("agent") or {}).get("id")})
        seg = col.new_segment("copilot-vscode", sid, ts, text)
        info["prompt_count"] += 1
        info["first_prompt"] = info["first_prompt"] or truncate(col.redact(text), 160)
        attached = []
        for var in ((req.get("variableData") or {}).get("variables") or []):
            if isinstance(var, dict) and var.get("name"):
                attached.append(str(var["name"]))
        if attached:
            seg["attached_context"] = attached[:15]
        elapsed = (result.get("timings") or {}).get("totalElapsed")
        if ts and isinstance(elapsed, (int, float)):
            seg["end_ts"] = ts + timedelta(milliseconds=elapsed)
            col.touch(seg["end_ts"])
            info["last_ts"] = seg["end_ts"]
        tokens = deep_numbers(meta, COPILOT_TOKEN_KEYS)
        col.add_usage("copilot-vscode", model, "main", tokens, 1)
        if result.get("errorDetails"):
            col.api_errors += 1
            seg["errors"] += 1
        tool_parts = 0
        reply = []
        for part in req.get("response") or []:
            if not isinstance(part, dict):
                continue
            kind = part.get("kind")
            if kind == "toolInvocationSerialized":
                tool_parts += 1
                name = str(part.get("toolId") or part.get("toolName") or "tool")
                col.tool_calls[name] += 1
                seg["tools"][name] += 1
                if name.startswith("mcp_"):
                    col.mcp["(copilot) " + name.split("_")[1] if "_" in name else "(copilot)"][name] += 1
                tsd = part.get("toolSpecificData") or {}
                if isinstance(tsd, dict):
                    cl = tsd.get("commandLine")
                    cmd = (cl.get("original") or cl.get("toolEdited")) if isinstance(cl, dict) else tsd.get("command")
                    if isinstance(cmd, str):
                        col.add_command(cmd, seg, ts)
            elif kind == "textEditGroup":
                p = uri_to_path(part.get("uri"))
                col.add_file_write(p, "copilot-edit", "", seg)
            elif kind == "thinking":
                col.thinking_blocks += 1
            elif kind in (None, "markdownContent") and isinstance(part.get("value"), str):
                reply.append(part["value"])
            elif kind in (None, "markdownContent") and isinstance(part.get("content"), dict):
                reply.append(str(part["content"].get("value") or ""))
        if not tool_parts:
            for rnd in meta.get("toolCallRounds") or []:
                for tc in (rnd or {}).get("toolCalls") or []:
                    name = str((tc or {}).get("name") or "tool")
                    col.tool_calls[name] += 1
                    seg["tools"][name] += 1
                    try:
                        args = json.loads(tc.get("arguments") or "{}")
                    except (ValueError, TypeError):
                        args = {}
                    if isinstance(args, dict) and isinstance(args.get("command"), str):
                        col.add_command(args["command"], seg, ts)
                    if isinstance(args, dict) and isinstance(args.get("filePath"), str) and \
                            re.search(r"edit|create|replace|insert|write", name, re.I):
                        col.add_file_write(args["filePath"], name, "", seg)
        seg["reply"] = "".join(reply).strip()
    if not info["prompt_count"]:
        return None
    return info


def find_copilot_cli_sessions(target, copilot_home):
    """Copilot CLI keeps per-session event logs; the format is not documented, so match any
    JSONL file under its state folders that mentions the target folder as its cwd."""
    want = norm_path(target)
    files = []
    for sub in ("session-state", "history-session-state"):
        for f in glob.glob(os.path.join(copilot_home, sub, "**", "*.jsonl"), recursive=True):
            for i, rec in enumerate(iter_jsonl(f)):
                cwd = rec.get("cwd") or (rec.get("data") or {}).get("cwd") or \
                    ((rec.get("data") or {}).get("context") or {}).get("cwd")
                if cwd:
                    if norm_path(cwd) == want:
                        files.append(f)
                    break
                if i > 30:
                    break
    return sorted(files)


def read_copilot_cli(path, col, window):
    col.sources_used.add("copilot-cli")
    sid = os.path.splitext(os.path.basename(path))[0]
    info = {"source": "copilot-cli", "session_id": sid, "file": path, "title": None, "first_ts": None,
            "last_ts": None, "prompt_count": 0, "first_prompt": None, "subagent_count": 0}
    seg = None
    model = "unknown"
    for rec in iter_jsonl(path):
        ts = parse_ts(rec.get("timestamp"))
        if not window.contains(ts):
            continue
        col.touch(ts)
        info["first_ts"] = info["first_ts"] or ts
        info["last_ts"] = ts or info["last_ts"]
        t = str(rec.get("type") or "")
        data = rec.get("data") if isinstance(rec.get("data"), dict) else rec
        model = data.get("model") or data.get("selectedModel") or data.get("newModel") or model
        if "version" in data and t.startswith("session"):
            col.harness[("GitHub Copilot CLI", str(data.get("version") or data.get("copilotVersion") or "?"))] += 1
        if t in ("user.message", "user_message", "user"):
            text = data.get("content") or data.get("text") or data.get("message")
            if isinstance(text, str) and text.strip():
                seg = col.new_segment("copilot-cli", sid, ts, text.strip())
                info["prompt_count"] += 1
                info["first_prompt"] = info["first_prompt"] or truncate(col.redact(text), 160)
        elif t in ("assistant.message", "assistant_message", "assistant"):
            text = data.get("content") or data.get("text")
            if isinstance(text, str) and seg is not None:
                seg["reply"] = text
        elif t.startswith("tool.") and t.endswith(("start", "execution_start", "call")):
            name = str(data.get("toolName") or data.get("name") or "tool")
            col.tool_calls[name] += 1
            if seg is not None:
                seg["tools"][name] += 1
            args = data.get("arguments") or {}
            if isinstance(args, dict) and isinstance(args.get("command"), str):
                col.add_command(args["command"], seg, ts)
        tokens = deep_numbers(data.get("usage") or {}, COPILOT_TOKEN_KEYS)
        if tokens:
            col.add_usage("copilot-cli", model, "main", tokens, 1)
    if not info["prompt_count"]:
        return None
    col.add_usage("copilot-cli", model, "main", Counter(), 0)
    return info


# ----------------------------------------------------------------------------- discovery

def sniff_format(path):
    if path.endswith(".json"):
        data = load_json(path)
        return "copilot-vscode" if isinstance(data, dict) and "requests" in data else None
    for i, rec in enumerate(iter_jsonl(path)):
        if rec.get("kind") == 0 and isinstance(rec.get("v"), dict):
            return "copilot-vscode"
        if rec.get("type") == "session_meta":
            return "codex"
        if rec.get("sessionId") and rec.get("type") in ("user", "assistant", "attachment", "system",
                                                         "ai-title", "mode", "queue-operation", "summary"):
            return "claude-code"
        if str(rec.get("type", "")).startswith(("session.", "user.", "assistant.")):
            return "copilot-cli"
        if i > 20:
            break
    return None


READERS = {
    "claude-code": read_claude,
    "codex": read_codex,
    "copilot-vscode": read_copilot_chat,
    "copilot-cli": read_copilot_cli,
}


def read_session(source, path, col, window, full=True):
    if source == "claude-code":
        return read_claude(path, col, window, with_subagents=full)
    if source == "codex":
        return read_codex(path, col, window, with_children=full)
    return READERS[source](path, col, window)


def discover(args, target):
    found = []
    searched = []
    if args.transcripts:
        spec = args.transcripts
        if any(c in spec for c in "*?["):
            files = glob.glob(spec, recursive=True)
        elif os.path.isdir(spec):
            files = glob.glob(os.path.join(spec, "*.jsonl")) + glob.glob(os.path.join(spec, "*.json"))
        else:
            files = [spec]
        for f in sorted(files):
            fmt = sniff_format(f)
            if fmt:
                found.append((fmt, f))
        searched.append({"source": "explicit", "where": spec, "sessions_found": len(found)})
        return found, searched
    home = os.path.expanduser("~")
    cc = find_claude_sessions(target, args.projects_dir)
    found += [("claude-code", f) for f in cc]
    searched.append({"source": "claude-code",
                     "where": os.path.join(args.projects_dir, encode_claude_dir(target)),
                     "sessions_found": len(cc)})
    user_dirs = [args.vscode_user_dir] if args.vscode_user_dir else vscode_user_dirs()
    cp = find_copilot_sessions(target, user_dirs)
    found += [("copilot-vscode", f) for f in cp]
    searched.append({"source": "copilot-vscode",
                     "where": "; ".join(os.path.join(u, "workspaceStorage") for u in user_dirs) or "(no VS Code user folder)",
                     "sessions_found": len(cp)})
    copilot_home = args.copilot_home or os.path.join(home, ".copilot")
    cli = find_copilot_cli_sessions(target, copilot_home)
    found += [("copilot-cli", f) for f in cli]
    searched.append({"source": "copilot-cli", "where": copilot_home, "sessions_found": len(cli)})
    codex_home = args.codex_home or os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")
    cx = find_codex_sessions(target, codex_home) if os.path.isdir(codex_home) else []
    found += [("codex", f) for f in cx]
    searched.append({"source": "codex", "where": codex_home, "sessions_found": len(cx)})
    return found, searched


def index_sessions(found):
    """Light pass: one summary per session, used for --list and for choosing sessions."""
    index = []
    for source, path in found:
        scratch = Collector(None, Redactor())
        info = read_session(source, path, scratch, Window(), full=False)
        if not info or (not info.get("prompt_count") and not scratch.usage):
            continue
        info = dict(info)
        info["file"] = path
        info["models"] = sorted({k[1] for k in scratch.usage if k[1] != "unknown"})
        info["ai_turns"] = sum(scratch.turns.values())
        index.append(info)
    index.sort(key=lambda s: s.get("first_ts") or datetime.min.replace(tzinfo=timezone.utc))
    return index


def select_sessions(index, args):
    chosen = index
    mode = "all"
    if args.session:
        wanted = [s.lower() for s in args.session]
        chosen = [s for s in chosen if any(s["session_id"].lower().startswith(w) for w in wanted)]
        mode = "session"
        missing = [w for w in wanted if not any(s["session_id"].lower().startswith(w) for s in index)]
        if missing:
            raise SystemExit(f"No session matches: {', '.join(missing)}. Run with --list to see the ids.")
    if args.since_dt or args.until_dt:
        chosen = [s for s in chosen
                  if (not args.until_dt or (s["first_ts"] and s["first_ts"] <= args.until_dt))
                  and (not args.since_dt or (s["last_ts"] and s["last_ts"] >= args.since_dt))]
        mode = "window" if mode == "all" else mode + "+window"
    if args.latest:
        chosen = sorted(chosen, key=lambda s: s.get("last_ts") or datetime.min.replace(tzinfo=timezone.utc))[-args.latest:]
        mode = "latest" if mode == "all" else mode + "+latest"
    return chosen, mode


# ----------------------------------------------------------------------------- output

def current_settings(sources, target):
    out = []
    home = os.path.expanduser("~")
    if "claude-code" in sources:
        paths = [os.path.join(home, ".claude", "settings.json")]
        if target:
            paths += [os.path.join(target, ".claude", "settings.json"),
                      os.path.join(target, ".claude", "settings.local.json")]
        for path in paths:
            data = load_json(path)
            if not isinstance(data, dict):
                continue
            vals = {k: data[k] for k in ("model", "effortLevel", "alwaysThinkingEnabled", "outputStyle")
                    if k in data}
            if isinstance(data.get("permissions"), dict) and data["permissions"].get("defaultMode"):
                vals["defaultMode"] = data["permissions"]["defaultMode"]
            if isinstance(data.get("enabledPlugins"), dict):
                vals["enabledPlugins"] = sorted(k for k, v in data["enabledPlugins"].items() if v)
            if vals:
                out.append({"path": path, "values": vals})
    if "codex" in sources:
        path = os.path.join(home, ".codex", "config.toml")
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
        vals = {}
        for key in ("model", "model_reasoning_effort", "approval_policy", "sandbox_mode"):
            m = re.search(rf"^\s*{key}\s*=\s*\"?([^\"\n]+)\"?", text, re.M)
            if m:
                vals[key] = m.group(1).strip()
        if vals:
            out.append({"path": path, "values": vals})
    return out


def repo_instruction_files(target):
    """Instruction files sitting in the folder now (Copilot and Codex do not log which they loaded)."""
    if not target or not os.path.isdir(target):
        return []
    pats = [".github/copilot-instructions.md", ".github/instructions/*.md", ".github/prompts/*.prompt.md",
            ".github/chatmodes/*.md", ".github/agents/*.md", "AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md"]
    res = []
    for p in pats:
        for f in glob.glob(os.path.join(target, p)):
            try:
                size = os.path.getsize(f)
            except OSError:
                size = None
            res.append({"path": f, "type": "in folder now", "chars": size})
    return res


def skill_location(name, source_path, target):
    base = name.split(":")[-1]
    home = os.path.expanduser("~")
    roots = [os.path.join(home, ".claude", "skills"), os.path.join(home, ".agents", "skills"),
             os.path.join(home, ".copilot", "skills"), os.path.join(home, ".codex", "skills")]
    if target:
        roots += [os.path.join(target, d, "skills") for d in (".claude", ".agents", ".github", ".codex")]
    for root in roots:
        md = os.path.join(root, base, "SKILL.md")
        if os.path.isfile(md):
            return md, read_frontmatter_version(md)
    for md in glob.glob(os.path.join(home, ".claude", "plugins", "**", "skills", base, "SKILL.md"), recursive=True)[:1]:
        return md, read_frontmatter_version(md)
    return None, None


def build_result(col, args, target, index, selected, mode, searched):
    events = sorted(col.events)
    span = active = 0
    if events:
        span = (events[-1] - events[0]).total_seconds()
        for a, b in zip(events, events[1:]):
            gap = (b - a).total_seconds()
            if 0 <= gap <= IDLE_GAP_SECONDS:
                active += gap

    segs = sorted(col.segments, key=lambda s: s["ts"] or datetime.min.replace(tzinfo=timezone.utc))
    prompts, timeline = [], []
    for n, s in enumerate(segs, 1):
        prompts.append({"n": n, "session_id": s["session_id"], "source": s["source"],
                        "timestamp": iso(s["ts"]), "kind": s["kind"], "chars": s["chars"], "text": s["prompt"]})
        dur = (s["end_ts"] - s["ts"]).total_seconds() if s["ts"] and s["end_ts"] else None
        item = {"n": n, "timestamp": iso(s["ts"]), "end_timestamp": iso(s["end_ts"]),
                "duration_seconds": round(dur) if dur is not None else None,
                "prompt_excerpt": truncate(s["prompt"], 300), "kind": s["kind"],
                "tools": dict(s["tools"].most_common()), "command_count": s["command_count"],
                "commands": s["commands"], "files": s["files"][:20], "skills": s["skills"],
                "subagents": s["subagents"][:10], "errors": s["errors"], "denials": s["denials"],
                "interrupted": s["interrupted"],
                # The AI's progress messages: the first and last few are what explain a long turn.
                "notes": s["notes"] if len(s["notes"]) <= 8 else s["notes"][:4] + ["…"] + s["notes"][-4:],
                "questions": s["questions"], "error_details": s["error_details"],
                "approvals": s["approvals"],
                "reply_excerpt": truncate(col.redact(s["reply"]), EXCERPT_LIMIT)}
        if s.get("attached_context"):
            item["attached_context"] = s["attached_context"]
        timeline.append(item)

    rows = []
    totals = Counter()
    for (source, model, scope), c in sorted(col.usage.items(), key=lambda kv: (kv[0][2] != "main", -kv[1]["output"])):
        row = {"source": source, "model": model, "name": col.model_names.get(model), "scope": scope,
               "turns": col.turns[(source, model, scope)]}
        for k in ("input", "output", "thinking", "cache_write", "cache_write_5m", "cache_write_1h",
                  "cache_read", "web_search", "web_fetch"):
            row[k] = int(c.get(k, 0))
            totals[k] += int(c.get(k, 0))
        rows.append(row)

    models = defaultdict(lambda: {"main_turns": 0, "subagent_turns": 0, "source": None})
    for (source, model, scope), n in col.turns.items():
        m = models[model]
        m["source"] = source
        m["main_turns" if scope == "main" else "subagent_turns"] += n
    model_list = [{"id": k, "name": col.model_names.get(k), **v} for k, v in
                  sorted(models.items(), key=lambda kv: -(kv[1]["main_turns"] + kv[1]["subagent_turns"]))]

    window_tokens, window_basis = None, None
    if col.context_windows:
        window_tokens, window_basis = col.context_windows.most_common(1)[0][0], "logged"
    elif any("[1m]" in m for m in models):
        window_tokens, window_basis = 1_000_000, "model id has the [1m] suffix"
    elif col.peak_context > 200_000:
        window_tokens, window_basis = 1_000_000, "inferred: peak context above 200k tokens needs the 1M window"

    reported = None
    if col.reported_costs:
        cc_sessions = [s for s in selected if s["source"] == "claude-code"]
        complete = (len(col.reported_costs) == len(cc_sessions) and all(
            r["coverage_ratio"] is not None and 0.9 <= r["coverage_ratio"] <= 1.15 and not r["window_applied"]
            for r in col.reported_costs))
        by_model = Counter()
        for r in col.reported_costs:
            for m, v in (r["by_model"] or {}).items():
                by_model[m] += v or 0
        reported = {
            "sessions": col.reported_costs,
            "total_usd": round(sum(r["total_usd"] or 0 for r in col.reported_costs), 4),
            "by_model": {m: round(v, 4) for m, v in by_model.items()},
            "complete": complete,
            "lines_added": sum(r["lines_added"] or 0 for r in col.reported_costs),
            "lines_removed": sum(r["lines_removed"] or 0 for r in col.reported_costs),
            "note": ("Claude Code's own cost figure covers all selected work." if complete else
                     "Claude Code's own cost figure does not cover all selected work (a session went on "
                     "after it was written, a time window was applied, or sub-agent usage is missing "
                     "from it). Use it as a cross-check; estimate the full cost from a price table."),
        }

    copilot = None
    if col.copilot_requests:
        by = defaultdict(lambda: {"requests": 0, "multiplier": None})
        for r in col.copilot_requests:
            by[r["model"]]["requests"] += 1
            if r["multiplier"] is not None:
                by[r["model"]]["multiplier"] = r["multiplier"]
        copilot = {"requests": len(col.copilot_requests), "by_model": dict(by),
                   "note": "GitHub Copilot bills premium requests (requests x model multiplier), not tokens."}

    skills = []
    for name in sorted(set(col.skill_uses) | set(col.skill_sources)):
        md, version = skill_location(name, col.skill_sources.get(name), target)
        skills.append({"name": name, "uses": col.skill_uses.get(name, 0), "source": col.skill_sources.get(name),
                       "skill_md_now": md, "version_now": version})
    plugins = Counter()
    for name in col.skill_uses:
        if ":" in name:
            plugins[(name.split(":")[0], "skill " + name)] += 1
    for server in col.mcp:
        m = re.match(r"plugin_([^_]+)_", server)
        if m:
            plugins[(m.group(1), "MCP server " + server)] += 1
    settings = current_settings(col.sources_used, target)
    for s in settings:
        for p in s["values"].get("enabledPlugins", []):
            plugins[(p.split("@")[0], "enabled in " + s["path"] + " now")] += 0
    plugin_list = defaultdict(list)
    for (name, evidence) in plugins:
        plugin_list[name].append(evidence)

    agent_types = defaultdict(lambda: {"count": 0, "descriptions": [], "output_tokens": 0, "models": Counter()})
    for a in col.agents:
        t = agent_types[a["type"]]
        t["count"] += 1
        t["output_tokens"] += a["output_tokens"]
        t["models"].update(a["models"])
        if a["description"] and a["description"] not in t["descriptions"] and len(t["descriptions"]) < 12:
            t["descriptions"].append(a["description"])
    for kind, n in col.agent_calls.items():
        if kind not in agent_types:
            agent_types[kind]["count"] = n

    instruction = [{"path": p, **v} for p, v in col.instruction_files.items()]
    if col.sources_used - {"claude-code"}:
        known = {norm_path(i["path"]) for i in instruction}
        instruction += [i for i in repo_instruction_files(target) if norm_path(i["path"]) not in known]

    shell_names = {os.path.basename(p).lower() for p, c in col.files_written.items() if c.get("shell")}
    files_written = sorted(({"path": p, "edits": sum(c.values()), "tools": dict(c),
                             "exists_now": os.path.exists(p) if os.path.isabs(p) else None}
                            for p, c in col.files_written.items()), key=lambda f: -f["edits"])

    if "claude-code" in col.sources_used:
        col.gap("Claude Code does not log the context window size; it is taken from the model id or inferred from peak use.")
        col.gap("Calls Claude Code makes in the background (session titles, summaries) are not in the transcript; "
                "its own cost figure includes them, the token table does not.")
    if "copilot-vscode" in col.sources_used:
        col.gap("VS Code Copilot Chat logs rarely include token counts, effort or context size; "
                "its cost is premium requests x model multiplier.")
        col.gap("Copilot does not log which instruction files it loaded; files listed are the ones in the folder now.")
    if "codex" in col.sources_used:
        col.gap("Codex logs running token totals per session, not per model or per sub-agent.")
    if not any(r["output"] for r in rows) and rows:
        col.gap("No token counts were found in these logs.")

    ai_used = bool(selected) and (bool(prompts) or bool(rows))
    if not selected:
        col.warnings.append("No AI session logs were found for this folder and selection.")

    env = col.environment or {}
    return {
        "schema": SCHEMA,
        "generated_utc": iso(datetime.now(timezone.utc)),
        "target_folder": target,
        "ai_used": ai_used,
        "selection": {"mode": mode, "session_ids": args.session or [], "since": iso(args.since_dt),
                      "until": iso(args.until_dt), "latest": args.latest},
        "searched": searched,
        "available_sessions": [_session_out(s) for s in index],
        "sessions": [_session_out(s, col) for s in selected],
        "timing": {"started_utc": iso(events[0]) if events else None,
                   "ended_utc": iso(events[-1]) if events else None,
                   "wall_clock_seconds": round(span), "active_seconds": round(active),
                   "idle_gap_seconds": IDLE_GAP_SECONDS},
        "prompts": prompts,
        "timeline": timeline,
        "setup": {
            "harnesses": [{"name": n, "version": v, "records": c} for (n, v), c in col.harness.most_common()],
            "entrypoints": {k: {"count": v, "label": ENTRYPOINT_LABELS.get(k, k)} for k, v in col.entrypoints.items()},
            "environment": {k: env.get(k) for k in ("platform", "osVersion", "shell", "isGitRepo", "isWorktree")
                            if env.get(k) is not None},
            "git_branches": dict(col.git_branches.most_common()),
            "models": model_list,
            "effort": dict(col.effort.most_common()),
            "speed": dict(col.speed),
            "service_tier": dict(col.service_tier),
            "thinking": {"blocks": col.thinking_blocks, "tokens": totals["thinking"]},
            "context": {"peak_tokens": col.peak_context, "peak_model": col.peak_context_model,
                        "window_tokens": window_tokens, "window_basis": window_basis,
                        "compactions": col.compactions},
            "modes": {"permission_modes": dict(col.permission_modes), "plan_mode_turns": col.plan_mode_turns,
                      "auto_mode_seen": col.auto_mode, "codex_approval": dict(col.codex_approval),
                      "codex_sandbox": dict(col.codex_sandbox), "collaboration_modes": dict(col.collab_modes),
                      "copilot_modes": dict(col.copilot_modes)},
            "instruction_files": instruction,
            "hooks": [{"event": e, "command": col.redact(c), "runs": n} for (e, c), n in col.hooks.most_common()],
            "local_command_output": col.local_command_output,
            "current_settings": settings,
        },
        "usage": {"rows": rows, "totals": dict(totals), "reported_cost": reported, "copilot": copilot,
                  "billing_hints": sorted(col.billing_hints)},
        "extensions": {
            "skills": skills,
            "mcp_servers": [{"server": s, "calls": sum(c.values()), "tools": dict(c.most_common())}
                            for s, c in sorted(col.mcp.items(), key=lambda kv: -sum(kv[1].values()))],
            "plugins": [{"name": n, "evidence": ev} for n, ev in sorted(plugin_list.items())],
            "subagents": [{"type": t, "count": v["count"], "output_tokens": v["output_tokens"],
                           "models": dict(v["models"]), "descriptions": v["descriptions"]}
                          for t, v in sorted(agent_types.items(), key=lambda kv: -kv[1]["count"])],
        },
        "non_ai_tools": {
            "executables": [{"name": n, "count": c, "category": exe_category(n)}
                            for n, c in col.executables.most_common()],
            "installs": col.installs,
            "imports": {lang: dict(c.most_common(40)) for lang, c in col.imports.items()},
            "web_searches": col.web_searches[:40],
            "web_domains": dict(col.web_domains.most_common(30)),
        },
        "work": {
            "tool_calls": dict(col.tool_calls.most_common()),
            "total_tool_calls": sum(col.tool_calls.values()),
            "files_written": files_written,
            "files_read": len(col.files_read),
            "commands": col.command_count,
            "git_commits": col.git_commits,
            "pull_requests": col.pull_requests,
            "lines_added": reported["lines_added"] if reported else None,
            "lines_removed": reported["lines_removed"] if reported else None,
            "tool_errors": col.tool_errors,
            "api_errors": col.api_errors,
            "interruptions": col.interruptions,
            "denials": dict(col.denials),
            "questions_asked": col.questions_asked,
            "approval_requests": col.approvals,
            "plans_presented": col.plans_presented,
            # Changes noticed on disk outside the AI's edit tools. When a shell command of the AI
            # wrote the same file, the AI itself is the likely author.
            "external_edits": [{"path": p, "count": n,
                                "written_by_ai_shell": os.path.basename(p).lower() in shell_names}
                               for p, n in col.external_edits.most_common(30)],
            "last_reply_excerpt": timeline[-1]["reply_excerpt"] if timeline else None,
        },
        "redactions": col.redact.summary(),
        "warnings": col.warnings,
        "data_gaps": col.data_gaps,
    }


def _session_out(s, col=None):
    out = {k: s.get(k) for k in ("source", "session_id", "title", "prompt_count", "subagent_count", "file")}
    out["first_ts"] = iso(s.get("first_ts"))
    out["last_ts"] = iso(s.get("last_ts"))
    out["first_prompt"] = s.get("first_prompt")
    if s.get("models") is not None:
        out["models"] = s["models"]
    return out


def local_time(ts_iso):
    dt = parse_ts(ts_iso)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M") if dt else "?"


def write_timeline_md(result, path):
    offset = datetime.now().astimezone().strftime("%z")
    lines = [f"# Session timeline: {result['target_folder']}", "",
             "Digest of the selected sessions, one block per human prompt. Read this instead of the raw",
             "transcripts; open a transcript only to check a specific turn (session file + timestamp).",
             f"Times are local (UTC{offset[:3]}:{offset[3:]}); the transcripts themselves use UTC.", ""]
    files = {s["session_id"]: s["file"] for s in result["sessions"]}
    for t, p in zip(result["timeline"], result["prompts"]):
        dur = t["duration_seconds"]
        lines.append(f"## Prompt {t['n']} · {local_time(t['timestamp'])} · {p['source']} · session {p['session_id'][:8]}"
                     + (f" · {p['kind']}" if p["kind"] else ""))
        lines.append("")
        lines.append("> " + truncate(p["text"], 1200).replace("\n", "\n> "))
        lines.append("")
        if t.get("attached_context"):
            lines.append("- Context attached by the user: " + ", ".join(t["attached_context"]))
        if t["tools"]:
            lines.append("- Tools: " + ", ".join(f"{k} ×{v}" for k, v in t["tools"].items()))
        if t["command_count"]:
            lines.append(f"- Commands ({t['command_count']}): " + "; ".join(f"`{c}`" for c in t["commands"]))
        if t["files"]:
            lines.append("- Files written: " + ", ".join(t["files"]))
        if t["skills"]:
            lines.append("- Skills: " + ", ".join(t["skills"]))
        if t["subagents"]:
            lines.append("- Sub-agents: " + "; ".join(t["subagents"]))
        for a in t.get("approvals") or []:
            lines.append(f"- Needed the human's approval to run outside the sandbox: {a}")
        for q in t.get("questions") or []:
            lines.append(f"- The AI asked: {q['question']}")
            lines.append(f"  The human answered: {q['answer'] or '(no answer logged)'}")
        flags = []
        if t["errors"]:
            flags.append(f"{t['errors']} tool error(s)")
        if t["denials"]:
            flags.append(f"{t['denials']} permission refusal(s)")
        if t["interrupted"]:
            flags.append("interrupted by the user")
        if flags:
            lines.append("- Problems: " + ", ".join(flags))
        for e in t.get("error_details") or []:
            lines.append(f"  - error: {e}")
        if dur is not None:
            lines.append(f"- Took: {dur // 60} min {dur % 60} s (prompt to last activity before the next prompt)")
        lines.append(f"- Transcript: {files.get(p['session_id'], '?')}")
        notes = t.get("notes") or []
        if len(notes) > 1:
            lines.append("")
            lines.append("What the AI said along the way:")
            lines.append("")
            lines += [f"- {n}" for n in notes[:-1]]
        if t["reply_excerpt"]:
            lines.append("")
            lines.append("Last reply before the next prompt:")
            lines.append("")
            lines.append("> " + t["reply_excerpt"].replace("\n", "\n> "))
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def print_list(index):
    if not index:
        print("No AI sessions found for this folder.")
        return
    offset = datetime.now().astimezone().strftime("%z")
    print(f"{len(index)} session(s), oldest first. Times are local (UTC{offset[:3]}:{offset[3:]}).\n")
    for s in index:
        start = s["first_ts"].astimezone().strftime("%Y-%m-%d %H:%M") if s.get("first_ts") else "?"
        end = s["last_ts"].astimezone().strftime("%Y-%m-%d %H:%M") if s.get("last_ts") else "?"
        title = s.get("title") or ""
        print(f"- {s['session_id']}  [{s['source']}]  {start} -> {end}  prompts: {s['prompt_count']}"
              f"  AI turns: {s.get('ai_turns', 0)}"
              + (f"  sub-agents: {s['subagent_count']}" if s.get("subagent_count") else "")
              + (f"  models: {', '.join(s['models'])}" if s.get("models") else ""))
        if title:
            print(f"    title: {title}")
        if s.get("first_prompt"):
            print(f"    first prompt: {first_line(s['first_prompt'])[:110]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target_folder", nargs="?", help="Folder where the AI work happened")
    ap.add_argument("--list", action="store_true", help="List the sessions found for the folder and stop")
    ap.add_argument("--session", action="append", help="Session id or id prefix to include (repeatable)")
    ap.add_argument("--since", help="Only activity from this local date/time (2026-09-26 or 2026-09-26T14:00)")
    ap.add_argument("--until", help="Only activity up to this local date/time (a bare date includes that day)")
    ap.add_argument("--latest", type=int, help="Only the N most recent sessions")
    ap.add_argument("--transcripts", help="Explicit log file, folder or glob (skips folder lookup)")
    ap.add_argument("--projects-dir", default=os.path.join(os.path.expanduser("~"), ".claude", "projects"),
                    help="Claude Code projects folder (default ~/.claude/projects)")
    ap.add_argument("--codex-home", help="Codex home (default $CODEX_HOME or ~/.codex)")
    ap.add_argument("--copilot-home", help="Copilot CLI home (default ~/.copilot)")
    ap.add_argument("--vscode-user-dir", help="VS Code user folder holding workspaceStorage")
    ap.add_argument("--no-redact", action="store_true", help="Keep likely secrets in prompt text")
    ap.add_argument("--out", help="Write the JSON here (plus <out>.timeline.md); otherwise print it")
    args = ap.parse_args()

    if not args.transcripts and not args.target_folder:
        ap.error("give a target folder or --transcripts")
    target = os.path.abspath(args.target_folder) if args.target_folder else None
    args.since_dt = parse_user_when(args.since)
    args.until_dt = parse_user_when(args.until, end_of_day=True)

    found, searched = discover(args, target)
    index = index_sessions(found)
    if args.list:
        print_list(index)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump({"target_folder": target, "searched": searched,
                           "available_sessions": [_session_out(s) for s in index]}, fh, indent=2, ensure_ascii=False)
        return

    selected, mode = select_sessions(index, args)
    col = Collector(target, Redactor(enabled=not args.no_redact))
    window = Window(args.since_dt, args.until_dt)
    for s in selected:
        read_session(s["source"], s["file"], col, window, full=True)
    result = build_result(col, args, target, index, selected, mode, searched)

    out_json = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    if not args.out:
        print(out_json)
        return
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out_json)
    timeline_path = re.sub(r"\.json$", "", args.out) + ".timeline.md"
    write_timeline_md(result, timeline_path)
    t = result["usage"]["totals"]
    print(f"Wrote {args.out}")
    print(f"Wrote {timeline_path}")
    print(f"  sessions: {len(result['sessions'])} of {len(index)} found (selection: {mode})")
    print(f"  prompts: {len(result['prompts'])}  models: {[m['id'] for m in result['setup']['models']]}")
    print(f"  tokens: in={t.get('input', 0):,} out={t.get('output', 0):,} "
          f"cache_read={t.get('cache_read', 0):,} cache_write={t.get('cache_write', 0):,}")
    print(f"  wall-clock: {result['timing']['wall_clock_seconds'] / 3600:.1f} h  "
          f"active: {result['timing']['active_seconds'] / 3600:.1f} h")
    print(f"  tool calls: {result['work']['total_tool_calls']}  files written: {len(result['work']['files_written'])}"
          f"  sub-agents: {sum(a['count'] for a in result['extensions']['subagents'])}")
    if result["redactions"]["count"]:
        print(f"  masked {result['redactions']['count']} likely secret(s) in prompt text")
    for w in result["warnings"]:
        print("  ! " + w)


if __name__ == "__main__":
    main()

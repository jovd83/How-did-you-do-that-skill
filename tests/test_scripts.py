"""Tests for extract_session.py and render_report.py against synthetic logs.

Run from the repository root:  python -m unittest discover -s tests -v
Stdlib only. Builds fake Claude Code, Copilot and Codex log folders in a temp dir.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT = os.path.join(ROOT, "scripts", "extract_session.py")
RENDER = os.path.join(ROOT, "scripts", "render_report.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import extract_session as ex  # noqa: E402


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def usage(inp, out, read, write_1h=0, write_5m=0, thinking=0):
    return {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": write_1h + write_5m,
            "cache_creation": {"ephemeral_1h_input_tokens": write_1h, "ephemeral_5m_input_tokens": write_5m},
            "output_tokens_details": {"thinking_tokens": thinking}, "speed": "standard"}


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hdyd-test-")
        cls.project = os.path.join(cls.tmp, "my_project")  # underscore: encoded as '-'
        os.makedirs(cls.project)
        cls.projects_dir = os.path.join(cls.tmp, "claude-projects")
        cls.vscode = os.path.join(cls.tmp, "vscode-user")
        cls.codex = os.path.join(cls.tmp, "codex-home")
        cls.copilot = os.path.join(cls.tmp, "copilot-home")
        cls._claude()
        cls._copilot()
        cls._codex()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _claude(cls):
        enc = re.sub(r"[^A-Za-z0-9]", "-", cls.project)
        d = os.path.join(cls.projects_dir, enc)
        sid = "11111111-aaaa-bbbb-cccc-000000000001"
        base = {"sessionId": sid, "version": "2.1.0", "entrypoint": "cli", "cwd": cls.project}
        msg1 = {"id": "msg_1", "model": "claude-opus-5-5", "usage": usage(10, 100, 1000, write_1h=50, thinking=40)}
        records = [
            {**base, "type": "ai-title", "aiTitle": "Build the widget"},
            {**base, "type": "attachment", "timestamp": "2026-09-01T10:00:00Z",
             "attachment": {"type": "model", "identity": {"modelId": "claude-opus-5-5", "marketingName": "Opus 5.5"}}},
            {**base, "type": "attachment", "timestamp": "2026-09-01T10:00:00Z",
             "attachment": {"type": "instructions", "files": [{"path": "C:/x/CLAUDE.md", "type": "User", "content": "rules"}]}},
            {**base, "type": "user", "timestamp": "2026-09-01T10:00:01Z", "origin": {"kind": "human"},
             "permissionMode": "auto",
             "message": {"role": "user", "content": "Build a widget. My key is sk-ant-abcdefghijklmnopqrstuvwxyz0123"}},
            # One API message written as two records that repeat the usage: must count once.
            {**base, "type": "assistant", "timestamp": "2026-09-01T10:00:05Z", "effort": "xhigh",
             "message": {**msg1, "content": [{"type": "thinking", "thinking": ""}]}},
            {**base, "type": "assistant", "timestamp": "2026-09-01T10:00:06Z", "effort": "xhigh",
             "message": {**msg1, "content": [
                 {"type": "tool_use", "id": "t1", "name": "Bash",
                  "input": {"command": "pip install requests && git commit -m 'feat: add widget'"}},
                 {"type": "tool_use", "id": "t2", "name": "Write",
                  "input": {"file_path": os.path.join(cls.project, "w.py"), "content": "import requests\nimport os\n"}},
                 {"type": "tool_use", "id": "t3", "name": "Skill", "input": {"skill": "skill-creator"}},
                 {"type": "tool_use", "id": "t4", "name": "mcp__github__create_issue", "input": {}},
                 {"type": "tool_use", "id": "t5", "name": "Agent",
                  "input": {"subagent_type": "Explore", "description": "find the config"}}]}},
            {**base, "type": "user", "timestamp": "2026-09-01T10:00:07Z",
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "x"}]}},
            {**base, "type": "assistant", "timestamp": "2026-09-01T10:00:50Z", "effort": "xhigh",
             "message": {"id": "msg_q", "model": "claude-opus-5-5", "usage": usage(1, 5, 10), "content": [
                 {"type": "text", "text": "I need a decision from you."},
                 {"type": "tool_use", "id": "q1", "name": "AskUserQuestion",
                  "input": {"questions": [{"question": "Keep git out of it?"}]}}]}},
            {**base, "type": "user", "timestamp": "2026-09-01T10:00:55Z",
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "q1",
                                                      "content": "User answered: yes, no git"}]}},
            {**base, "type": "user", "timestamp": "2026-09-01T10:01:00Z", "origin": {"kind": "task-notification"},
             "message": {"role": "user", "content": "<task-notification>agent done</task-notification>"}},
            {**base, "type": "user", "timestamp": "2026-09-01T10:02:00Z", "origin": {"kind": "human"},
             "message": {"role": "user", "content": "<command-message>review</command-message>\n<command-name>/review</command-name>\n<command-args>high</command-args>"}},
            {**base, "type": "assistant", "timestamp": "2026-09-01T10:02:10Z", "effort": "xhigh",
             "message": {"id": "msg_2", "model": "claude-opus-5-5", "usage": usage(5, 50, 2000),
                         "content": [{"type": "text", "text": "All done, tests pass."}]}},
            {**base, "type": "user", "timestamp": "2026-09-01T10:03:00Z", "origin": {"kind": "human"},
             "message": {"role": "user", "content": "continue"}},
            {**base, "type": "system", "subtype": "compact_boundary", "timestamp": "2026-09-01T10:03:30Z",
             "compactMetadata": {"trigger": "auto", "preTokens": 250000}},
            {"type": "cost-state", "sessionId": sid, "totalCostUSD": 0.42, "totalLinesAdded": 12,
             "totalLinesRemoved": 3, "totalAPIDuration": 5000,
             "modelUsage": {"claude-opus-5-5": {"outputTokens": 170, "costUSD": 0.42}}},
        ]
        write_jsonl(os.path.join(d, sid + ".jsonl"), records)
        sub = os.path.join(d, sid, "subagents", "agent-abc.jsonl")
        write_jsonl(sub, [
            {**base, "type": "assistant", "isSidechain": True, "timestamp": "2026-09-01T10:00:30Z",
             "message": {"id": "sub_1", "model": "claude-haiku-4-5", "usage": usage(3, 20, 500, write_5m=10),
                         "content": [{"type": "tool_use", "id": "s1", "name": "Bash", "input": {"command": "rg config"}}]}},
        ])
        with open(sub[:-6] + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump({"agentType": "Explore", "description": "find the config"}, fh)
        # A second, unrelated session for selection tests.
        sid2 = "22222222-aaaa-bbbb-cccc-000000000002"
        write_jsonl(os.path.join(d, sid2 + ".jsonl"), [
            {"sessionId": sid2, "type": "user", "timestamp": "2026-09-10T09:00:00Z", "origin": {"kind": "human"},
             "message": {"role": "user", "content": "Unrelated question"}},
            {"sessionId": sid2, "type": "assistant", "timestamp": "2026-09-10T09:00:05Z",
             "message": {"id": "m9", "model": "claude-sonnet-5", "usage": usage(1, 9, 0), "content": []}},
        ])

    @classmethod
    def _copilot(cls):
        ws = os.path.join(cls.vscode, "workspaceStorage", "abc123")
        os.makedirs(os.path.join(ws, "chatSessions"))
        uri = "file:///" + cls.project.replace("\\", "/").replace(":", "%3A")
        with open(os.path.join(ws, "workspace.json"), "w", encoding="utf-8") as fh:
            json.dump({"folder": uri}, fh)
        request = {
            "requestId": "r1", "timestamp": 1788000000000, "message": {"text": "Add a login page"},
            "modeInfo": {"kind": "agent"}, "agent": {"id": "github.copilot.editsAgent"},
            "result": {"details": "GPT-4.1 • 0x", "timings": {"totalElapsed": 30000}},
            "response": [
                {"kind": "toolInvocationSerialized", "toolId": "run_in_terminal",
                 "toolSpecificData": {"kind": "terminal", "commandLine": {"original": "npm install express"}}},
                {"kind": "textEditGroup", "uri": {"fsPath": os.path.join(cls.project, "login.html")}},
                {"kind": "markdownContent", "value": "Created the login page."}],
        }
        write_jsonl(os.path.join(ws, "chatSessions", "s1.jsonl"), [
            {"kind": 0, "v": {"version": 3, "sessionId": "copilot-s1", "requests": []}},
            {"kind": 2, "k": ["requests"], "v": [request]},
        ])

    @classmethod
    def _codex(cls):
        f = os.path.join(cls.codex, "sessions", "2026", "09", "05", "rollout-x.jsonl")
        # A reviewer session Codex started itself: a sub-agent of the main one, not a user session.
        write_jsonl(os.path.join(cls.codex, "sessions", "2026", "09", "05", "rollout-review.jsonl"), [
            {"timestamp": "2026-09-05T08:00:11Z", "type": "session_meta",
             "payload": {"id": "child-1", "cwd": cls.project, "parent_thread_id": "codex-main",
                         "thread_source": "guardian_review"}},
            {"timestamp": "2026-09-05T08:00:12Z", "type": "turn_context", "payload": {"model": "codex-auto-review"}},
            {"timestamp": "2026-09-05T08:00:12Z", "type": "response_item",
             "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Assess this action"}]}},
            {"timestamp": "2026-09-05T08:00:13Z", "type": "event_msg",
             "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 50, "output_tokens": 7}}}},
        ])
        write_jsonl(f, [
            {"timestamp": "2026-09-05T08:00:00Z", "type": "session_meta",
             "payload": {"id": "codex-main", "cwd": cls.project, "cli_version": "0.150.0", "originator": "codex_cli"}},
            {"timestamp": "2026-09-05T08:00:01Z", "type": "turn_context",
             "payload": {"model": "gpt-5.6", "effort": "high", "approval_policy": "on-request",
                         "sandbox_policy": {"type": "workspace-write"}}},
            {"timestamp": "2026-09-05T08:00:02Z", "type": "response_item",
             "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Fix the build"}]}},
            {"timestamp": "2026-09-05T08:00:10Z", "type": "response_item",
             "payload": {"type": "custom_tool_call", "name": "exec",
                         "input": 'tools.exec_command({cmd:"npm run build","workdir":"C:\\\\x"})'}},
            {"timestamp": "2026-09-05T08:00:20Z", "type": "event_msg",
             "payload": {"type": "token_count", "info": {"total_token_usage": {
                 "input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 80,
                 "reasoning_output_tokens": 30}, "model_context_window": 258400}}},
        ])

    def run_extract(self, *args):
        out = os.path.join(self.tmp, "m-%d.json" % abs(hash(args)))
        cmd = [sys.executable, EXTRACT, self.project, "--projects-dir", self.projects_dir,
               "--vscode-user-dir", self.vscode, "--codex-home", self.codex, "--copilot-home", self.copilot,
               *args, "--out", out]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(out, encoding="utf-8") as fh:
            return json.load(fh), out


class ExtractTests(Fixture):
    def test_finds_all_three_tools(self):
        m, _ = self.run_extract()
        self.assertEqual(sorted({s["source"] for s in m["sessions"]}), ["claude-code", "codex", "copilot-vscode"])
        self.assertEqual(len(m["available_sessions"]), 4)

    def test_claude_usage_counted_once_per_message_and_subagents_included(self):
        m, _ = self.run_extract("--session", "1111")
        rows = {(r["model"], r["scope"]): r for r in m["usage"]["rows"]}
        main = rows[("claude-opus-5-5", "main")]
        self.assertEqual(main["output"], 155)          # 100 + 5 + 50, not 255
        self.assertEqual(main["cache_read"], 3010)
        self.assertEqual(main["cache_write_1h"], 50)
        self.assertEqual(main["thinking"], 40)
        self.assertEqual(main["turns"], 3)
        sub = rows[("claude-haiku-4-5", "subagent")]
        self.assertEqual(sub["output"], 20)
        self.assertEqual(sub["cache_write_5m"], 10)

    def test_claude_prompts_and_human_actions(self):
        m, _ = self.run_extract("--session", "1111")
        texts = [p["text"] for p in m["prompts"]]
        self.assertEqual(len(texts), 3)                 # task-notification is not a prompt
        self.assertIn("/review high", texts)
        self.assertEqual(m["prompts"][2]["kind"], "continue")
        self.assertIn("[REDACTED:anthropic-key]", texts[0])
        self.assertNotIn("sk-ant-", json.dumps(m))
        self.assertEqual(m["work"]["tool_errors"], 1)
        q = m["timeline"][0]["questions"][0]
        self.assertEqual(q["question"], "Keep git out of it?")
        self.assertIn("no git", q["answer"])
        self.assertIn("I need a decision from you.", m["timeline"][0]["notes"])

    def test_claude_setup_extensions_tools(self):
        m, _ = self.run_extract("--session", "1111")
        s = m["setup"]
        self.assertEqual(s["effort"], {"xhigh": 3})
        self.assertEqual(s["modes"]["permission_modes"], {"auto": 1})
        self.assertEqual(s["models"][0]["name"], "Opus 5.5")
        self.assertEqual(len(s["context"]["compactions"]), 1)
        self.assertEqual(s["instruction_files"][0]["type"], "User")
        e = m["extensions"]
        self.assertEqual(e["skills"][0]["name"], "skill-creator")
        self.assertEqual(e["mcp_servers"][0]["server"], "github")
        self.assertEqual(e["subagents"][0]["type"], "Explore")
        t = m["non_ai_tools"]
        self.assertIn({"manager": "pip", "packages": ["requests"],
                       "command": "pip install requests && git commit -m 'feat: add widget'"}, t["installs"])
        self.assertIn("requests", t["imports"]["python"])
        self.assertIn("os (stdlib)", t["imports"]["python"])
        names = [x["name"] for x in t["executables"]]
        self.assertIn("rg", names)                      # run by the sub-agent
        self.assertEqual(m["work"]["git_commits"][0]["message"], "feat: add widget")

    def test_claude_reported_cost_complete(self):
        m, _ = self.run_extract("--session", "1111")
        rc = m["usage"]["reported_cost"]
        self.assertTrue(rc["complete"], rc)
        self.assertAlmostEqual(rc["total_usd"], 0.42)

    def test_copilot_best_effort(self):
        m, _ = self.run_extract("--transcripts", os.path.join(self.vscode, "workspaceStorage", "abc123", "chatSessions"))
        self.assertEqual(m["prompts"][0]["text"], "Add a login page")
        self.assertEqual(m["usage"]["copilot"]["by_model"]["GPT-4.1"]["multiplier"], 0.0)
        self.assertEqual(m["setup"]["modes"]["copilot_modes"], {"agent": 1})
        self.assertEqual(m["non_ai_tools"]["installs"][0]["packages"], ["express"])
        self.assertTrue(m["work"]["files_written"][0]["path"].endswith("login.html"))

    def test_codex_child_sessions_fold_into_parent(self):
        m, _ = self.run_extract()
        codex = [s for s in m["sessions"] if s["source"] == "codex"]
        self.assertEqual(len(codex), 1)
        self.assertEqual(codex[0]["subagent_count"], 1)
        self.assertNotIn("Assess this action", [p["text"] for p in m["prompts"]])
        rows = {(r["model"], r["scope"]): r for r in m["usage"]["rows"]}
        self.assertEqual(rows[("codex-auto-review", "subagent")]["output"], 7)

    def test_codex_best_effort(self):
        m, _ = self.run_extract("--transcripts", os.path.join(self.codex, "sessions", "**", "rollout-x.jsonl"))
        row = m["usage"]["rows"][0]
        self.assertEqual((row["model"], row["input"], row["cache_read"], row["output"], row["thinking"]),
                         ("gpt-5.6", 400, 600, 80, 30))
        self.assertEqual(m["setup"]["context"]["window_tokens"], 258400)
        self.assertEqual(m["prompts"][0]["text"], "Fix the build")
        self.assertIn("npm", [x["name"] for x in m["non_ai_tools"]["executables"]])

    def test_selection_by_window_and_latest(self):
        m, _ = self.run_extract("--since", "2026-09-09", "--until", "2026-09-11")
        self.assertEqual([s["session_id"][:4] for s in m["sessions"]], ["2222"])
        m, _ = self.run_extract("--latest", "1")
        self.assertEqual(len(m["sessions"]), 1)

    def test_no_logs_means_no_ai(self):
        empty = os.path.join(self.tmp, "empty_folder")
        os.makedirs(empty, exist_ok=True)
        out = os.path.join(self.tmp, "none.json")
        subprocess.run([sys.executable, EXTRACT, empty, "--projects-dir", self.projects_dir, "--vscode-user-dir",
                        self.vscode, "--codex-home", self.codex, "--copilot-home", self.copilot, "--out", out],
                       check=True, capture_output=True)
        with open(out, encoding="utf-8") as fh:
            m = json.load(fh)
        self.assertFalse(m["ai_used"])


class RenderTests(Fixture):
    def test_render_then_check(self):
        _, metrics = self.run_extract()
        report = os.path.join(self.tmp, "report.md")
        subprocess.run([sys.executable, RENDER, metrics, "--out", report], check=True, capture_output=True)
        res = subprocess.run([sys.executable, RENDER, "--check", report], capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("unfilled", res.stdout)
        with open(report, encoding="utf-8") as fh:
            text = fh.read()
        for heading in ("## 1. Summary", "## 5. Tokens and cost", "## 11. Replicate it", "### B. All prompts, word for word"):
            self.assertIn(heading, text)
        self.assertIn("premium requests", text)        # Copilot cost basis
        filled = re.sub(r"<!-- WRITE[^>]*-->", "written", text)
        with open(report, "w", encoding="utf-8") as fh:
            fh.write(filled)
        res = subprocess.run([sys.executable, RENDER, "--check", report], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)
        broken = filled.replace("## 10. Review", "## Review")
        with open(report, "w", encoding="utf-8") as fh:
            fh.write(broken)
        res = subprocess.run([sys.executable, RENDER, "--check", report], capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)

    def test_prices_drive_estimate(self):
        _, metrics = self.run_extract("--session", "2222")
        prices = os.path.join(self.tmp, "prices.json")
        with open(prices, "w", encoding="utf-8") as fh:
            json.dump({"source": "test", "fetched": "2026-10-01",
                       "models": {"claude-sonnet-5": {"input": 1000000, "output": 1000000, "cache_read": 0}}}, fh)
        report = os.path.join(self.tmp, "priced.md")
        subprocess.run([sys.executable, RENDER, metrics, "--prices", prices, "--out", report], check=True, capture_output=True)
        with open(report, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("$10.00", text)                 # (1 + 9) tokens at $1 per token
        self.assertIn("estimate", text)

    def test_no_ai_report_passes_check(self):
        empty = os.path.join(self.tmp, "empty2")
        os.makedirs(empty, exist_ok=True)
        out = os.path.join(self.tmp, "none2.json")
        subprocess.run([sys.executable, EXTRACT, empty, "--projects-dir", self.projects_dir, "--vscode-user-dir",
                        self.vscode, "--codex-home", self.codex, "--copilot-home", self.copilot, "--out", out],
                       check=True, capture_output=True)
        report = os.path.join(self.tmp, "none2.md")
        subprocess.run([sys.executable, RENDER, out, "--out", report], check=True, capture_output=True)
        with open(report, encoding="utf-8") as fh:
            self.assertIn("no AI was used", fh.read())
        res = subprocess.run([sys.executable, RENDER, "--check", report], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)


class UnitTests(unittest.TestCase):
    def test_shell_write_targets(self):
        cmd = ("echo hi > out.txt && cat a >> /tmp/log.txt 2>/dev/null; sed -i 's/x/y/' README.md; "
               "cp a.md b.md; echo \"a > b\" ; 'x' | tee notes.md")
        self.assertEqual(ex.shell_write_targets(cmd), ["out.txt", "/tmp/log.txt", "README.md", "b.md", "notes.md"])

    def test_exe_category_checks_the_path(self):
        self.assertEqual(ex.exe_category("ls"), "shell utility")
        self.assertEqual(ex.exe_category("Get-ChildItem"), "PowerShell cmdlet")
        self.assertEqual(ex.exe_category("python -m pytest"), "python module")
        self.assertEqual(ex.exe_category("iteration-3-not-a-program"), "not on PATH now")

    def test_encoding_replaces_every_non_alphanumeric(self):
        self.assertEqual(ex.encode_claude_dir(r"C:\projects\VS_prj\My App"), "C--projects-VS-prj-My-App")

    def test_executables_ignore_inline_scripts_and_quotes(self):
        cmd = 'grep -n "a|b" f | head -3; python -c "\nimport os\nprint(1)\n"; cat > x <<\'EOF\'\nfoo | bar\nEOF\nnode app.js'
        self.assertEqual(ex.executables(cmd), ["grep", "head", "python", "cat", "node"])


if __name__ == "__main__":
    unittest.main()

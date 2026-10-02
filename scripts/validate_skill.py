#!/usr/bin/env python3
"""Repository-local validation for the how-did-you-do-that skill.

Checks the standard AgentSkill repo files and the SKILL.md frontmatter.
Exit 0 = pass, 1 = failures found. Stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "evals/evals.json",
    "scripts/extract_session.py",
    "scripts/render_report.py",
    "assets/report-template.md",
    "references/review-guide.md",
    "references/pricing-sources.md",
    "references/log-formats.md",
]

REQUIRED_SECTIONS = [
    "## What this skill is for",
    "## Workflow",
]


def parse_frontmatter(content: str):
    if not content.startswith("---\n"):
        return {}, "must start with YAML frontmatter"
    try:
        _, fm, _ = content.split("---\n", 2)
    except ValueError:
        return {}, "frontmatter must be closed with ---"
    values = {}
    for line in fm.splitlines():
        if not line.strip() or line[0] in " \t":
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            values[m.group(1)] = m.group(2).strip().strip('"')
    return values, None


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    errors: list[str] = []
    warnings: list[str] = []

    for rel in REQUIRED_FILES:
        if not (root / rel).exists():
            errors.append(f"missing required file: {rel}")

    core = root / "SKILL.md"
    if core.exists():
        content = core.read_text(encoding="utf-8")
        fm, err = parse_frontmatter(content)
        if err:
            errors.append(f"SKILL.md: {err}")
        else:
            name = fm.get("name", "")
            desc = fm.get("description", "")
            if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
                errors.append(f"SKILL.md: name '{name}' must be lowercase hyphen-case (1-64 chars)")
            if name != "how-did-you-do-that":
                errors.append(f"SKILL.md: name must be 'how-did-you-do-that', got '{name}'")
            if not desc:
                errors.append("SKILL.md: description is required")
            if len(desc) > 1024:
                errors.append(f"SKILL.md: description must be <= 1024 chars (is {len(desc)})")
            if fm.get("license", "").upper() != "MIT":
                warnings.append("SKILL.md: license should be MIT")
            if not desc.startswith("Use when"):
                warnings.append("SKILL.md: description should start with 'Use when' (discovery convention)")
        for sec in REQUIRED_SECTIONS:
            if sec not in content:
                errors.append(f"SKILL.md missing required section: {sec}")

    print(f"how-did-you-do-that validation @ {root}")
    for w in warnings:
        print(f"  WARN: {w}")
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        print(f"RESULT: FAIL ({len(errors)} error(s), {len(warnings)} warning(s))")
        return 1
    print(f"RESULT: PASS ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

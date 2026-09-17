#!/usr/bin/env python3
"""Gate drift checker for Tokenome repos.

Asserts:
  (a) No duplicated lint/format/typecheck commands in .github/workflows/*.yml
      outside khodex-rei/tokenome-quality-actions call sites.
  (b) pre-commit hook revs for ruff/isort match uv.lock package versions.

Exits nonzero and prints named findings on drift.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import textwrap
import tomllib
from pathlib import Path

# ponytail: line-based YAML scan, not a full parser; adequate for assertion
CALLOUT_RE = re.compile(r"khodex-rei/tokenome-quality-actions/")
JOB_NAME_RE = re.compile(r"^(\s+)([\w.-]+):\s*(?:#.*)?$")
JOB_SECTION_END_RE = re.compile(r"^\S")
RUN_STEP_RE = re.compile(r"^\s*-?\s*run:\s*(.*)$")
HOOK_REPO_RE = re.compile(r"^\s*-?\s*repo:\s*https://github\.com/(\S+)")
HOOK_REV_RE = re.compile(r"^\s*-?\s*rev:\s*[\"']?([^\s\"']+)")

GATE_COMMAND_RE = re.compile(
    r"^(uv\s+run\s+)?(ruff|isort|mypy|sqlfluff|prettier|eslint|tsc|turbo)\b"
)
GATE_PATTERNS = [
    re.compile(r"\bruff\s+format\b"),
    re.compile(r"\bruff\s+check\b"),
    re.compile(r"\bisort\b"),
    re.compile(r"\bmypy\b"),
    re.compile(r"\bsqlfluff\s+lint\b"),
    re.compile(r"\bprettier\b"),
    re.compile(r"\beslint\b"),
    re.compile(r"\btsc\b"),
    re.compile(r"\bturbo\s+run\s+(lint|check-types)\b"),
    re.compile(r"\bformat:check\b"),
]

HOOK_REPOS = {
    "astral-sh/ruff-pre-commit": "ruff",
    "pycqa/isort": "isort",
}


def find_jobs(lines: list[str]):
    """Yield (name, call_site, [(lineno, line)]) for each job under jobs:."""
    jobs_start = None
    for i, line in enumerate(lines):
        if re.match(r"^jobs:\s*(?:#.*)?$", line):
            jobs_start = i
            break
    if jobs_start is None:
        return

    job_indent: int | None = None
    current: dict | None = None

    for i in range(jobs_start + 1, len(lines)):
        line = lines[i]
        if line.strip() and JOB_SECTION_END_RE.match(line):
            break
        m = JOB_NAME_RE.match(line)
        if m:
            indent = len(m.group(1))
            if job_indent is None and indent > 0:
                job_indent = indent
            if indent == job_indent:
                if current is not None:
                    yield (current["name"], current["call_site"], current["lines"])
                current = {"name": m.group(2), "call_site": False, "lines": []}
                continue
        if current is not None:
            current["lines"].append((i + 1, line))
            if CALLOUT_RE.search(line):
                current["call_site"] = True

    if current is not None:
        yield (current["name"], current["call_site"], current["lines"])


def is_gate_command(line: str) -> bool:
    stripped = line.strip()
    stripped = re.sub(r"^-\s*", "", stripped)
    stripped = re.sub(r"^run:\s*", "", stripped)
    if not stripped or stripped.startswith("#"):
        return False
    if not GATE_COMMAND_RE.match(stripped):
        return False
    return any(p.search(stripped) for p in GATE_PATTERNS)


def check_duplication(repo: Path) -> list[str]:
    findings = []
    wf_dir = repo / ".github" / "workflows"
    if not wf_dir.is_dir():
        return findings
    for yml in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        lines = yml.read_text(encoding="utf-8").splitlines()
        for name, call_site, job_lines in find_jobs(lines):
            if call_site:
                continue
            for lineno, line in job_lines:
                if is_gate_command(line):
                    findings.append(
                        f"[FAIL] duplication: {yml.name}:{lineno} "
                        f"job={name} command={line.strip()!r} "
                        f"— gate command outside composite-call site"
                    )
    return findings


def check_lockfile(repo: Path) -> list[str]:
    findings = []
    pc = repo / ".pre-commit-config.yaml"
    if not pc.exists():
        pc = repo / ".pre-commit-config.yml"
    if not pc.exists():
        return findings

    hooks: dict[str, str] = {}
    pending_repo = None
    for line in pc.read_text(encoding="utf-8").splitlines():
        m = HOOK_REPO_RE.match(line)
        if m:
            pending_repo = m.group(1).rstrip("/")
            continue
        m = HOOK_REV_RE.match(line)
        if m and pending_repo:
            pkg = HOOK_REPOS.get(pending_repo)
            if pkg:
                hooks[pkg] = m.group(1)
            pending_repo = None

    lock = repo / "uv.lock"
    if not lock.exists() or not hooks:
        return findings

    data = tomllib.loads(lock.read_text(encoding="utf-8"))
    versions = {p["name"]: p["version"] for p in data.get("package", [])}
    for pkg, rev in hooks.items():
        ver = versions.get(pkg)
        norm_rev = rev.lstrip("v")
        if ver is None:
            findings.append(
                f"[FAIL] lockfile: pre-commit hook '{pkg}' rev {rev} "
                f"has no matching entry in uv.lock"
            )
        elif ver != norm_rev:
            findings.append(
                f"[FAIL] lockfile: pre-commit hook '{pkg}' rev {rev} "
                f"!= uv.lock {pkg} {ver}"
            )
    return findings


def check_repo(repo: Path) -> list[str]:
    return check_duplication(repo) + check_lockfile(repo)


def selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".github" / "workflows").mkdir(parents=True)
        (repo / ".github" / "workflows" / "quality.yml").write_text(
            textwrap.dedent("""\
                name: quality
                on: [push]
                jobs:
                  lint:
                    runs-on: ubuntu-latest
                    steps:
                      - uses: actions/checkout@v5
                      - run: uv run ruff check src
                  via-action:
                    runs-on: ubuntu-latest
                    steps:
                      - uses: khodex-rei/tokenome-quality-actions/python-quality@v1
                """)
        )
        (repo / ".pre-commit-config.yaml").write_text(
            textwrap.dedent("""\
                repos:
                  - repo: https://github.com/astral-sh/ruff-pre-commit
                    rev: v0.12.0
                    hooks:
                      - id: ruff
                """)
        )
        (repo / "uv.lock").write_text(
            textwrap.dedent("""\
                version = 1
                [[package]]
                name = "ruff"
                version = "0.15.11"
                """)
        )
        findings = check_repo(repo)
        assert any("duplication" in f and "quality.yml" in f for f in findings), findings
        assert any("lockfile" in f and "v0.12.0" in f for f in findings), findings
        assert not any("via-action" in f for f in findings), findings
        print(f"selftest: PASS ({len(findings)} expected findings)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repos", nargs="*", type=Path, default=[Path(".")])
    ap.add_argument("--selftest", action="store_true", help="run built-in self-test")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    failed = False
    for repo in args.repos:
        findings = check_repo(repo)
        print(f"gate-drift: {repo}")
        for f in findings:
            print(f"  {f}")
        if findings:
            failed = True
    print("gate-drift: " + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

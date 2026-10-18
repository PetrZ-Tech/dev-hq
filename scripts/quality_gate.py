from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import importlib.util
import quality_commands as command_policy
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

PROJECTS_ROOT = Path(os.environ.get("DEV_HQ_PROJECTS_ROOT", str(Path.home() / "Projects"))).expanduser().resolve()
STATUS_ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}

SAFE_AUTO_SCRIPT_NAMES = ("test", "typecheck", "lint", "build")

SENSITIVE_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development.local",
    "id_rsa", "id_ed25519", "credentials.json", "service-account.json",
}

SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "generic-secret-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|token|password|passwd|secret|client[_-]?secret)\b\s*[:=]\s*[\"']?([^\s\"'#]{8,})"
        ),
    ),
]

PLACEHOLDER_MARKERS = {
    "changeme", "change-me", "example", "placeholder", "your_", "your-", "xxx",
    "dummy", "test", "sample", "<", "${", "process.env", "env.",
}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".sh", ".ps1", ".env",
    ".sql", ".html", ".css", ".xml", ".csv",
}


@dataclass
class Check:
    name: str
    status: str
    detail: str


def worst_status(checks: Iterable[Check]) -> str:
    current = "PASS"
    for c in checks:
        if STATUS_ORDER[c.status] > STATUS_ORDER[current]:
            current = c.status
    return current


def run(cmd: list[str] | str, cwd: Path, timeout: int = 900, shell: bool = False) -> tuple[int, str]:
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=shell,
        )
        output = ((cp.stdout or "") + (cp.stderr or "")).strip()
        return cp.returncode, output
    except subprocess.TimeoutExpired:
        return 124, f"Timed out after {timeout}s"
    except Exception as exc:
        return 125, f"Runner error: {type(exc).__name__}: {exc}"


def is_inside_projects(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROJECTS_ROOT)
        return True
    except ValueError:
        return False


def git_available(project: Path) -> bool:
    code, _ = run(["git", "rev-parse", "--is-inside-work-tree"], project, timeout=20)
    return code == 0


def git_check(project: Path) -> tuple[list[Check], list[str], list[str]]:
    checks: list[Check] = []
    changed_files: list[str] = []
    untracked_files: list[str] = []

    if not git_available(project):
        checks.append(Check("git", "WARN", "Not a Git work tree"))
        return checks, changed_files, untracked_files

    _, branch = run(["git", "branch", "--show-current"], project, timeout=20)
    code, status = run(["git", "status", "--porcelain=v1"], project, timeout=20)
    if code != 0:
        checks.append(Check("git-status", "FAIL", "git status failed"))
        return checks, changed_files, untracked_files

    for line in status.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if line.startswith("??"):
            untracked_files.append(path)
        else:
            changed_files.append(path)

    dirty_count = len(changed_files) + len(untracked_files)
    checks.append(
        Check(
            "git-status",
            "PASS",
            f"branch={branch.strip() or '(detached/unborn)'}, changed={len(changed_files)}, untracked={len(untracked_files)}",
        )
    )

    diff_code, diff_out = run(["git", "diff", "--check"], project, timeout=60)
    cached_code, cached_out = run(["git", "diff", "--cached", "--check"], project, timeout=60)
    if diff_code != 0 or cached_code != 0:
        detail = "git diff --check found whitespace/conflict-marker problems"
        snippets = [x for x in (diff_out, cached_out) if x]
        if snippets:
            detail += ": " + " | ".join(s.splitlines()[0] for s in snippets[:2])
        checks.append(Check("git-diff-check", "FAIL", detail))
    else:
        checks.append(Check("git-diff-check", "PASS", "No whitespace/conflict-marker errors"))

    if dirty_count == 0:
        checks.append(Check("working-tree", "PASS", "Working tree clean"))
    else:
        checks.append(Check("working-tree", "PASS", f"Dirty tree is allowed; {dirty_count} path(s) need review"))

    return checks, changed_files, untracked_files


def added_diff_lines(project: Path) -> list[tuple[str, int | None, str]]:
    results: list[tuple[str, int | None, str]] = []
    commands = [
        ["git", "diff", "--no-ext-diff", "--unified=0"],
        ["git", "diff", "--cached", "--no-ext-diff", "--unified=0"],
    ]
    for cmd in commands:
        code, out = run(cmd, project, timeout=120)
        if code != 0:
            continue
        current_file = ""
        current_line: int | None = None
        for raw in out.splitlines():
            if raw.startswith("+++ b/"):
                current_file = raw[6:]
                current_line = None
                continue
            if raw.startswith("@@"):
                m = re.search(r"\+(\d+)(?:,\d+)?", raw)
                current_line = int(m.group(1)) if m else None
                continue
            if raw.startswith("+") and not raw.startswith("+++"):
                results.append((current_file, current_line, raw[1:]))
                if current_line is not None:
                    current_line += 1
            elif raw.startswith("-") and not raw.startswith("---"):
                continue
            elif current_line is not None and not raw.startswith("\\"):
                current_line += 1
    return results


def looks_placeholder(value: str) -> bool:
    v = value.lower()
    return any(marker in v for marker in PLACEHOLDER_MARKERS)


def scan_line_for_secret(line: str) -> str | None:
    for label, pattern in SECRET_PATTERNS:
        m = pattern.search(line)
        if not m:
            continue
        if label == "generic-secret-assignment":
            value = m.group(1) if m.lastindex else ""
            if looks_placeholder(value):
                continue
        return label
    return None


def is_text_candidate(path: Path) -> bool:
    if path.name.startswith(".env"):
        return True
    return path.suffix.lower() in TEXT_EXTENSIONS or path.suffix == ""


def secret_check(project: Path, untracked_files: list[str]) -> list[Check]:
    findings: list[str] = []

    for rel in untracked_files:
        p = project / rel
        if p.name in SENSITIVE_FILENAMES and p.name not in {".env.example", ".env.sample"}:
            findings.append(f"sensitive-file:{rel}")

    for rel, line_no, line in added_diff_lines(project):
        label = scan_line_for_secret(line)
        if label:
            suffix = f":{line_no}" if line_no is not None else ""
            findings.append(f"{label}:{rel}{suffix}")

    for rel in untracked_files:
        p = project / rel
        if not p.is_file() or not is_text_candidate(p):
            continue
        try:
            if p.stat().st_size > 1_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            label = scan_line_for_secret(line)
            if label:
                findings.append(f"{label}:{rel}:{idx}")
                if len(findings) >= 20:
                    break
        if len(findings) >= 20:
            break

    findings = sorted(set(findings))
    if findings:
        preview = ", ".join(findings[:8])
        more = f" (+{len(findings)-8} more)" if len(findings) > 8 else ""
        return [Check("secrets", "FAIL", f"Potential secret(s) detected by location only: {preview}{more}")]
    return [Check("secrets", "PASS", "No high-confidence secrets found in added/untracked text")]


def load_quality_config(project: Path) -> dict:
    config_path = project / ".hq-quality-gate.json"
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("root must be object")
        return data
    except Exception as exc:
        return {"_config_error": str(exc)}


def npm_auto_commands(project: Path) -> list[dict]:
    scripts, _ = command_policy.package(project)
    result: list[dict] = []
    for name in SAFE_AUTO_SCRIPT_NAMES:
        if name in scripts:
            command = ["npm", "run", name]
            result.append({"name": name, "command": command, "required": True,
                           "plan": command_policy.compile_plan(project, command)})
    return result


def python_auto_commands(project: Path) -> list[dict]:
    indicators = [project / "pyproject.toml", project / "pytest.ini", project / "tests"]
    if not any(p.exists() for p in indicators):
        return []
    if importlib.util.find_spec("pytest") is not None:
        return [{"name": "test", "command": [sys.executable, "-m", "pytest"], "required": True}]
    return []


def fallback_commands(project: Path) -> list[dict]:
    if (project / "test.js").exists():
        return [{"name": "test", "command": ["node", "test.js"], "required": True}]
    return []


def _discover_commands(project: Path, config: dict) -> tuple[list[dict], list[Check]]:
    checks: list[Check] = []
    if "_config_error" in config:
        return [], [Check("quality-config", "FAIL", f"Invalid .hq-quality-gate.json: {config['_config_error']}")]

    configured = config.get("commands", [])
    if not isinstance(configured, list) or type(config.get("skip_auto_commands", False)) is not bool:
        raise command_policy.Refused("commands must be an array and skip_auto_commands a boolean")
    commands: list[dict] = []
    if configured:
        if not isinstance(configured, list):
            return [], [Check("quality-config", "FAIL", "commands must be an array")]
        for item in configured:
            if not isinstance(item, dict) or not item.get("name") or not item.get("command"):
                return [], [Check("quality-config", "FAIL", "Each command needs name and command")]
            if (not isinstance(item['name'], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', item['name'])
                    or type(item.get('required', True)) is not bool or command_policy.blocked(item['name'])):
                raise command_policy.Refused("Invalid or unsafe check name/required flag")
            if any(c['name'] == item['name'] for c in commands):
                raise command_policy.Refused("Duplicate configured check name")
            commands.append({
                "name": str(item["name"]),
                "command": item["command"],
                "required": bool(item.get("required", True)),
                "plan": command_policy.compile_plan(project, item["command"]),
            })

    if not bool(config.get("skip_auto_commands", False)):
        existing_names = {c["name"] for c in commands}
        for candidate in npm_auto_commands(project) + python_auto_commands(project) + fallback_commands(project):
            if candidate["name"] not in existing_names:
                candidate.setdefault('plan', command_policy.compile_plan(project, candidate['command']))
                commands.append(candidate)
                existing_names.add(candidate["name"])

    return commands, checks


def discover_commands(project: Path, config: dict) -> tuple[list[dict], list[Check]]:
    try:
        return _discover_commands(project, config)
    except (command_policy.Refused, OSError, TypeError, ValueError) as exc:
        return [], [Check('command-preflight', 'FAIL', str(exc))]


def automated_checks(project: Path, skip_exec: bool) -> list[Check]:
    config = load_quality_config(project)
    commands, config_checks = discover_commands(project, config)
    if config_checks:
        return config_checks
    if not commands:
        return [Check("automated-checks", "WARN", "No safe test/typecheck/lint/build command discovered")]
    if skip_exec:
        names = ", ".join(c["name"] for c in commands)
        return [Check("automated-checks", "WARN", f"Execution skipped; discovered: {names}")]

    checks: list[Check] = []
    deadline = time.monotonic() + 1200
    for spec in commands:
        name = spec["name"]
        required = bool(spec.get("required", True))
        try:
            command_policy.verify_snapshot(project, spec['plan'])
            code, out = 0, ''
            for step in spec['plan']['steps']:
                command_policy.verify_snapshot(project, spec['plan'])
                argv = command_policy.resolve_argv(project, step['argv'])
                remaining = int(deadline - time.monotonic())
                if remaining <= 0:
                    raise command_policy.Refused('Total automated-check time budget exhausted')
                code, out = run(argv, project, timeout=remaining, shell=False)
                if code != 0:
                    break
        except (command_policy.Refused, OSError, ValueError) as exc:
            checks.append(Check('command-preflight', 'FAIL', str(exc)))
            break
        if code == 0:
            detail = "PASS"
            if out:
                last = out.splitlines()[-1].strip()
                if last:
                    detail += f" — {last[:180]}"
            checks.append(Check(name, "PASS", detail))
        else:
            level = "FAIL" if required else "WARN"
            tail = " | ".join(out.splitlines()[-3:])[:500] if out else f"exit={code}"
            checks.append(Check(name, level, f"exit={code}: {tail}"))
            break
    return checks


def task_criteria_check(value: str) -> Check:
    value = value.lower()
    if value == "yes":
        return Check("task-criteria", "PASS", "Current task acceptance criteria confirmed")
    if value == "no":
        return Check("task-criteria", "FAIL", "At least one current task criterion is not satisfied")
    return Check("task-criteria", "WARN", "Task acceptance criteria not confirmed by mechanical runner")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dev HQ Quality Gate")
    parser.add_argument("--project", required=True, help="Absolute project path inside <PROJECTS_ROOT>")
    parser.add_argument("--criteria-ok", choices=["yes", "no", "unknown"], default="unknown")
    parser.add_argument("--skip-exec", action="store_true", help="Inspect without running test/lint/build")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    project = Path(args.project).resolve()
    checks: list[Check] = []

    if not project.exists() or not project.is_dir():
        checks.append(Check("scope", "FAIL", f"Project path does not exist: {project}"))
    elif not is_inside_projects(project):
        checks.append(Check("scope", "FAIL", f"Project is outside allowed root: {PROJECTS_ROOT}"))
    else:
        checks.append(Check("scope", "PASS", str(project)))
        git_checks, _, untracked = git_check(project)
        checks.extend(git_checks)
        if git_available(project):
            checks.extend(secret_check(project, untracked))
        else:
            checks.append(Check("secrets", "WARN", "Git diff unavailable; secret scan coverage incomplete"))
        checks.extend(automated_checks(project, args.skip_exec))
        checks.append(task_criteria_check(args.criteria_ok))

    overall = worst_status(checks)
    payload = {
        "quality_gate": overall,
        "command_policy": command_policy.POLICY_VERSION,
        "project": str(project),
        "checks": [asdict(c) for c in checks],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Quality Gate: {overall}")
        for c in checks:
            print(f"[{c.status}] {c.name}: {c.detail}")

    return 0 if overall == "PASS" else 1 if overall == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())

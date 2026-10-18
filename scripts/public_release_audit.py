from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

EXCLUDED_DIRS = {
    ".git", ".codebase-memory", ".pytest_cache", "__pycache__", "runtime", "handoffs",
    "records", "node_modules", ".next", "dist", "build", "coverage", ".venv", "venv",
}

SAFE_EXAMPLE_NAMES = {".env.example", ".env.sample"}
SENSITIVE_EXACT = {
    ".env", ".env.local", ".env.production", ".env.development", ".env.test",
    "id_rsa", "id_ed25519", "credentials.json", "service-account.json", "secrets.json",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx", ".sqlite", ".sqlite3", ".db"}
TEXT_SUFFIXES = {
    ".md", ".txt", ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".ps1", ".sh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html",
    ".css", ".xml", ".csv", ".sql", ".env",
}
PLACEHOLDER_MARKERS = (
    "example", "sample", "dummy", "test", "placeholder", "changeme", "change-me",
    "your_", "your-", "<", "${", "process.env", "env.", "replace here", "redacted",
)

SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("telegram-bot-token", re.compile(r"\b[0-9]{8,12}:[A-Za-z0-9_-]{25,}\b")),
]
GENERIC_SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|bot[_-]?token|password|passwd|secret|client[_-]?secret)\b"
    r"\s*[:=]\s*[\"']?([^\s\"'#;,]{8,})"
)
WINDOWS_USER_PATH = re.compile(r"(?i)\b[A-Z]:\\Users\\([^\\\s]+)\\")
POSIX_USER_PATH = re.compile(r"/(?:Users|home)/([^/\s]+)/")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


@dataclass(frozen=True)
class Finding:
    severity: str
    kind: str
    path: str
    line: int | None = None
    commit: str | None = None


def is_placeholder(value: str) -> bool:
    lower = value.lower()
    return any(marker in lower for marker in PLACEHOLDER_MARKERS)


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        yield path, rel


def sensitive_name(path: Path) -> bool:
    name = path.name.lower()
    if name in SAFE_EXAMPLE_NAMES or name.endswith(".env.example"):
        return False
    return (
        name in SENSITIVE_EXACT
        or (name.startswith(".env.") and name not in SAFE_EXAMPLE_NAMES)
        or path.suffix.lower() in SENSITIVE_SUFFIXES
        or any(part.lower() in {"secrets", "credentials", "private_keys"} for part in path.parts)
    )


def text_candidate(path: Path) -> bool:
    return path.name.startswith(".env") or path.suffix.lower() in TEXT_SUFFIXES or path.suffix == ""


def scan_text(text: str, rel: str, forbids: list[str], commit: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(Finding("FAIL", kind, rel, number, commit))
        match = GENERIC_SECRET.search(line)
        if match and not is_placeholder(match.group(1)):
            findings.append(Finding("FAIL", "generic-secret-assignment", rel, number, commit))
        if WINDOWS_USER_PATH.search(line) or POSIX_USER_PATH.search(line):
            findings.append(Finding("FAIL", "absolute-user-path", rel, number, commit))
        email = EMAIL.search(line)
        if email and not is_placeholder(email.group(0)) and not email.group(0).lower().endswith("@example.com"):
            findings.append(Finding("WARN", "email-address", rel, number, commit))
        lower = line.lower()
        for forbidden in forbids:
            if forbidden.lower() in lower:
                findings.append(Finding("FAIL", "forbidden-marker", rel, number, commit))
    return findings


def scan_worktree(root: Path, forbids: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path, rel_path in iter_files(root):
        rel = rel_path.as_posix()
        if sensitive_name(rel_path):
            findings.append(Finding("FAIL", "sensitive-file", rel))
            continue
        if not text_candidate(path):
            continue
        try:
            if path.stat().st_size > 2_000_000:
                findings.append(Finding("WARN", "large-text-skipped", rel))
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            findings.append(Finding("WARN", "unreadable", rel))
            continue
        findings.extend(scan_text(text, rel, forbids))
    return findings


def git(root: Path, *args: str) -> tuple[int, str]:
    try:
        cp = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
        return cp.returncode, cp.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 125, ""


def scan_history(root: Path, forbids: list[str]) -> list[Finding]:
    code, commits = git(root, "rev-list", "--all")
    if code != 0:
        return [Finding("WARN", "git-history-unavailable", ".git")]
    findings: list[Finding] = []
    for commit in [c.strip() for c in commits.splitlines() if c.strip()]:
        code, names = git(root, "ls-tree", "-r", "--name-only", commit)
        if code != 0:
            continue
        for rel in [n.strip() for n in names.splitlines() if n.strip()]:
            rel_path = Path(rel)
            if any(part in EXCLUDED_DIRS for part in rel_path.parts):
                continue
            if sensitive_name(rel_path):
                findings.append(Finding("FAIL", "sensitive-file-history", rel, commit=commit[:12]))
                continue
            if rel_path.suffix.lower() not in TEXT_SUFFIXES and rel_path.suffix != "":
                continue
            code, text = git(root, "show", f"{commit}:{rel}")
            if code == 0 and len(text) <= 2_000_000:
                findings.extend(scan_text(text, rel, forbids, commit[:12]))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a repository before public release without printing secret values.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--forbid", action="append", default=[], help="Additional exact marker that must not appear")
    parser.add_argument("--history", action="store_true", help="Also scan reachable Git history")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(json.dumps({"status": "ERROR", "error": "root is not a directory"}))
        return 2

    findings = scan_worktree(root, args.forbid)
    if args.history and (root / ".git").exists():
        findings.extend(scan_history(root, args.forbid))
    findings = sorted(set(findings), key=lambda f: (f.severity, f.kind, f.path, f.line or 0, f.commit or ""))

    fails = [f for f in findings if f.severity == "FAIL"]
    warns = [f for f in findings if f.severity == "WARN"]
    status = "FAIL" if fails else "WARN" if warns else "PASS"
    payload = {
        "status": status,
        "root": str(root),
        "files_scanned": sum(1 for _ in iter_files(root)),
        "fail_count": len(fails),
        "warning_count": len(warns),
        "findings": [asdict(f) for f in findings],
        "note": "Locations only; matched values are intentionally omitted.",
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Public release audit: {status}")
        print(f"FAIL={len(fails)} WARN={len(warns)}")
        for finding in findings:
            where = f"{finding.path}:{finding.line}" if finding.line else finding.path
            if finding.commit:
                where = f"{finding.commit}:{where}"
            print(f"[{finding.severity}] {finding.kind}: {where}")
    return 2 if fails else 1 if warns else 0


if __name__ == "__main__":
    raise SystemExit(main())

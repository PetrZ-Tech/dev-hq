from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECTS_ROOT = Path(os.environ.get("DEV_HQ_PROJECTS_ROOT", str(Path.home() / "Projects"))).expanduser().resolve()
HQ_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_ROOT = HQ_ROOT / "handoffs"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

MODEL_MAP = {
    "simple": ("current default/fast model", "Low"),
    "normal": ("current default model", "Medium"),
    "complex": ("strongest suitable reasoning model", "High"),
    "extreme": ("strongest available suitable model", "High"),
}

SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ed25519", "credentials.json", "secrets.json",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build a safe Codex/Work handoff package.")
    p.add_argument("--project", required=True, help="Local project path under <PROJECTS_ROOT>")
    p.add_argument("--project-id", help="HQ project ID; defaults to folder name")
    p.add_argument("--task", required=True, help="Concrete task for Codex")
    p.add_argument("--goal", help="Desired outcome; defaults to task")
    p.add_argument("--context", default="", help="Fresh HQ context summary")
    p.add_argument("--file", action="append", default=[], help="Relevant file, relative to project; repeatable")
    p.add_argument("--constraint", action="append", default=[], help="Additional constraint; repeatable")
    p.add_argument("--accept", action="append", default=[], help="Acceptance criterion; repeatable")
    p.add_argument("--verify", action="append", default=[], help="Verification command/check; repeatable")
    p.add_argument("--in-scope", action="append", default=[], help="In-scope item; repeatable")
    p.add_argument("--out-of-scope", action="append", default=[], help="Out-of-scope item; repeatable")
    p.add_argument("--complexity", choices=["auto", "simple", "normal", "complex", "extreme"], default="auto")
    p.add_argument("--freshness", default="LOCAL", help="Freshness marker, e.g. VERIFIED LOCAL / RECORDED")
    p.add_argument("--dry-run", action="store_true", help="Print package without writing artifact")
    return p.parse_args()


def ensure_project(path: str) -> Path:
    project = Path(path).resolve()
    if project == PROJECTS_ROOT or PROJECTS_ROOT not in project.parents:
        raise ValueError(f"Project must be inside {PROJECTS_ROOT}")
    if not project.is_dir():
        raise FileNotFoundError(f"Project does not exist: {project}")
    return project


def git(project: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout.strip()


def git_state(project: Path) -> tuple[str, str]:
    code, branch = git(project, "branch", "--show-current")
    if code != 0:
        return "n/a", "not a Git repository"
    _, status = git(project, "status", "--short")
    lines = [line for line in status.splitlines() if line.strip()]
    return branch or "detached/unknown", ("clean" if not lines else f"dirty ({len(lines)} path(s))")


def is_sensitive(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    if path.name.lower() in SENSITIVE_NAMES:
        return True
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    return "secrets" in lower_parts or "credentials" in lower_parts


def resolve_relevant(project: Path, values: list[str]) -> list[Path]:
    result: list[Path] = []
    for value in values:
        candidate = Path(value)
        full = candidate.resolve() if candidate.is_absolute() else (project / candidate).resolve()
        if full != project and project not in full.parents:
            raise ValueError(f"Relevant file escapes project: {value}")
        if not full.exists() or not full.is_file():
            raise FileNotFoundError(f"Relevant file not found: {value}")
        if is_sensitive(full):
            raise ValueError(f"Sensitive file cannot be attached to handoff: {full.name}")
        if full not in result:
            result.append(full)

    for automatic in ["PROJECT_STATE.md", "PROJECT_CONTEXT.md", "AGENTS.md", "docs/adr/README.md"]:
        full = (project / automatic).resolve()
        if full.is_file() and full not in result:
            result.insert(0, full)
    return result


def extract_state_context(project: Path) -> str:
    state = None
    for name in ["PROJECT_STATE.md", "PROJECT_CONTEXT.md"]:
        p = project / name
        if p.is_file():
            state = p
            break
    if not state:
        return "No PROJECT_STATE/PROJECT_CONTEXT found; inspect current tree before editing."

    text = state.read_text(encoding="utf-8", errors="replace")
    wanted = {"status", "verified current", "open / not done", "open", "next", "important guardrails"}
    lines = text.splitlines()
    collected: list[str] = []
    active = False
    taken = 0
    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            active = heading in wanted
            if active:
                collected.append(line)
            continue
        if active and line.strip():
            collected.append(line)
            taken += 1
            if taken >= 24:
                break
    if not collected:
        return f"State source: {state.name}. Read it before editing."
    return "\n".join(collected[:32])


def infer_complexity(task: str, file_count: int) -> str:
    t = task.lower()
    complex_terms = [
        "architecture", "архитект", "migration", "миграц", "security", "безопас",
        "concurrency", "race", "production", "продак", "distributed", "rls", "auth",
        "сложн", "root cause", "deep debug", "рефакторинг системы",
    ]
    simple_terms = ["typo", "опечат", "rename", "переимен", "текст", "readme", "документац", "small fix", "мелк"]
    if any(term in t for term in complex_terms) or file_count >= 8:
        return "complex"
    if any(term in t for term in simple_terms) and file_count <= 3:
        return "simple"
    return "normal"


def bullets(values: list[str], default: str) -> str:
    return "\n".join(f"- {v}" for v in values) if values else f"- {default}"


def slugify_task(task: str) -> str:
    text = task.lower()
    text = re.sub(r"[^a-z0-9а-яё]+", "-", text, flags=re.IGNORECASE).strip("-")
    translit = str.maketrans({
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
        "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
        "х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
    })
    text = text.translate(translit)
    text = re.sub(r"[^a-z0-9-]+", "", text).strip("-")
    return (text[:56].rstrip("-") or "task")


def build_markdown(args: argparse.Namespace, project: Path, files: list[Path]) -> tuple[str, dict]:
    branch, tree = git_state(project)
    complexity = args.complexity if args.complexity != "auto" else infer_complexity(args.task, len(files))
    model, effort = MODEL_MAP[complexity]
    auto_context = extract_state_context(project)
    context = auto_context if not args.context else f"{args.context.strip()}\n\nState excerpt:\n{auto_context}"
    project_id = args.project_id or project.name
    generated = datetime.now().astimezone()
    files_md = "\n".join(f"- `{p.relative_to(project)}`" for p in files) or "- No explicit files supplied; inspect state and locate the smallest relevant set before editing."

    constraints = [
        "Preserve unrelated user changes in a dirty working tree.",
        "Do not expose or copy secrets/credentials into output or repository files.",
        "No commit, push, deploy, publish, migration, production activation or system change unless explicitly authorized.",
    ] + args.constraint

    md = f"""# Codex Handoff — {project_id}\n\nGenerated: `{generated.strftime('%Y-%m-%d %H:%M %z')}`\nTarget: `Codex / Work`\nRecommended model: `{model}`\nRecommended reasoning: `{effort}`\nComplexity: `{complexity}`\n\n## Project\n- ID: `{project_id}`\n- Path: `{project}`\n- Branch: `{branch}`\n- Freshness: `{args.freshness}`\n- Working tree: `{tree}`\n\n## Task\n{args.task.strip()}\n\n## Goal\n{(args.goal or args.task).strip()}\n\n## Current context\n{context}\n\n## Relevant files\n{files_md}\n\n## In scope\n{bullets(args.in_scope, 'Only changes necessary to satisfy the task and acceptance criteria.')}\n\n## Out of scope\n{bullets(args.out_of_scope, 'Unrelated refactors and opportunistic cleanup.')}\n\n## Constraints / guardrails\n{bullets(constraints, 'Follow project guardrails.')}\n\n## Acceptance criteria\n{bullets(args.accept, 'Implement the requested behavior and preserve existing unrelated behavior.')}\n\n## Verification\n{bullets(args.verify, 'Run the safest applicable project-local tests/typecheck/lint/build and report exact results.')}\n\n## Execution rules\n- Read the listed state/context and relevant files before editing.\n- Inspect `git status` before changes.\n- Preserve unrelated user changes.\n- Prefer the smallest correct change.\n- Do not claim runtime/live success without an actual check.\n\n## Final response format\nReturn only:\n1. `Changed` — what changed and where.\n2. `Checks` — exact commands/tests and outcomes.\n3. `Open` — anything not completed.\n4. `Risks` — remaining technical or runtime risks.\n"""
    meta = {
        "project_id": project_id,
        "project_path": str(project),
        "branch": branch,
        "git_state": tree,
        "complexity": complexity,
        "model": model,
        "effort": effort,
        "relevant_files": [str(p.relative_to(project)) for p in files],
    }
    return md, meta


def main() -> int:
    args = parse_args()
    try:
        project = ensure_project(args.project)
        files = resolve_relevant(project, args.file)
        md, meta = build_markdown(args, project, files)
        if args.dry_run:
            print(md)
            print("\n---HANDOFF_META---")
            print(json.dumps({"status": "DRY_RUN_OK", **meta}, ensure_ascii=False, indent=2))
            return 0

        project_id = meta["project_id"]
        safe_project_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", project_id).strip("-") or project.name
        out_dir = HANDOFF_ROOT / safe_project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        out = out_dir / f"{stamp}-{slugify_task(args.task)}.md"
        out.write_text(md, encoding="utf-8")
        print(json.dumps({"status": "CREATED", "handoff": str(out), **meta}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

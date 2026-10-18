from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

PROJECTS_ROOT = Path(os.environ.get("DEV_HQ_PROJECTS_ROOT", str(Path.home() / "Projects"))).expanduser().resolve()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

RU_MAP = {
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
    "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
    "х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
}


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = "".join(RU_MAP.get(ch, ch) for ch in text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not text:
        raise ValueError("Cannot derive a valid ASCII slug; pass --slug explicitly.")
    return text


def validate_slug(slug: str) -> str:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", slug):
        raise ValueError("Slug must use lowercase a-z, 0-9 and hyphens, max 64 chars.")
    return slug


def ensure_inside_projects(path: Path) -> Path:
    root = PROJECTS_ROOT.resolve()
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Target must be a child of {root}")
    return resolved


def run_git(project_dir: Path, branch: str) -> None:
    try:
        subprocess.run(
            ["git", "init", "-b", branch],
            cwd=project_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "branch", "-M", branch], cwd=project_dir, check=True, capture_output=True, text=True)


def render_files(name: str, slug: str, purpose: str, stack: str, branch: str) -> dict[str, str]:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    stack_text = stack or "TBD"

    gitignore = """# Secrets\n.env\n.env.*\n!.env.example\n\n# Dependencies / build\nnode_modules/\n.next/\ndist/\nbuild/\ncoverage/\n.venv/\nvenv/\n__pycache__/\n*.pyc\n\n# Logs / local artifacts\n*.log\n.DS_Store\nThumbs.db\n\n# HQ local memory artifact\n.codebase-memory/\n"""

    readme = f"""# {name}\n\nStatus: **BOOTSTRAPPED / NOT YET VERIFIED**\n\n## Purpose\n{purpose}\n\n## Stack\n{stack_text}\n\n## Project ID\n`{slug}`\n\n## Working state\nRead `PROJECT_STATE.md` before substantial work. Runtime/build/test claims must be verified before being marked current.\n\n## Git\nDefault branch: `{branch}`. Remote repository is not created by bootstrap.\n"""

    project_state = f"""# PROJECT_STATE — {name}\n\nLast verified: {now}\nVerified by: bootstrap file/Git creation only\nStatus: BOOTSTRAPPED / NOT YET VERIFIED\n\n## Verified current\n- Local project scaffold exists.\n- Git repository initialized on branch `{branch}`.\n- No application build/runtime has been verified yet.\n\n## Changed this session\n- Project bootstrap created the initial project structure.\n\n## Checks\n- bootstrap scaffold creation → PASS\n- Git initialization → PASS\n\n## Open / not done\n- Application architecture and implementation are not yet verified.\n- Dependencies are not installed by bootstrap.\n- No remote repository or deployment exists unless added later.\n\n## Next\n- Confirm scope and implement the first real project milestone.\n\n## Important guardrails\n- Do not store secrets in Git.\n- Do not claim build/runtime success without an actual check.\n- Production/public actions require the normal HQ safety rules.\n\n## Key references\n- Path: `<PROJECTS_ROOT>\\{slug}`\n- Project ID: `{slug}`\n- Codebase Memory: pending HQ indexing\n"""

    agents = f"""# AGENTS — {name}\n\n## Working rules\n- Read `PROJECT_STATE.md` before substantial work.\n- Follow: plan → implement → verify → update state.\n- Before implementation of a substantial new project, agree architecture, a full technical specification and development stages.\n- Follow Dev HQ STAGED_EXECUTION.md: implement a bounded stage, verify it, save a checkpoint, then continue the approved plan.\n- Read OPERATION_CONTROL.md before potentially long tool calls; register operations and preserve result evidence.\n- On interruption read the exact saved lifecycle run, inspect unresolved operations/action keys and recover outcomes before retry.\n- Save project/run identity, last verified checkpoint, unresolved operations and first safe next step in PROJECT_STATE.md.\n- A live process or heartbeat is not proof of progress; report technical completion, prepared artifact and actual user delivery separately.\n- Prefer small reversible changes.\n- Run relevant tests/build/lint when available.\n- Never store secrets, tokens or passwords in repository files.\n- Do not commit/push/release unless explicitly requested.\n- Distinguish VERIFIED current state from TARGET/RECORDED plans.\n"""

    vision = f"""# Vision — {name}\n\n## Purpose\n{purpose}\n\n## Primary user\nTBD\n\n## Problem\nTBD\n\n## MVP outcome\nTBD\n\n## Out of scope\nTBD\n\n## Success criteria\nTBD\n"""

    architecture = f"""# Architecture — {name}\n\nStatus: TARGET / NOT YET VERIFIED\n\n## Stack\n{stack_text}\n\n## Components\nTBD\n\n## Data / integrations\nTBD\n\n## Deployment\nTBD\n\n## Security / secrets\n- Secrets must stay outside Git.\n- External/public/production actions follow Dev HQ safety boundaries.\n"""

    adr_index = """# ADR Index\n\nArchitecture Decision Records explain why important long-term choices were made.\n\n| ADR | Status | Decision |\n|---|---|---|\n\nCreate an ADR for architecture, security, storage, protocol, deployment, memory/state or other important trade-offs.\n"""

    adr_template = """# ADR-XXXX — <Decision title>\n\nStatus: `PROPOSED`\nDate: `YYYY-MM-DD`\n\n## Context\n...\n\n## Decision\n...\n\n## Why\n...\n\n## Alternatives considered\n- ...\n\n## Consequences\n### Positive\n- ...\n\n### Negative / trade-offs\n- ...\n\n## Verification / references\n- ...\n\n## Supersedes\n- none\n\n## Superseded by\n- none\n"""

    return {
        ".gitignore": gitignore,
        "README.md": readme,
        "PROJECT_STATE.md": project_state,
        "AGENTS.md": agents,
        "docs/VISION.md": vision,
        "docs/ARCHITECTURE.md": architecture,
        "docs/adr/README.md": adr_index,
        "docs/adr/ADR_TEMPLATE.md": adr_template,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a safe Dev HQ project scaffold.")
    parser.add_argument("--name", required=True, help="Human-readable project name")
    parser.add_argument("--purpose", required=True, help="Short project purpose")
    parser.add_argument("--slug", help="Project folder/ID; derived from name if omitted")
    parser.add_argument("--stack", default="", help="Initial stack description")
    parser.add_argument("--aliases", default="", help="Comma-separated aliases for HQ registry draft")
    parser.add_argument("--branch", default="main", help="Initial Git branch; default main")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print plan without writes")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        slug = validate_slug(args.slug or slugify(args.name))
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", args.branch):
            raise ValueError("Unsafe branch name.")

        target = ensure_inside_projects(PROJECTS_ROOT / slug)
        files = render_files(args.name.strip(), slug, args.purpose.strip(), args.stack.strip(), args.branch)
        aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]

        plan = {
            "name": args.name.strip(),
            "id": slug,
            "path": str(target),
            "branch": args.branch,
            "purpose": args.purpose.strip(),
            "stack": args.stack.strip() or "TBD",
            "aliases": aliases,
            "files": sorted(files.keys()),
            "git": True,
            "remote_created": False,
            "codebase_memory": "pending HQ indexing",
            "registry": "pending HQ registration",
        }

        if args.dry_run:
            if target.exists():
                print(json.dumps({
                    "status": "DRY_RUN_CONFLICT",
                    "error": f"Target already exists: {target}",
                    **plan,
                }, ensure_ascii=False, indent=2))
                return 2
            print(json.dumps({"status": "DRY_RUN_OK", **plan}, ensure_ascii=False, indent=2))
            return 0

        if target.exists():
            raise FileExistsError(f"Target already exists: {target}")

        target.mkdir(parents=True)
        for relative_path, content in files.items():
            file_path = target / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        run_git(target, args.branch)

        missing = [relative for relative in files if not (target / relative).exists()]
        if missing:
            raise RuntimeError(f"Missing created files: {missing}")
        if not (target / ".git").is_dir():
            raise RuntimeError("Git repository was not initialized")

        print(json.dumps({"status": "CREATED", **plan}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

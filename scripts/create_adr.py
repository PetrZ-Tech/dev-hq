from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

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
    return text[:70] or "decision"


def next_number(adr_dir: Path) -> int:
    nums = []
    for path in adr_dir.glob("ADR-[0-9][0-9][0-9][0-9]-*.md"):
        match = re.match(r"ADR-(\d{4})-", path.name)
        if match:
            nums.append(int(match.group(1)))
    return (max(nums) + 1) if nums else 1


def render(number: int, args: argparse.Namespace) -> str:
    alternatives = [x.strip() for x in args.alternatives.split("||") if x.strip()]
    positive = [x.strip() for x in args.positive.split("||") if x.strip()]
    negative = [x.strip() for x in args.negative.split("||") if x.strip()]
    alt_text = "\n".join(f"- {x}" for x in alternatives) or "- none recorded"
    pos_text = "\n".join(f"- {x}" for x in positive) or "- TBD"
    neg_text = "\n".join(f"- {x}" for x in negative) or "- TBD"
    return f"""# ADR-{number:04d} — {args.title.strip()}\n\nStatus: `{args.status}`\nDate: `{date.today().isoformat()}`\nDecision owners: `{args.owner}`\n\n## Context\n{args.context.strip()}\n\n## Decision\n{args.decision.strip()}\n\n## Why\n{args.why.strip()}\n\n## Alternatives considered\n{alt_text}\n\n## Consequences\n### Positive\n{pos_text}\n\n### Negative / trade-offs\n{neg_text}\n\n## Verification / references\n- {args.references.strip() or 'TBD'}\n\n## Supersedes\n- {args.supersedes.strip() or 'none'}\n\n## Superseded by\n- none\n"""


def update_index(index_path: Path, filename: str, status: str, title: str) -> None:
    row = f"| [{filename[4:12]}]({filename}) | {status} | {title} |\n"
    if not index_path.exists():
        index_path.write_text(
            "# ADR Index\n\n| ADR | Status | Decision |\n|---|---|---|\n" + row,
            encoding="utf-8",
        )
        return
    text = index_path.read_text(encoding="utf-8")
    marker = "|---|---|---|\n"
    if marker in text:
        text = text.replace(marker, marker + row, 1)
    else:
        text += "\n" + row
    index_path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an ADR for a Dev HQ project")
    parser.add_argument("--project", required=True, help="Absolute local project path")
    parser.add_argument("--title", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--why", required=True)
    parser.add_argument("--alternatives", default="", help="Separate items with ||")
    parser.add_argument("--positive", default="", help="Separate items with ||")
    parser.add_argument("--negative", default="", help="Separate items with ||")
    parser.add_argument("--references", default="")
    parser.add_argument("--supersedes", default="")
    parser.add_argument("--owner", default="Dev HQ")
    parser.add_argument("--status", choices=["PROPOSED", "ACCEPTED"], default="ACCEPTED")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    projects_root = Path(os.environ.get("DEV_HQ_PROJECTS_ROOT", str(Path.home() / "Projects"))).expanduser().resolve()
    if projects_root not in project.parents:
        print(json.dumps({"status":"ERROR","error":"project outside <PROJECTS_ROOT>"}, ensure_ascii=False))
        return 2
    if not project.is_dir():
        print(json.dumps({"status":"ERROR","error":f"project not found: {project}"}, ensure_ascii=False))
        return 2

    adr_dir = project / "docs" / "adr"
    number = next_number(adr_dir) if adr_dir.exists() else 1
    filename = f"ADR-{number:04d}-{slugify(args.title)}.md"
    target = adr_dir / filename
    content = render(number, args)

    plan = {"status":"DRY_RUN_OK" if args.dry_run else "CREATED", "number":number, "file":str(target), "title":args.title, "adr_status":args.status}
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    adr_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        print(json.dumps({"status":"ERROR","error":f"target exists: {target}"}, ensure_ascii=False))
        return 2
    target.write_text(content, encoding="utf-8")
    update_index(adr_dir / "README.md", filename, args.status, args.title.strip())
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

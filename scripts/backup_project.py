from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECTS_ROOT = Path(os.environ.get("DEV_HQ_PROJECTS_ROOT", str(Path.home() / "Projects"))).expanduser().resolve()
BACKUP_ROOT = (PROJECTS_ROOT / "_hq_backups").resolve()
DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024
DEFAULT_RETENTION = 10

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

EXCLUDED_DIRS = {
    ".git", ".codebase-memory", "node_modules", ".next", "dist", "build", "coverage",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".venv", "venv",
    "handoffs", "runtime", "_hq_backups",
}
SENSITIVE_DIR_NAMES = {"secrets", "secret", "credentials", "private", "private_keys", "keys"}
SENSITIVE_EXACT = {
    ".env", ".env.local", ".env.production", ".env.development", ".env.test",
    "id_rsa", "id_ed25519", "credentials.json", "secrets.json", "pgsodium_root.key",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}
DATA_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safe Dev HQ project backup")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--project", required=True)
    create.add_argument("--project-id", required=True)
    create.add_argument("--mode", default="checkpoint", choices=["checkpoint", "manual"])
    create.add_argument("--max-file-size-mb", type=int, default=50)
    create.add_argument("--retention", type=int, default=DEFAULT_RETENTION)
    create.add_argument("--dry-run", action="store_true")

    listing = sub.add_parser("list")
    listing.add_argument("--project-id", required=True)
    listing.add_argument("--limit", type=int, default=10)

    verify = sub.add_parser("verify")
    verify.add_argument("--project-id", required=True)
    verify.add_argument("--archive", help="Specific backup ZIP; defaults to latest")

    return parser.parse_args()


def safe_project_id(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise ValueError("Unsafe project-id")
    return value


def ensure_inside_projects(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == PROJECTS_ROOT or PROJECTS_ROOT not in resolved.parents:
        raise ValueError(f"Project must be a child of {PROJECTS_ROOT}")
    if resolved == BACKUP_ROOT or BACKUP_ROOT in resolved.parents:
        raise ValueError("Backup source cannot be inside _hq_backups")
    if not resolved.is_dir():
        raise FileNotFoundError(f"Project does not exist: {resolved}")
    return resolved


def project_backup_dir(project_id: str) -> Path:
    project_id = safe_project_id(project_id)
    target = (BACKUP_ROOT / project_id).resolve()
    if BACKUP_ROOT not in target.parents:
        raise ValueError("Unsafe backup destination")
    return target


def is_sensitive_file(path: Path) -> bool:
    name = path.name.lower()
    if name == ".env.example" or name.endswith(".env.example"):
        return False
    if name in SENSITIVE_EXACT or name.startswith(".env.") or name == ".env":
        return True
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & SENSITIVE_DIR_NAMES)


def file_reason(path: Path, size: int, max_size: int) -> str | None:
    if path.is_symlink():
        return "symlink"
    if is_sensitive_file(path):
        return "sensitive"
    if path.suffix.lower() in DATA_SUFFIXES:
        return "local-data-db"
    if size > max_size:
        return "too-large"
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(project: Path, max_size: int) -> tuple[list[dict], Counter]:
    files: list[dict] = []
    excluded: Counter = Counter()
    for root_str, dirs, names in os.walk(project, topdown=True, followlinks=False):
        root = Path(root_str)
        kept_dirs = []
        for d in dirs:
            dp = root / d
            if d.lower() in EXCLUDED_DIRS or d.lower() in SENSITIVE_DIR_NAMES or dp.is_symlink():
                excluded["directory"] += 1
            else:
                kept_dirs.append(d)
        dirs[:] = kept_dirs

        for name in names:
            path = root / name
            try:
                resolved = path.resolve()
                if resolved != project and project not in resolved.parents:
                    excluded["outside-project"] += 1
                    continue
                stat = path.stat()
            except (OSError, RuntimeError):
                excluded["unreadable"] += 1
                continue
            reason = file_reason(path, stat.st_size, max_size)
            if reason:
                excluded[reason] += 1
                continue
            rel = path.relative_to(project).as_posix()
            files.append({"path": rel, "size": stat.st_size, "sha256": sha256_file(path), "source": path})

    files.sort(key=lambda x: x["path"].lower())
    return files, excluded


def fingerprint(files: list[dict]) -> str:
    h = hashlib.sha256()
    for item in files:
        h.update(item["path"].encode("utf-8"))
        h.update(b"\0")
        h.update(item["sha256"].encode("ascii"))
        h.update(b"\0")
        h.update(str(item["size"]).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def archives(project_id: str) -> list[Path]:
    d = project_backup_dir(project_id)
    if not d.exists():
        return []
    return sorted((p for p in d.glob("*.zip") if p.is_file()), key=lambda p: p.name, reverse=True)


def manifest_from_zip(path: Path) -> dict:
    with zipfile.ZipFile(path, "r") as zf:
        raw = zf.read("manifest.json")
        return json.loads(raw.decode("utf-8"))


def verify_archive(path: Path, expected_project_id: str | None = None) -> dict:
    path = path.resolve()
    if BACKUP_ROOT not in path.parents:
        raise ValueError("Archive must be inside _hq_backups")
    if not path.is_file():
        raise FileNotFoundError(path)

    with zipfile.ZipFile(path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise ValueError(f"ZIP CRC failure: {bad}")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if expected_project_id and manifest.get("project_id") != expected_project_id:
            raise ValueError("Project ID mismatch")
        for item in manifest.get("files", []):
            arcname = f"files/{item['path']}"
            data = zf.read(arcname)
            digest = hashlib.sha256(data).hexdigest()
            if digest != item["sha256"]:
                raise ValueError(f"Hash mismatch: {item['path']}")
            if len(data) != item["size"]:
                raise ValueError(f"Size mismatch: {item['path']}")
    return {
        "status": "VERIFIED",
        "archive": str(path),
        "project_id": manifest.get("project_id"),
        "created_at": manifest.get("created_at"),
        "file_count": len(manifest.get("files", [])),
        "content_fingerprint": manifest.get("content_fingerprint"),
    }


def create_backup(args: argparse.Namespace) -> int:
    project_id = safe_project_id(args.project_id)
    project = ensure_inside_projects(Path(args.project))
    max_size = max(1, args.max_file_size_mb) * 1024 * 1024
    selected, excluded = collect_files(project, max_size)
    content_fp = fingerprint(selected)
    total_bytes = sum(item["size"] for item in selected)

    existing = archives(project_id)
    if existing:
        try:
            latest_manifest = manifest_from_zip(existing[0])
            if latest_manifest.get("content_fingerprint") == content_fp:
                verified = verify_archive(existing[0], project_id)
                print(json.dumps({
                    "status": "SKIPPED_UNCHANGED",
                    "project_id": project_id,
                    "source": str(project),
                    "existing_backup": str(existing[0]),
                    "file_count": len(selected),
                    "total_bytes": total_bytes,
                    "content_fingerprint": content_fp,
                    "verified_existing": verified["status"],
                }, ensure_ascii=False, indent=2))
                return 0
        except Exception:
            pass

    summary = {
        "project_id": project_id,
        "source": str(project),
        "mode": args.mode,
        "file_count": len(selected),
        "total_bytes": total_bytes,
        "content_fingerprint": content_fp,
        "excluded": dict(excluded),
        "max_file_size_mb": args.max_file_size_mb,
    }
    if args.dry_run:
        print(json.dumps({"status": "DRY_RUN_OK", **summary}, ensure_ascii=False, indent=2))
        return 0

    target_dir = project_backup_dir(project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    filename = f"{now.strftime('%Y%m%d-%H%M%S')}-{project_id}.zip"
    final_path = target_dir / filename
    temp_path = target_dir / f".{filename}.tmp"

    manifest = {
        "schema_version": 1,
        "project_id": project_id,
        "source_path": str(project),
        "created_at": now.isoformat(timespec="seconds"),
        "mode": args.mode,
        "max_file_size_mb": args.max_file_size_mb,
        "file_count": len(selected),
        "total_bytes": total_bytes,
        "content_fingerprint": content_fp,
        "excluded": dict(excluded),
        "files": [{k: item[k] for k in ("path", "size", "sha256")} for item in selected],
    }

    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for item in selected:
                zf.write(item["source"], f"files/{item['path']}")
        temp_path.replace(final_path)
        verified = verify_archive(final_path, project_id)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    count_after = len(archives(project_id))
    result = {
        "status": "CREATED_VERIFIED",
        "archive": str(final_path),
        **summary,
        "verification": verified["status"],
        "backup_count": count_after,
        "retention_warning": count_after > max(1, args.retention),
        "retention_limit": max(1, args.retention),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def list_backups(args: argparse.Namespace) -> int:
    project_id = safe_project_id(args.project_id)
    rows = []
    for path in archives(project_id)[: max(1, args.limit)]:
        info = {"archive": str(path), "size": path.stat().st_size}
        try:
            manifest = manifest_from_zip(path)
            info.update({
                "created_at": manifest.get("created_at"),
                "file_count": manifest.get("file_count"),
                "content_fingerprint": manifest.get("content_fingerprint"),
            })
        except Exception as exc:
            info["manifest_error"] = str(exc)
        rows.append(info)
    print(json.dumps({"status": "OK", "project_id": project_id, "count": len(archives(project_id)), "backups": rows}, ensure_ascii=False, indent=2))
    return 0


def verify_backup(args: argparse.Namespace) -> int:
    project_id = safe_project_id(args.project_id)
    if args.archive:
        path = Path(args.archive)
    else:
        items = archives(project_id)
        if not items:
            raise FileNotFoundError(f"No backups for {project_id}")
        path = items[0]
    print(json.dumps(verify_archive(path, project_id), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    try:
        if args.command == "create":
            return create_backup(args)
        if args.command == "list":
            return list_backups(args)
        if args.command == "verify":
            return verify_backup(args)
        raise ValueError("Unknown command")
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

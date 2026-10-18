from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HQ_ROOT = Path(__file__).resolve().parents[1]
LEDGER = HQ_ROOT / "runtime" / "resource-usage.jsonl"
TIERS = {"LOW", "NORMAL", "HIGH", "EXTREME"}
KINDS = {"model", "tool", "research", "other"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Track known Dev HQ resource-usage events.")
    sub = p.add_subparsers(dest="cmd", required=True)

    log = sub.add_parser("log")
    log.add_argument("--project", required=True)
    log.add_argument("--kind", choices=sorted(KINDS), required=True)
    log.add_argument("--resource", required=True)
    log.add_argument("--tier", choices=sorted(TIERS), required=True)
    log.add_argument("--units", type=float)
    log.add_argument("--unit", default="")
    log.add_argument("--note", default="")

    report = sub.add_parser("report")
    report.add_argument("--days", type=int, default=7)
    report.add_argument("--json", action="store_true")
    return p.parse_args()


def safe_text(value: str, max_len: int = 160) -> str:
    text = " ".join(value.strip().split())
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    forbidden = ["sk-", "token=", "api_key=", "authorization:", "bearer "]
    lower = text.lower()
    if any(x in lower for x in forbidden):
        return "[redacted-sensitive-note]"
    return text


def load_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    events = []
    for line in LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except json.JSONDecodeError:
            continue
    return events


def cmd_log(args: argparse.Namespace) -> int:
    if args.units is not None and not args.unit.strip():
        print(json.dumps({"status": "ERROR", "error": "--unit is required when --units is provided"}, ensure_ascii=False))
        return 2

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project": safe_text(args.project, 80),
        "kind": args.kind,
        "resource": safe_text(args.resource, 100),
        "tier": args.tier,
        "units": args.units,
        "unit": safe_text(args.unit, 30) if args.units is not None else "",
        "note": safe_text(args.note),
    }
    with LEDGER.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(json.dumps({"status": "LOGGED", "event": event}, ensure_ascii=False, indent=2))
    return 0


def parse_ts(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def cmd_report(args: argparse.Namespace) -> int:
    if args.days < 1 or args.days > 3650:
        print(json.dumps({"status": "ERROR", "error": "--days must be between 1 and 3650"}, ensure_ascii=False))
        return 2

    now = datetime.now().astimezone()
    cutoff = now - timedelta(days=args.days)
    selected = []
    for e in load_events():
        ts = parse_ts(str(e.get("timestamp", "")))
        if ts and ts >= cutoff:
            selected.append(e)

    by_tier = Counter(str(e.get("tier", "UNKNOWN")) for e in selected)
    by_resource = Counter(str(e.get("resource", "UNKNOWN")) for e in selected)
    known_units: dict[str, float] = defaultdict(float)
    for e in selected:
        if isinstance(e.get("units"), (int, float)) and e.get("unit"):
            known_units[str(e["unit"])] += float(e["units"])

    result = {
        "status": "OK",
        "period_days": args.days,
        "event_count": len(selected),
        "by_tier": dict(by_tier),
        "by_resource": dict(by_resource.most_common()),
        "known_units": dict(known_units),
        "platform_usage": "UNKNOWN — local ledger is not billing/allowance data",
        "ledger_path": str(LEDGER),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"Resource report: last {args.days} day(s)")
    print(f"Logged events: {len(selected)}")
    if by_tier:
        print("By tier: " + ", ".join(f"{k}={v}" for k, v in by_tier.items()))
    else:
        print("By tier: no logged events")
    if by_resource:
        print("By resource: " + ", ".join(f"{k}={v}" for k, v in by_resource.most_common()))
    if known_units:
        print("Known measured units: " + ", ".join(f"{k}={v:g}" for k, v in known_units.items()))
    else:
        print("Known measured units: none")
    print("Platform usage: UNKNOWN — local ledger is not billing/allowance data")
    return 0


def main() -> int:
    args = parse_args()
    return cmd_log(args) if args.cmd == "log" else cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import operation_control as operations

HQ_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = Path(os.environ.get("DEV_HQ_PROJECTS_ROOT", str(Path.home() / "Projects"))).expanduser().resolve()
RUN_ROOT = HQ_ROOT / "runtime" / "task-runs"
WATCHDOG_TASK_FILE = HQ_ROOT / "runtime" / "hq-task-marker.json"
STAGES = [
    "resolve", "context", "freshness", "routing", "checkpoint", "execute",
    "verify", "quality_gate", "state_handoff", "adr", "backup", "memory", "report",
]
REQUIRED = [
    "resolve", "context", "freshness", "routing", "checkpoint", "execute",
    "verify", "quality_gate", "state_handoff", "adr", "backup", "memory",
]
VALID_STATUS = {"PENDING", "PASS", "WARN", "SKIP", "FAIL"}
NON_SKIPPABLE = {"resolve", "context", "freshness", "routing", "execute", "verify", "report"}
CHANGE_KINDS = {"code", "config", "docs", "read-only"}


def stage_error(record: dict, stage: str, value: dict) -> str | None:
    status = value.get("status", "PENDING")
    if status not in VALID_STATUS:
        return f"{stage}: invalid status {status!r}"
    note = str(value.get("note") or "").strip()
    evidence = value.get("evidence") or {}
    if not isinstance(evidence, dict):
        return f"{stage}: evidence must be an object"
    if status == "SKIP":
        if stage in NON_SKIPPABLE:
            return f"{stage}: mandatory stage cannot be skipped"
        if not note:
            return f"{stage}: SKIP requires --note"
        # Old records have no change_kind; treat them conservatively as code.
        if stage == "quality_gate" and record.get("change_kind", "code") not in {"docs", "read-only"}:
            return "quality_gate: SKIP is allowed only for docs/read-only tasks with a reason"
    if status in {"PASS", "WARN"} and stage == "verify":
        if not note or not str(evidence.get("reference") or "").strip():
            return "verify: outcome requires --note and --evidence-ref"
    if status in {"PASS", "WARN", "FAIL"} and stage == "quality_gate":
        expected_code = {"PASS": 0, "WARN": 1, "FAIL": 2}[status]
        if (evidence.get("quality_gate") != status or evidence.get("exit_code") != expected_code
                or not isinstance(evidence.get("checks"), list) or not evidence["checks"]):
            return "quality_gate: use the gate command; runner result and checks are required"
    return None


def reopen(record: dict) -> None:
    """Any new technical work invalidates a previously prepared report."""
    record["status"] = "IN_PROGRESS"
    record["completed_at"] = None
    record["technical_completed_at"] = None
    record["reporting"] = {"preparation": "PENDING", "delivery": "UNCONFIRMED"}
    record["stages"]["report"] = {"status": "PENDING", "at": None, "note": "", "evidence": {}}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def watchdog_signal(state: str, task: str = "", checkpoint: str | None = None, *,
                    run_id: str | None = None, project_id: str | None = None) -> None:
    current = {}
    try:
        current = json.loads(WATCHDOG_TASK_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    ts = now()
    same_run = bool(run_id and project_id and current.get("run_id") == run_id and current.get("project_id") == project_id)
    if state == "IDLE":
        payload = {"state": "IDLE", "current_task": "", "last_activity_at": ts, "last_activity_source": "task-lifecycle", "last_checkpoint": checkpoint, "updated_at": ts}
    else:
        payload = dict(current) if same_run else {}
        if state == "WORKING" and (not same_run or current.get("state") != "WORKING"):
            payload["task_started_at"] = ts
        payload.update({"state": state, "current_task": task or current.get("current_task", ""), "last_activity_at": ts, "last_activity_source": "task-lifecycle", "updated_at": ts})
        if checkpoint:
            payload["last_checkpoint"] = checkpoint
    payload.update({"run_id": run_id, "project_id": project_id})
    if same_run and current.get("window_binding"):
        payload["window_binding"] = current["window_binding"]
    WATCHDOG_TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WATCHDOG_TASK_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(WATCHDOG_TASK_FILE)


def slug(value: str, limit: int = 48) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return (value or "task")[:limit]


def safe_project_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise ValueError("Unsafe project-id")
    return value


def resolve_project(path: str) -> Path:
    project = Path(path).resolve()
    if not project.is_dir():
        raise FileNotFoundError(project)
    if project == PROJECTS_ROOT or PROJECTS_ROOT not in project.parents:
        raise ValueError(f"Project must be inside {PROJECTS_ROOT}")
    return project


def run_cmd(args: list[str], cwd: Path | None = None, timeout: int = 1200) -> tuple[int, str]:
    cp = subprocess.run(
        args, cwd=str(cwd or HQ_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    return cp.returncode, ((cp.stdout or "") + (cp.stderr or "")).strip()


def git_snapshot(project: Path) -> dict:
    code, inside = run_cmd(["git", "rev-parse", "--is-inside-work-tree"], project, 30)
    if code != 0 or inside.strip() != "true":
        return {"is_git": False}
    _, branch = run_cmd(["git", "branch", "--show-current"], project, 30)
    _, status = run_cmd(["git", "status", "--porcelain=v1"], project, 30)
    rows = [line for line in status.splitlines() if line.strip()]
    return {"is_git": True, "branch": branch.strip(), "dirty_paths": len(rows)}


def save(record: dict, path: Path, *, touch_progress: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record["updated_at"] = now()
    if touch_progress:
        record["last_progress_at"] = record["updated_at"]
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def find_run(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_file():
        return candidate.resolve()
    matches = list(RUN_ROOT.glob(f"*/*{value}*.json"))
    if len(matches) == 1:
        return matches[0].resolve()
    if not matches:
        raise FileNotFoundError(f"Run not found: {value}")
    raise ValueError(f"Run id is ambiguous: {value}")


def load_run(value: str) -> tuple[dict, Path]:
    path = find_run(value)
    return json.loads(path.read_text(encoding="utf-8")), path


def set_stage(record: dict, stage: str, status: str, note: str = "", evidence: dict | None = None) -> None:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    status = status.upper()
    if status not in VALID_STATUS - {"PENDING"}:
        raise ValueError(f"Invalid stage status: {status}")
    value = {
        "status": status,
        "at": now(),
        "note": note.strip(),
        "evidence": evidence or {},
    }
    error = stage_error(record, stage, value)
    if error:
        raise ValueError(error)
    record["stages"][stage] = value


def cmd_start(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    project_id = safe_project_id(args.project_id)
    ts = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    run_id = f"{ts}-{project_id}-{slug(args.task)}"
    path = RUN_ROOT / project_id / f"{run_id}.json"
    stages = {name: {"status": "PENDING", "at": None, "note": "", "evidence": {}} for name in STAGES}
    record = {
        "schema_version": 2,
        "run_id": run_id,
        "status": "IN_PROGRESS",
        "created_at": now(),
        "updated_at": now(),
        "completed_at": None,
        "technical_completed_at": None,
        "change_kind": args.change_kind,
        "reporting": {"preparation": "PENDING", "delivery": "UNCONFIRMED"},
        "operation_schema_version": 1,
        "operations": {},
        "project_id": project_id,
        "project_path": str(project),
        "task": args.task.strip(),
        "acceptance": [x.strip() for x in args.acceptance if x.strip()],
        "routing": {
            "complexity": args.complexity,
            "model": args.model,
            "effort": args.effort,
            "risk": args.risk,
        },
        "git_start": git_snapshot(project),
        "stages": stages,
    }
    set_stage(record, "resolve", "PASS", "Project path validated inside Projects", {"project_id": project_id})
    save(record, path)
    watchdog_signal("WORKING", record["task"], "resolve:PASS", run_id=record["run_id"], project_id=record["project_id"])
    print(json.dumps({"status": "CREATED", "run_id": run_id, "run_path": str(path)}, ensure_ascii=False, indent=2))
    return 0


def cmd_mark(args: argparse.Namespace) -> int:
    record, path = load_run(args.run)
    if args.stage == "report":
        raise ValueError("Use prepare-report with a real report file; mark cannot confirm delivery")
    reference = str(args.evidence_ref or "").strip()
    set_stage(record, args.stage, args.status, args.note, {"reference": reference} if reference else {})
    if args.stage == "execute":
        for stage in ("verify", "quality_gate"):
            record["stages"][stage] = {"status": "PENDING", "at": None, "note": "", "evidence": {}}
    reopen(record)
    save(record, path)
    watchdog_signal("WORKING", record["task"], f"{args.stage}:{args.status.upper()}", run_id=record["run_id"], project_id=record["project_id"])
    print(json.dumps({"status": "UPDATED", "run_id": record["run_id"], "stage": args.stage, "stage_status": args.status.upper()}, ensure_ascii=False))
    return 0


def parse_json_output(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Expected JSON output")
    return json.loads(text[start:end + 1])


def cmd_gate(args: argparse.Namespace) -> int:
    record, path = load_run(args.run)
    project = resolve_project(record["project_path"])
    gate = HQ_ROOT / "scripts" / "quality_gate.py"
    cmd = [sys.executable, str(gate), "--project", str(project), "--criteria-ok", args.criteria_ok, "--json"]
    code, output = run_cmd(cmd, HQ_ROOT, 1800)
    payload = parse_json_output(output)
    qg = payload.get("quality_gate", "FAIL")
    stage_status = "PASS" if qg == "PASS" else "WARN" if qg == "WARN" else "FAIL"
    set_stage(record, "quality_gate", stage_status, f"Quality Gate: {qg}", {"exit_code": code, "quality_gate": qg, "checks": payload.get("checks", [])})
    reopen(record)
    save(record, path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if qg == "PASS" else 1 if qg == "WARN" else 2


def cmd_backup(args: argparse.Namespace) -> int:
    record, path = load_run(args.run)
    project = resolve_project(record["project_path"])
    backup = HQ_ROOT / "scripts" / "backup_project.py"
    cmd = [sys.executable, str(backup), "create", "--project", str(project), "--project-id", record["project_id"], "--mode", args.mode]
    code, output = run_cmd(cmd, HQ_ROOT, 1800)
    payload = parse_json_output(output)
    bstatus = payload.get("status", "ERROR")
    ok = code == 0 and bstatus in {"CREATED_VERIFIED", "SKIPPED_UNCHANGED"}
    set_stage(record, "backup", "PASS" if ok else "FAIL", bstatus, payload)
    reopen(record)
    save(record, path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 2


def summary(record: dict) -> dict:
    stages = record.get("stages", {})
    pending = [s for s in REQUIRED if stages.get(s, {}).get("status", "PENDING") == "PENDING"]
    failed = [s for s in REQUIRED if stages.get(s, {}).get("status") == "FAIL"]
    warnings = [s for s in REQUIRED if stages.get(s, {}).get("status") == "WARN"]
    invalid = [error for s in REQUIRED if (error := stage_error(record, s, stages.get(s, {})))]
    operation_guard = operations.guard(record)
    return {"pending": pending, "failed": failed, "warnings": warnings, "invalid": invalid,
            "operations_blocked": operation_guard["blocked"], "operations_invalid": operation_guard["invalid"]}


def cmd_status(args: argparse.Namespace) -> int:
    record, _ = load_run(args.run)
    info = summary(record)
    print(json.dumps({
        "run_id": record["run_id"], "status": record["status"], "task": record["task"],
        "reporting": record.get("reporting", {"preparation": "LEGACY_UNVERIFIED", "delivery": "UNCONFIRMED"}),
        **info, "stages": {k: v["status"] for k, v in record["stages"].items()},
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    record, path = load_run(args.run)
    info = summary(record)
    if info["pending"] or info["failed"] or info["invalid"] or info["operations_blocked"] or info["operations_invalid"]:
        print(json.dumps({"status": "BLOCKED", "run_id": record["run_id"], **info}, ensure_ascii=False, indent=2))
        return 2
    if record.get("status") == "READY_TO_REPORT":
        prepared = record.get("reporting", {}).get("artifact", {})
        try:
            artifact = Path(prepared["path"]).resolve()
            if (PROJECTS_ROOT in artifact.parents and artifact.suffix.lower() in {".md", ".txt"}
                    and artifact.is_file() and artifact.stat().st_size <= 1_000_000
                    and hashlib.sha256(artifact.read_bytes()).hexdigest() == prepared.get("sha256")):
                print(json.dumps({"status": "READY_TO_REPORT", "run_id": record["run_id"],
                                  "reporting": record["reporting"], **info}, ensure_ascii=False, indent=2))
                return 0
        except (KeyError, OSError, ValueError):
            pass
    # Technical completion is not evidence of a message delivered to the user.
    record["status"] = "TECHNICAL_COMPLETE"
    record["technical_completed_at"] = record.get("technical_completed_at") or now()
    record["completed_at"] = None
    reporting = record.setdefault("reporting", {"preparation": "PENDING", "delivery": "UNCONFIRMED"})
    if reporting.get("preparation") == "PREPARED":
        # A deleted/changed report must be prepared again; a retry cannot certify it.
        record["stages"]["report"] = {"status": "PENDING", "at": None, "note": "", "evidence": {}}
    record["reporting"] = {"preparation": "PENDING", "delivery": "UNCONFIRMED"}
    record["git_finish"] = git_snapshot(resolve_project(record["project_path"]))
    save(record, path)
    watchdog_signal("WORKING", record["task"], "technical:COMPLETE;report:PENDING", run_id=record["run_id"], project_id=record["project_id"])
    print(json.dumps({"status": record["status"], "run_id": record["run_id"], **info}, ensure_ascii=False, indent=2))
    return 0


def cmd_prepare_report(args: argparse.Namespace) -> int:
    record, path = load_run(args.run)
    info = summary(record)
    if (info["pending"] or info["failed"] or info["invalid"] or info["operations_blocked"] or info["operations_invalid"]
            or record.get("status") not in {"TECHNICAL_COMPLETE", "READY_TO_REPORT"}):
        print(json.dumps({"status": "BLOCKED", "run_id": record["run_id"], **info}, ensure_ascii=False, indent=2))
        return 2
    artifact = Path(args.file).resolve()
    if PROJECTS_ROOT not in artifact.parents or artifact.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("Report must be a .md/.txt file inside Projects")
    if artifact.is_relative_to(HQ_ROOT / "runtime" / "task-runs"):
        raise ValueError("A lifecycle run record is not a user report")
    if not artifact.is_file() or not 0 < artifact.stat().st_size <= 1_000_000:
        raise ValueError("Report file must exist and contain 1..1000000 bytes")
    data = artifact.read_bytes()
    if not data.decode("utf-8-sig").strip():
        raise ValueError("Report file is empty")
    evidence = {"kind": "prepared_artifact", "path": str(artifact),
                "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    set_stage(record, "report", "PASS", "Report artifact prepared; user delivery is unconfirmed", evidence)
    record["reporting"] = {"preparation": "PREPARED", "prepared_at": now(),
                           "delivery": "UNCONFIRMED", "artifact": evidence}
    record["status"] = "READY_TO_REPORT"
    record["completed_at"] = None
    save(record, path)
    watchdog_signal("IDLE", record["task"], "report:READY;delivery:UNCONFIRMED", run_id=record["run_id"], project_id=record["project_id"])
    print(json.dumps({"status": record["status"], "run_id": record["run_id"],
                      "reporting": record["reporting"], **info}, ensure_ascii=False, indent=2))
    return 0


def cmd_begin_operation(args: argparse.Namespace) -> int:
    record, path = load_run(args.run)
    was_complete = record.get("status") in {"TECHNICAL_COMPLETE", "READY_TO_REPORT", "DONE", "DONE_WITH_WARNINGS"}
    operation = operations.begin(record, kind=args.kind, tool=args.tool, label=args.label,
                                 expected_seconds=args.expected_seconds, check_every=args.check_every,
                                 reference=args.reference, side_effect=args.side_effect,
                                 action_key=args.action_key, pid=args.pid)
    reopen(record)
    if was_complete:
        for stage in ("verify", "quality_gate"):
            record["stages"][stage] = {"status": "PENDING", "at": None, "note": "", "evidence": {}}
    save(record, path)
    watchdog_signal("WORKING", record["task"], f"operation:{operation['id']}:STARTED",
                    run_id=record["run_id"], project_id=record["project_id"])
    print(json.dumps({"status": "OPERATION_REGISTERED", "run_id": record["run_id"], "operation": operation}, ensure_ascii=False, indent=2))
    return 0


def cmd_operation_event(args: argparse.Namespace) -> int:
    record, path = load_run(args.run)
    operation = operations.event(record, args.operation, args.event, evidence_ref=args.evidence_ref,
                                 note=args.note, expected_seconds=args.expected_seconds,
                                 resolution=args.resolution, pid=args.pid)
    real_progress = args.event not in {"observed", "extend"}
    reopen(record)
    save(record, path, touch_progress=real_progress)
    if real_progress:
        state = "ERROR" if operation["state"] == "FAILED" else "WAITING" if operation["state"] == "WAITING_INPUT" else "WORKING"
        watchdog_signal(state, record["task"], f"operation:{operation['id']}:{operation['state']}",
                        run_id=record["run_id"], project_id=record["project_id"])
    print(json.dumps({"status": "OPERATION_UPDATED", "run_id": record["run_id"], "operation": operation}, ensure_ascii=False, indent=2))
    return 0



def cmd_observe_n8n(args: argparse.Namespace) -> int:
    record, path = load_run(args.run)
    if RUN_ROOT.resolve() not in path.resolve().parents:
        raise ValueError("Run must be a canonical local HQ task record")
    if operations.guard(record)["invalid"]:
        raise ValueError("Invalid registry requires recovery")
    operation = record.get("operations", {}).get(args.operation)
    if not operation or operation["state"] != "RUNNING":
        raise ValueError("Bind only a running operation; recover terminal outcomes first")
    if type(args.max_age) is not int or not 10 <= args.max_age <= 600:
        raise ValueError("Observation max age must be 10..600 seconds")
    source = operations.adapters.safe_path(args.response_file)
    with source.open('rb') as stream:
        response = stream.read(operations.adapters.MAX_BYTES + 1)
    if len(response) > operations.adapters.MAX_BYTES:
        raise ValueError("Metadata response too large")
    payload = json.loads(response.decode("utf-8-sig"))
    execution = payload.get("execution") if isinstance(payload, dict) else None
    if not isinstance(execution, dict) or execution.get("id") != args.execution_id or execution.get("workflowId") != args.workflow_id:
        raise ValueError("Exact workflow/execution identity must match tool response")
    if execution.get("status") not in operations.adapters.N8N_STATES:
        raise ValueError("Unsupported execution status")
    snapshot_path = operations.adapters.receipt_path(HQ_ROOT, record["run_id"], operation["id"])
    binding = {"kind": "n8n", "path": str(snapshot_path), "workflow_id": args.workflow_id,
               "execution_id": args.execution_id, "max_age_seconds": args.max_age, "allow_historical": args.historical}
    if operation.get("observer") not in (None, binding):
        raise ValueError("Observer identity/policy cannot change during an operation")
    if not operations.adapters.validate(binding):
        raise ValueError("Invalid observer policy")
    reference = operations.text(args.evidence_ref, "evidence-ref")
    operation["observer"] = binding
    # Metadata-only projection; never persist node data, error bodies or tokens.
    observation = {"schema_version": 1, "kind": "n8n", "run_id": record["run_id"],
                   "operation_id": operation["id"], "observed_at": operations.iso(__import__("time").time()),
                   "evidence_ref": reference,
                   "execution": {k: execution.get(k) for k in ("id", "workflowId", "status", "startedAt", "stoppedAt", "waitTill")}}
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    save(record, path, touch_progress=False)
    snapshot_path.write_text(json.dumps(observation, indent=2), encoding="utf-8")
    print(json.dumps({"status": "OBSERVATION_RECORDED", "path": str(snapshot_path),
                      "observation": operations.adapters.inspect(record, operation, at=__import__("time").time())}, indent=2))
    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dev HQ full task lifecycle run record")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("start")
    s.add_argument("--project", required=True)
    s.add_argument("--project-id", required=True)
    s.add_argument("--task", required=True)
    s.add_argument("--complexity", choices=["simple", "normal", "complex", "extreme"], default="normal")
    s.add_argument("--model", required=True)
    s.add_argument("--effort", choices=["Low", "Medium", "High", "Extra High"], required=True)
    s.add_argument("--risk", choices=["LOW", "NORMAL", "HIGH", "EXTREME"], default="NORMAL")
    s.add_argument("--acceptance", action="append", default=[])
    s.add_argument("--change-kind", choices=sorted(CHANGE_KINDS), default="code")

    m = sub.add_parser("mark")
    m.add_argument("--run", required=True)
    m.add_argument("--stage", choices=STAGES, required=True)
    m.add_argument("--status", choices=["PASS", "WARN", "SKIP", "FAIL"], required=True)
    m.add_argument("--note", default="")
    m.add_argument("--evidence-ref", default="")

    g = sub.add_parser("gate")
    g.add_argument("--run", required=True)
    g.add_argument("--criteria-ok", choices=["yes", "no", "unknown"], default="unknown")

    b = sub.add_parser("backup")
    b.add_argument("--run", required=True)
    b.add_argument("--mode", choices=["checkpoint", "manual"], default="checkpoint")

    st = sub.add_parser("status")
    st.add_argument("--run", required=True)

    f = sub.add_parser("finish")
    f.add_argument("--run", required=True)
    report = sub.add_parser("prepare-report")
    report.add_argument("--run", required=True)
    report.add_argument("--file", required=True, help="Existing UTF-8 .md/.txt report inside Projects")
    operation = sub.add_parser("begin-operation")
    operation.add_argument("--run", required=True)
    operation.add_argument("--kind", choices=sorted(operations.KINDS), required=True)
    operation.add_argument("--tool", required=True)
    operation.add_argument("--label", required=True)
    operation.add_argument("--expected-seconds", type=int, required=True)
    operation.add_argument("--check-every", type=int, default=10)
    operation.add_argument("--reference", default="")
    operation.add_argument("--side-effect", action="store_true")
    operation.add_argument("--action-key", default="")
    operation.add_argument("--pid", type=int)
    event = sub.add_parser("operation-event")
    event.add_argument("--run", required=True)
    event.add_argument("--operation", required=True)
    event.add_argument("--event", choices=sorted(operations.EVENTS), required=True)
    event.add_argument("--evidence-ref", required=True)
    event.add_argument("--note", required=True)
    event.add_argument("--expected-seconds", type=int)
    event.add_argument("--resolution", choices=["SUCCEEDED", "FAILED", "NOT_EXECUTED"])
    event.add_argument("--pid", type=int)
    observed = sub.add_parser("observe-n8n")
    observed.add_argument("--run", required=True)
    observed.add_argument("--operation", required=True)
    observed.add_argument("--workflow-id", required=True)
    observed.add_argument("--execution-id", required=True)
    observed.add_argument("--response-file", required=True)
    observed.add_argument("--evidence-ref", required=True)
    observed.add_argument("--max-age", type=int, default=120)
    observed.add_argument("--historical", action="store_true")
    return p


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args()
    handlers = {
        "start": cmd_start, "mark": cmd_mark, "gate": cmd_gate,
        "backup": cmd_backup, "status": cmd_status, "finish": cmd_finish,
        "prepare-report": cmd_prepare_report,
        "begin-operation": cmd_begin_operation, "operation-event": cmd_operation_event,
        "observe-n8n": cmd_observe_n8n,
    }
    try:
        return handlers[args.command](args)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

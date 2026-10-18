"""Cooperative operation metadata and read-only, independent observation.

This module never runs/retries commands or treats a live PID as task success.
"""
from __future__ import annotations

import os
import time
import uuid
import operation_adapters as adapters
from datetime import datetime, timezone
from pathlib import Path

KINDS = {"reasoning", "plugin", "browser", "terminal", "test", "build", "storage", "other"}
STATES = {"RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN", "RESOLVED"}
BLOCKING = {"RUNNING", "WAITING_INPUT", "FAILED", "OUTCOME_UNKNOWN"}
EVENTS = {"observed", "progress", "waiting-input", "succeeded", "failed", "outcome-unknown", "extend", "resolve"}


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def epoch(value) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def text(value: str, label: str, limit=240) -> str:
    value = str(value or "").strip()
    if not value or len(value) > limit or any(c in value for c in "\r\n\x00"):
        raise ValueError(f"{label} must be short, nonempty metadata on one line")
    return value


def probe_process(pid: int) -> dict:
    """Read-only liveness plus creation identity; no process termination."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return {"state": "UNKNOWN", "reason": "invalid-pid"}
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        handle = k.OpenProcess(0x1000, False, pid)
        if not handle:
            return {"state": "NOT_OBSERVED", "reason": "missing-or-access-unavailable"}
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            exit_code = wintypes.DWORD()
            if not k.GetProcessTimes(handle, *(ctypes.byref(v) for v in times)) or not k.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return {"state": "UNKNOWN", "reason": "process-query-unavailable"}
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return {"state": "ALIVE" if exit_code.value == 259 else "EXITED",
                    "identity": f"{pid}:{created}"}
        finally:
            k.CloseHandle(handle)
    try:
        stat = (Path("/proc") / str(pid) / "stat").read_text()
        fields = stat.rsplit(")", 1)[1].split()
        return {"state": "EXITED" if fields[0] == "Z" else "ALIVE", "identity": f"{pid}:{fields[19]}"}
    except (OSError, IndexError):
        return {"state": "NOT_OBSERVED", "reason": "missing-or-access-unavailable"}


def begin(record: dict, *, kind: str, tool: str, label: str, expected_seconds: int,
          check_every: int = 10, reference: str = "", side_effect: bool = False,
          action_key: str = "", pid: int | None = None, at: float | None = None) -> dict:
    if (kind not in KINDS or type(expected_seconds) is not int or type(check_every) is not int
            or not 1 <= expected_seconds <= 86400 or not 5 <= check_every <= 3600):
        raise ValueError("Invalid kind or operation timing policy")
    tool, label = text(tool, "tool", 80), text(label, "label", 160)
    reference = text(reference, "reference") if reference else ""
    action_key = text(action_key, "action-key", 120) if action_key else ""
    if side_effect and not action_key:
        raise ValueError("Side effects require an action-key for correlation")
    operations = record.get("operations", {})
    if not isinstance(operations, dict) or len(operations) >= 1000 or guard(record)["invalid"]:
        raise ValueError("Invalid/full operation registry; checkpoint and start a new bounded run")
    if sum(o.get("state") in {"RUNNING", "WAITING_INPUT"} for o in operations.values() if isinstance(o, dict)) >= 32:
        raise ValueError("At most 32 operations may be active in one bounded run")
    if side_effect and any(o.get("action_key") == action_key and o.get("state") in {"RUNNING", "WAITING_INPUT", "FAILED", "OUTCOME_UNKNOWN"}
                           for o in operations.values()):
        raise ValueError("Action outcome is unresolved; read-only recovery is required before another attempt")
    probe = None
    if pid is not None:
        observed = probe_process(pid)
        if observed.get("state") != "ALIVE" or not observed.get("identity"):
            raise ValueError("Cannot bind a process without observed creation identity")
        probe = {"kind": "process", "pid": pid, "identity": observed["identity"]}
    current = time.time() if at is None else at
    operation = {"id": uuid.uuid4().hex[:16], "kind": kind, "tool": tool, "label": label,
                 "state": "RUNNING", "started_at": iso(current), "last_progress_at": iso(current),
                 "deadline_at": iso(current + expected_seconds), "check_every_seconds": check_every,
                 "reference": reference, "side_effect": bool(side_effect), "action_key": action_key,
                 "probe": probe, "events": []}
    record.setdefault("operations", {})[operation["id"]] = operation
    record["operation_schema_version"] = 1
    return operation


def event(record: dict, operation_id: str, event_name: str, *, evidence_ref: str, note: str,
          expected_seconds: int | None = None, resolution: str | None = None,
          pid: int | None = None, at: float | None = None) -> dict:
    if guard(record)["invalid"]:
        raise ValueError("Invalid operation registry requires recovery")
    if event_name not in EVENTS:
        raise ValueError("Unknown operation event")
    operation = record.get("operations", {}).get(operation_id)
    if not operation:
        raise ValueError("Operation is not in this run")
    evidence_ref, note = text(evidence_ref, "evidence-ref"), text(note, "note")
    state = operation.get("state")
    current = time.time() if at is None else at
    if event_name == "resolve":
        if state not in {"FAILED", "OUTCOME_UNKNOWN"} or resolution not in {"SUCCEEDED", "FAILED", "NOT_EXECUTED"}:
            raise ValueError("Resolve needs a failed/unknown operation and an established recovery outcome")
    elif state not in {"RUNNING", "WAITING_INPUT"}:
        raise ValueError("Terminal operation requires read-only recovery, not a blind retry")
    if event_name == "extend" and (type(expected_seconds) is not int or not 1 <= expected_seconds <= 86400):
        raise ValueError("Extend requires a new expected duration from now and real observation evidence")
    if event_name == "extend" and state != "RUNNING":
        raise ValueError("Resume a waiting operation with progress evidence before extending")
    attached = None
    if pid is not None:
        observed = probe_process(pid)
        if observed.get("state") != "ALIVE" or not observed.get("identity"):
            raise ValueError("Cannot bind process identity")
        attached = {"kind": "process", "pid": pid, "identity": observed["identity"]}
    if attached:
        operation["probe"] = attached
    operation["last_observed_at"] = iso(current)
    operation["evidence_ref"] = evidence_ref
    if event_name == "progress":
        paused = epoch(operation.pop("paused_at", None))
        if paused is not None:
            operation["deadline_at"] = iso((epoch(operation["deadline_at"]) or current) + max(0, current - paused))
        operation["state"] = "RUNNING"
        operation["last_progress_at"] = iso(current)
    elif event_name == "waiting-input":
        operation["state"] = "WAITING_INPUT"
        operation.setdefault("paused_at", iso(current))
    elif event_name == "extend":
        operation["deadline_at"] = iso(current + expected_seconds)
    elif event_name == "resolve":
        operation.update({"state": "RESOLVED", "resolved_outcome": resolution, "resolved_at": iso(current)})
    elif event_name in {"succeeded", "failed", "outcome-unknown"}:
        operation["state"] = {"succeeded": "SUCCEEDED", "failed": "FAILED", "outcome-unknown": "OUTCOME_UNKNOWN"}[event_name]
        operation["finished_at"] = iso(current)
    operation["events"] = (operation.get("events", []) + [{"at": iso(current), "event": event_name,
                                                          "evidence_ref": evidence_ref, "note": note}])[-20:]
    return operation


def guard(record: dict) -> dict:
    operations = record.get("operations", {})
    if not isinstance(operations, dict):
        return {"blocked": [], "invalid": ["operations registry is not an object"]}
    blocked, invalid = [], []
    for key, operation in operations.items():
        if not isinstance(operation, dict) or operation.get("id") != key or operation.get("state") not in STATES:
            invalid.append(str(key))
            continue
        policy = operation.get("check_every_seconds")
        valid = (epoch(operation.get("started_at")) is not None
                 and epoch(operation.get("last_progress_at")) is not None
                 and epoch(operation.get("deadline_at")) is not None
                 and type(policy) is int and 5 <= policy <= 3600)
        if operation["state"] in {"SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN", "RESOLVED"}:
            valid = valid and bool(str(operation.get("evidence_ref") or "").strip())
        if operation["state"] == "WAITING_INPUT":
            valid = valid and epoch(operation.get("paused_at")) is not None
        if operation["state"] == "RESOLVED":
            valid = valid and operation.get("resolved_outcome") in {"SUCCEEDED", "FAILED", "NOT_EXECUTED"}
        source = operation.get("probe")
        if source is not None:
            valid = (valid and isinstance(source, dict) and source.get("kind") == "process"
                     and type(source.get("pid")) is int and source["pid"] > 0 and bool(source.get("identity")))
        if operation.get("observer") is not None:
            valid = valid and adapters.validate(operation["observer"])
        if not valid:
            invalid.append(str(key))
        if operation["state"] in BLOCKING:
            blocked.append(key)
    return {"blocked": blocked, "invalid": invalid}


def inspect(record: dict, *, at: float, cache: dict | None = None, probe_fn=None) -> dict:
    """Observer checks update only their own cache, never task progress or records."""
    if "operations" not in record:
        return {"state": "UNINSTRUMENTED", "coverage": "NOT_REGISTERED", "operations": []}
    validation = guard(record)
    if validation["invalid"]:
        return {"state": "OUTCOME_UNKNOWN", "coverage": "INVALID", "operations": []}
    cache = cache if cache is not None else {}
    probe_fn = probe_fn or probe_process
    rows = []
    priority = {"FAILED": 6, "OUTCOME_UNKNOWN": 5, "OVERDUE": 4, "RESULT_AVAILABLE": 3, "WAITING_RESULT": 2, "WAITING_INPUT": 1, "IDLE": 0}
    aggregate = "IDLE"
    for operation_id, operation in record.get("operations", {}).items():
        state = operation["state"]
        if state in {"SUCCEEDED", "RESOLVED"}:
            continue
        observed = None
        verdict = state
        if state == "RUNNING":
            verdict = "WAITING_RESULT"
            deadline = epoch(operation.get("deadline_at"))
            progress = epoch(operation.get("last_progress_at"))
            if deadline is None or progress is None or progress > at + 5:
                verdict = "OUTCOME_UNKNOWN"
            elif at >= deadline:
                verdict = "OVERDUE"
            source = operation.get("probe")
            if isinstance(source, dict) and source.get("kind") == "process":
                key = (record.get("run_id"), operation_id, source.get("pid"), source.get("identity"))
                saved = cache.get(key)
                interval = max(5, int(operation.get("check_every_seconds", 10)))
                if saved is None or at < saved["checked_at"] or at - saved["checked_at"] >= interval:
                    try:
                        observed = probe_fn(source.get("pid"))
                    except Exception:
                        observed = {"state": "UNKNOWN", "reason": "probe-unavailable"}
                    cache[key] = {"checked_at": at, "result": observed}
                else:
                    observed = saved["result"]
                if (observed.get("state") != "ALIVE" or observed.get("identity") != source.get("identity")):
                    verdict = "OUTCOME_UNKNOWN"
        result_observation = adapters.inspect(record, operation, at=at, process_observation=observed) if state == "RUNNING" else None
        if result_observation is not None:
            verdict = result_observation["state"]
            if verdict == "WAITING_RESULT" and at >= epoch(operation["deadline_at"]):
                verdict = "OVERDUE"
        if priority.get(verdict, 4) > priority[aggregate]:
            aggregate = verdict if verdict in priority else "OUTCOME_UNKNOWN"
        progress_at = epoch(operation.get("last_progress_at"))
        rows.append({"id": operation_id, "kind": operation.get("kind"), "tool": operation.get("tool"),
                     "label": operation.get("label"), "state": verdict, "recorded_state": state,
                     "deadline_at": operation.get("deadline_at"), "reference": operation.get("reference"),
                     "progress_age_seconds": max(0, int(at - progress_at)) if progress_at is not None else None,
                     "probe": observed, "result_observation": result_observation, "automatic_retry": False,
                     "recommendation": "READ_ONLY_RECOVERY" if verdict in {"FAILED", "OUTCOME_UNKNOWN", "OVERDUE"}
                     else "VERIFY_RESULT_AND_ACKNOWLEDGE" if verdict == "RESULT_AVAILABLE" else "WAIT_FOR_INPUT" if verdict == "WAITING_INPUT" else "WAIT_FOR_RESULT_OR_CHECK_REFERENCE"})
    return {"state": aggregate, "coverage": "REGISTERED_OPERATIONS_ONLY", "operations": rows}

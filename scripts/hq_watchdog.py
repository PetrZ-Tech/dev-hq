#!/usr/bin/env python3
"""Dev HQ lightweight watchdog.

Stdlib-only local monitor. It never retries ChatGPT actions, restarts tools,
or changes external systems. Background polling is intentionally cheap;
UI Automation is sampled only at a slow interval or on manual recheck.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import operation_control as operations

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
STATUS_FILE = RUNTIME / "hq-status.json"
TASK_FILE = RUNTIME / "hq-task-marker.json"
EVENTS_FILE = RUNTIME / "watchdog-events.jsonl"
def env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        return value if 1 <= value <= 65535 else default
    except ValueError:
        return default


def configured_tool_ports() -> dict[str, int]:
    """Optional health checks from DEV_HQ_TOOL_PORTS="Name:port,Other:port"."""
    result: dict[str, int] = {}
    for item in os.environ.get("DEV_HQ_TOOL_PORTS", "").split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        name, raw_port = item.rsplit(":", 1)
        try:
            port = int(raw_port)
        except ValueError:
            continue
        if name.strip() and 1 <= port <= 65535:
            result[name.strip()] = port
    return result


DEFAULT_PORT = env_int("DEV_HQ_WATCHDOG_PORT", 32110)
DESKTOP_CONTROL_PORT = env_int("DEV_HQ_DESKTOP_CONTROL_PORT", 32103)
WATCH_DESKTOP_COMMANDER = os.environ.get("DEV_HQ_WATCH_DESKTOP_COMMANDER", "false").lower() in {"1", "true", "yes", "on"}
POLL_SECONDS = 10
STALE_WARNING_SECONDS = 60
STALLED_SECONDS = 120
DEEP_UI_SECONDS = 60
EXPENSIVE_HEALTH_SECONDS = 60
MAX_EVENTS = 100
WATCHDOG_VERSION = "1.4.0-public"
TOOL_PORTS = configured_tool_ports()
ERROR_MARKERS = ("message delivery timed out", "please try again", "connection interrupted", "retry")
GENERATION_MARKERS = ("stop generating", "stop streaming", "остановить генерацию", "остановить ответ")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else (default or {})
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default or {}


def append_bounded_event(path: Path, event: dict[str, Any], max_events: int = MAX_EVENTS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    lines.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    lines = lines[-max_events:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def tcp_alive(port: int, timeout: float = 0.18) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def desktop_commander_alive() -> bool:
    if os.name != "nt":
        return False
    cmd = (
        "$p=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object {$_.CommandLine -and $_.CommandLine -match 'desktop-commander' -and $_.CommandLine -match '\\bremote\\b'} | "
        "Select-Object -First 1; if($p){exit 0}else{exit 1}"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def process_name(pid: int) -> str:
    if os.name != "nt":
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
        return ""
    finally:
        k32.CloseHandle(handle)


def visible_windows() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    rows: list[dict[str, Any]] = []
    fg = int(user32.GetForegroundWindow() or 0)
    CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rows.append({"handle": str(int(hwnd)), "title": buf.value, "pid": int(pid.value), "process": process_name(int(pid.value)), "foreground": int(hwnd) == fg})
        return True

    user32.EnumWindows(CALLBACK(cb), 0)
    return rows


def is_chat_window(window: dict[str, Any]) -> bool:
    process = str(window.get("process") or "").lower()
    title = str(window.get("title") or "").strip()
    if not title:
        return False
    if process in {"chatgpt.exe", "codex.exe"}:
        return True
    # A title containing 'OpenAI', 'GPT' or 'HQ' alone is not a chat page.
    return process == "chrome.exe" and bool(re.search(r"(?:^| - )ChatGPT - Google Chrome$", title))


def window_key(window: dict[str, Any] | None) -> tuple:
    if not window:
        return ()
    return (str(window.get("handle")), window.get("pid"), window.get("process"),
            window.get("title") if window.get("process") == "chrome.exe" else None)


def bind_window(window: dict[str, Any]) -> dict[str, Any]:
    return {key: window.get(key) for key in ("handle", "pid", "process", "title")}


def choose_chat_window(windows: list[dict[str, Any]], binding: dict[str, Any] | None = None) -> dict[str, Any] | None:
    candidates = [w for w in windows if is_chat_window(w)]
    if binding:
        # Never silently follow another window or a reused HWND/PID.
        return next((w for w in candidates if window_key(w) == window_key(binding)), None)
    # Foreground is not proof of which conversation belongs to this task.
    return candidates[0] if len(candidates) == 1 else None


def lifecycle_record(marker: dict[str, Any] | None = None) -> dict[str, Any]:
    marker = marker or {}
    project_id = str(marker.get("project_id") or "")
    run_id = str(marker.get("run_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", project_id):
        return {}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", run_id):
        return {}
    root = (RUNTIME / "task-runs").resolve()
    path = (root / project_id / f"{run_id}.json").resolve()
    if root not in path.parents:
        return {}
    record = read_json(path)
    if record.get("run_id") != run_id or record.get("project_id") != project_id:
        return {}
    return record


def latest_lifecycle_activity(marker: dict[str, Any] | None = None, record: dict | None = None) -> tuple[float | None, str | None]:
    record = lifecycle_record(marker) if record is None else record
    # Semantic timestamp only; touching another file must not be a heartbeat.
    return parse_time(record.get("last_progress_at", record.get("updated_at"))), record.get("run_id")


def recommend(state: str, offline_component: str | None = None) -> str:
    return {
        "WORKING": "No action required",
        "WAITING": "Waiting for user",
        "IDLE": "No active task",
        "STALLED": "Run read-only recovery audit before retry",
        "ERROR": "Recovery audit — do not blind Retry",
        "OFFLINE": f"Check {offline_component or 'critical component'}",
        "UNKNOWN": "Task state unknown - check task marker and observed window",
        "WAITING_RESULT": "Waiting for registered operation result; liveness is not progress",
        "CHECK_REQUIRED": "Operation exceeded expected duration - read-only recovery before retry",
    }[state]


def decide_state(marker: dict[str, Any], tools: dict[str, bool], chat_state: str, now_epoch: float, activity_epoch: float | None,
                 stalled_seconds: int = STALLED_SECONDS) -> tuple[str, int, str | None]:
    requested = str(marker.get("state") or "UNKNOWN").upper()
    active = requested in {"WORKING", "WAITING", "ERROR"}
    offline = next((name for name, ok in tools.items() if not ok), None)
    if chat_state == "error":
        return "ERROR", 0, None
    if offline:
        if active:
            return "ERROR", 0, offline
        return "OFFLINE", 0, offline
    if requested == "ERROR":
        return "ERROR", 0, None
    if requested == "WAITING":
        return "WAITING", 0, None
    if chat_state == "generating" and requested == "IDLE":
        return "WORKING", 0, None
    if requested == "WORKING":
        last = activity_epoch if activity_epoch is not None else parse_time(marker.get("task_started_at"))
        if last is None or last > now_epoch + 5:
            return "UNKNOWN", 0, None
        stall = max(0, int(now_epoch - last))
        if chat_state == "generating":
            return "WORKING", stall, None
        if stall >= stalled_seconds:
            return "STALLED", stall, None
        return "WORKING", stall, None
    if requested == "IDLE" and activity_epoch is not None and 0 <= now_epoch - activity_epoch <= STALE_WARNING_SECONDS:
        return "IDLE", 0, None
    return "UNKNOWN", 0, None


class SelfResources:
    def __init__(self) -> None:
        self.prev_wall = time.monotonic()
        self.prev_cpu = time.process_time()
        self.started_wall = self.prev_wall
        self.started_cpu = self.prev_cpu
        self.last_cpu = 0.0
        self.peak_ram = 0.0
        self.peak_cpu = 0.0

    @staticmethod
    def ram_mb() -> float:
        if os.name != "nt":
            return 0.0
        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        info = PMC(); info.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(info), info.cb):
            return info.WorkingSetSize / 1024 / 1024
        return 0.0

    def sample(self) -> dict[str, float]:
        wall = time.monotonic(); cpu = time.process_time()
        dw = max(1e-6, wall - self.prev_wall); dc = max(0.0, cpu - self.prev_cpu)
        raw_pct = (dc / dw) * 100.0 / max(1, os.cpu_count() or 1)
        meaningful = dw >= 1.0
        if meaningful:
            self.last_cpu = raw_pct
            self.peak_cpu = max(self.peak_cpu, raw_pct)
        self.prev_wall, self.prev_cpu = wall, cpu
        ram = self.ram_mb()
        self.peak_ram = max(self.peak_ram, ram)
        total_wall = max(1e-6, wall - self.started_wall)
        avg = ((cpu - self.started_cpu) / total_wall) * 100.0 / max(1, os.cpu_count() or 1)
        return {"ram_mb": round(ram, 1), "ram_peak_mb": round(self.peak_ram, 1), "cpu_percent": round(self.last_cpu, 3),
                "cpu_average_percent": round(avg, 3), "cpu_peak_percent": round(self.peak_cpu, 3)}


class Watchdog:
    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.resources = SelfResources()
        self.last_dc_check = 0.0
        self.dc_ok = True
        self.last_deep_check = 0.0
        self.chat_state = "unknown"
        self.chat_detail = "not checked"
        self.last_state: str | None = None
        self.last_window: dict[str, Any] | None = None
        self.window_binding: dict[str, Any] | None = None
        self.observed_run: tuple[str | None, str | None] | None = None
        self.checked_window: tuple = ()
        self.operation_cache: dict = {}
        self.status: dict[str, Any] = {}

    def tool_health(self, force_expensive: bool = False) -> dict[str, bool]:
        tools = {name: tcp_alive(port) for name, port in TOOL_PORTS.items()}
        now = time.monotonic()
        if WATCH_DESKTOP_COMMANDER:
            if force_expensive or now - self.last_dc_check >= EXPENSIVE_HEALTH_SECONDS:
                self.dc_ok = desktop_commander_alive()
                self.last_dc_check = now
            tools["Desktop Commander"] = self.dc_ok
        tools["HQ Watchdog"] = True
        return tools

    def mcp_tool(self, name: str, arguments: dict[str, Any], timeout: float = 4.0) -> dict[str, Any]:
        url = f"http://127.0.0.1:{DESKTOP_CONTROL_PORT}/mcp"
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "hq-watchdog", "version": "1.0"}}}
        req = urllib.request.Request(url, data=json.dumps(init).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            sid = resp.headers.get("mcp-session-id"); resp.read()
        if not sid:
            raise RuntimeError("MCP session id missing")
        headers["mcp-session-id"] = sid
        note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        with urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(note).encode(), headers=headers), timeout=timeout) as resp:
            resp.read()
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        with urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(call).encode(), headers=headers), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def deep_ui_check(self, target: dict[str, Any] | None) -> tuple[str, str]:
        if not tcp_alive(DESKTOP_CONTROL_PORT):
            return "unknown", "Desktop Control Adapter offline"
        if not target:
            return "unknown", "Chat window missing, changed or ambiguous"
        pattern = "(?i)^(" + "|".join(re.escape(x) for x in ERROR_MARKERS + GENERATION_MARKERS) + ")$"
        try:
            result = self.mcp_tool("ui_find", {"windowHandle": target["handle"], "namePattern": pattern, "foundIndex": 1,
                                                   "visibleOnly": True, "timeoutMs": 2500, "includeDiagnostics": False}, timeout=4.0)
            block = ((result.get("result") or {}).get("content") or [{}])[0].get("text", "")
            payload = json.loads(block) if block else {}
            if payload.get("success") and payload.get("elements"):
                name = str(payload["elements"][0].get("name") or "")
                low = name.lower().strip()
                if low in ERROR_MARKERS:
                    return "error", "visible error control"
                if low in GENERATION_MARKERS:
                    return "generating", "visible generation control"
            if payload.get("errorType") == "timeout":
                return "unknown", "bounded UI scan timed out without marker"
            return "unknown", "no conclusive error/generation control"
        except Exception as exc:
            return "unknown", f"UI check unavailable: {type(exc).__name__}"

    def refresh(self, manual: bool = False) -> dict[str, Any]:
        with self.lock:
            now_epoch = time.time(); tools = self.tool_health(force_expensive=manual)
            marker = read_json(TASK_FILE, {})
            run_identity = (marker.get("project_id"), marker.get("run_id"))
            if self.observed_run != run_identity:
                self.window_binding = None
                self.observed_run = run_identity
                self.checked_window = ()
                self.chat_state, self.chat_detail = "unknown", "task identity changed; fresh UI check required"
                self.operation_cache.clear()
            windows = visible_windows()
            explicit_binding = marker.get("window_binding")
            binding = explicit_binding if isinstance(explicit_binding, dict) and explicit_binding else self.window_binding
            target = choose_chat_window(windows, binding)
            window_source = "bound" if explicit_binding else "auto_unique_candidate"
            if target and not binding:
                self.window_binding = bind_window(target)
            if not target:
                window_source = "unavailable_or_ambiguous"
            self.last_window = target
            if window_key(target) != self.checked_window:
                self.chat_state, self.chat_detail = "unknown", "observed window changed; fresh UI check required"
            if manual or time.monotonic() - self.last_deep_check >= DEEP_UI_SECONDS:
                self.chat_state, self.chat_detail = self.deep_ui_check(target)
                self.last_deep_check = time.monotonic()
                self.checked_window = window_key(target)
            record = lifecycle_record(marker)
            lifecycle_ts, _ = latest_lifecycle_activity(marker, record)
            marker_ts = parse_time(marker.get("last_activity_at"))
            activity_ts = max([x for x in (marker_ts, lifecycle_ts) if x is not None and x <= now_epoch + 5], default=None)
            source = marker.get("last_activity_source")
            if lifecycle_ts and (marker_ts is None or lifecycle_ts > marker_ts):
                source = "task-lifecycle"
            state, stall, offline = decide_state(marker, tools, self.chat_state, now_epoch, activity_ts)
            operation_watch = operations.inspect(record, at=now_epoch, cache=self.operation_cache)
            if state not in {"ERROR", "OFFLINE"}:
                state = {"FAILED": "ERROR", "OUTCOME_UNKNOWN": "UNKNOWN", "OVERDUE": "CHECK_REQUIRED",
                         "WAITING_RESULT": "WAITING_RESULT", "WAITING_INPUT": "WAITING", "RESULT_AVAILABLE": "CHECK_REQUIRED"}.get(operation_watch["state"], state)
            started = parse_time(marker.get("task_started_at"))
            elapsed = max(0, int(now_epoch - started)) if started and state in {"WORKING", "WAITING", "STALLED", "ERROR", "WAITING_RESULT", "CHECK_REQUIRED", "UNKNOWN"} else 0
            # A window title is observation metadata, never the task's name.
            current_task = marker.get("current_task") or ""
            observation = {
                "state": "OBSERVED" if self.chat_state in {"generating", "error"} and target else "DEGRADED",
                "task_source": "task-marker" if marker.get("state") else "none",
                "window_source": window_source,
                "detail": self.chat_detail,
            }
            status = {
                "version": WATCHDOG_VERSION,
                "state": state,
                "run_id": marker.get("run_id"),
                "project_id": marker.get("project_id"),
                "observation": observation,
                "operation_watch": operation_watch,
                "notification": operations.adapters.notification(operation_watch),
                "current_task": current_task,
                "task_started_at": marker.get("task_started_at"),
                "elapsed_seconds": elapsed,
                "last_activity_at": datetime.fromtimestamp(activity_ts, timezone.utc).astimezone().isoformat(timespec="seconds") if activity_ts else None,
                "last_activity_source": source,
                "last_tool": marker.get("last_tool"),
                "last_checkpoint": marker.get("last_checkpoint"),
                "stall_seconds": stall,
                "stale_warning_seconds": STALE_WARNING_SECONDS,
                "stalled_seconds": STALLED_SECONDS,
                "poll_interval_seconds": POLL_SECONDS,
                "chatgpt_state": self.chat_state,
                "chatgpt_detail": self.chat_detail,
                "chatgpt_window": target,
                "tools": {name: ("OK" if ok else "OFFLINE") for name, ok in tools.items()},
                "watchdog_resources": self.resources.sample(),
                "recommendation": ("Result available - verify evidence and acknowledge operation"
                                   if state == "CHECK_REQUIRED" and operation_watch["state"] == "RESULT_AVAILABLE"
                                   else recommend(state, offline)),
                "updated_at": now_iso(),
            }
            if state != self.last_state:
                append_bounded_event(EVENTS_FILE, {"timestamp": status["updated_at"], "state": state, "task_label": current_task,
                                                   "tool": marker.get("last_tool"), "health_state": "OK" if not offline else f"OFFLINE:{offline}",
                                                   "error_category": self.chat_detail if state == "ERROR" else None})
                self.last_state = state
            atomic_json(STATUS_FILE, status); self.status = status
            return status

    def run_poller(self) -> None:
        while not self.stop.wait(POLL_SECONDS):
            try:
                self.refresh(False)
            except Exception as exc:
                append_bounded_event(EVENTS_FILE, {"timestamp": now_iso(), "state": "ERROR", "error_category": f"watchdog-refresh:{type(exc).__name__}"})

    def recent_events(self) -> list[dict[str, Any]]:
        if not EVENTS_FILE.exists():
            return []
        out = []
        try:
            for line in EVENTS_FILE.read_text(encoding="utf-8").splitlines()[-MAX_EVENTS:]:
                try: out.append(json.loads(line))
                except json.JSONDecodeError: pass
        except OSError: pass
        return out


HTML = """<!doctype html><html><head><meta charset='utf-8'><title>Dev HQ Watchdog</title><style>
body{font:15px Segoe UI,Arial,sans-serif;max-width:980px;margin:28px auto;padding:0 18px;background:#111827;color:#e5e7eb}h1{font-size:24px}.card{background:#1f2937;border-radius:12px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:210px 1fr;gap:7px 16px}.k{color:#9ca3af}.state{font-weight:700;font-size:22px}button{padding:9px 14px;border:0;border-radius:8px;cursor:pointer}pre{white-space:pre-wrap}.ok{color:#86efac}.bad{color:#fca5a5}</style></head><body>
<h1>Dev HQ — Live Task Diagnostics</h1><div id='connection'></div><div class='card grid' id='main'></div><div class='card'><b>TOOLS</b><div id='tools'></div></div><div class='card'><button onclick='recheck()'>Перепроверить</button> <span id='msg'></span></div><div class='card'><b>Recent transitions</b><pre id='events'></pre></div>
<script>
function dur(s){s=Number(s||0);return [Math.floor(s/3600),Math.floor((s%3600)/60),Math.floor(s%60)].map(x=>x.toString().padStart(2,'0')).join(':')}
async function get(url){let r=await fetch(url);if(!r.ok)throw Error('HTTP '+r.status);return r.json()}
function field(parent,label,value){let k=document.createElement('div');k.className='k';k.textContent=label;let v=document.createElement('div');v.textContent=String(value??'—');if(label==='HQ TASK STATUS')v.className='state';parent.append(k,v)}
async function load(){try{let s=await get('/api/status');let r=s.watchdog_resources||{};let o=s.observation||{};let rows=[['HQ TASK STATUS',s.state],['Current task',s.current_task||'—'],['Elapsed',dur(s.elapsed_seconds)],['Last activity',s.last_activity_at],['Activity source',s.last_activity_source],['Last tool',s.last_tool],['Last checkpoint',s.last_checkpoint],['Operation control',s.operation_watch?.state||'UNINSTRUMENTED'],['Attention',s.notification ? s.notification.label+' — '+s.notification.reason : '—'],['Next action',s.notification?.next_action||'—'],['Current operation',s.operation_watch?.operations?.[0]?.label||'—'],['Expected by',s.operation_watch?.operations?.[0]?.deadline_at||'—'],['UI observation',o.state||'UNKNOWN'],['Observed window',s.chatgpt_window?.title||'—'],['ChatGPT/UI',s.chatgpt_state+': '+s.chatgpt_detail],['Stall timer',(s.stall_seconds||0)+' sec'],['RAM',(r.ram_mb||0)+' MB'],['CPU',(r.cpu_percent||0)+'% (avg '+(r.cpu_average_percent||0)+'%)'],['Recommendation',s.recommendation],['Updated',s.updated_at]];let main=document.getElementById('main');main.replaceChildren();rows.forEach(x=>field(main,...x));let t=document.getElementById('tools');t.replaceChildren();Object.entries(s.tools||{}).forEach(([k,v])=>{let d=document.createElement('div');d.textContent=k+': '+v;d.className=v==='OK'?'ok':'bad';t.append(d)});let e=await get('/api/events');document.getElementById('events').textContent=e.map(x=>x.timestamp+'  '+x.state+'  '+(x.task_label||'')).join('\\n');document.getElementById('connection').textContent='Live — Watchdog '+(s.version||'?')}catch(e){document.getElementById('connection').textContent='OFFLINE — монитор недоступен; ниже последние данные'}}
async function recheck(){let m=document.getElementById('msg');m.textContent='Проверка…';try{let r=await fetch('/api/recheck',{method:'POST'});if(!r.ok)throw Error();m.textContent='Готово';await load()}catch(e){m.textContent='Монитор недоступен'}}load();setInterval(load,5000)
</script></body></html>"""


def make_handler(wd: Watchdog):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None: pass
        def send_json(self, data: Any, code: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self) -> None:
            if self.path in ("/", "/hq-status"):
                body = HTML.encode("utf-8"); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            elif self.path == "/api/status": self.send_json(wd.status or wd.refresh(False))
            elif self.path == "/api/events": self.send_json(wd.recent_events())
            elif self.path == "/healthz": self.send_json({"ok": True, "version": WATCHDOG_VERSION, "updated_at": (wd.status or {}).get("updated_at")})
            else: self.send_json({"error": "not found"}, 404)
        def do_POST(self) -> None:
            if self.path == "/api/recheck": self.send_json(wd.refresh(True))
            else: self.send_json({"error": "not found"}, 404)
    return Handler


def signal_task(args: argparse.Namespace) -> int:
    marker = read_json(TASK_FILE, {})
    state = args.state.upper()
    now = now_iso()
    run_id, project_id = getattr(args, "run_id", None), getattr(args, "project_id", None)
    if bool(run_id) != bool(project_id):
        raise ValueError("Supply both --run-id and --project-id")
    if run_id and (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", run_id)
                   or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", project_id)):
        raise ValueError("Invalid run/project identity")
    changed_identity = bool(run_id and (run_id != marker.get("run_id") or project_id != marker.get("project_id")))
    changed_task = bool(args.task and args.task != marker.get("current_task"))
    if changed_identity or changed_task:
        marker = {}
    if run_id:
        marker.update({"run_id": run_id, "project_id": project_id})
    else:
        marker.pop("run_id", None)
        marker.pop("project_id", None)
    handle = getattr(args, "window_handle", None)
    if handle:
        target = next((w for w in visible_windows() if str(w.get("handle")) == str(handle) and is_chat_window(w)), None)
        if target is None:
            raise ValueError("Window handle is not an eligible ChatGPT/Codex window")
        marker["window_binding"] = bind_window(target)
    if state == "WORKING" and marker.get("state") != "WORKING":
        marker["task_started_at"] = now
    if state == "IDLE":
        identity = {key: marker[key] for key in ("run_id", "project_id", "window_binding") if key in marker}
        marker = {"state": "IDLE", "current_task": "", "last_activity_at": now, "last_activity_source": args.source or "task-marker",
                  "last_tool": args.tool, "last_checkpoint": args.checkpoint, "updated_at": now, **identity}
    else:
        marker.update({"state": state, "current_task": args.task or marker.get("current_task") or "", "last_activity_at": now,
                       "last_activity_source": args.source or "task-marker", "last_tool": args.tool or marker.get("last_tool"),
                       "last_checkpoint": args.checkpoint or marker.get("last_checkpoint"), "updated_at": now})
        if state == "ERROR" and args.message: marker["error"] = args.message
    atomic_json(TASK_FILE, marker)
    print(json.dumps(marker, ensure_ascii=False))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run"); run.add_argument("--port", type=int, default=DEFAULT_PORT)
    sig = sub.add_parser("signal"); sig.add_argument("--state", required=True, choices=["WORKING", "WAITING", "IDLE", "ERROR"]); sig.add_argument("--task"); sig.add_argument("--source"); sig.add_argument("--tool"); sig.add_argument("--checkpoint"); sig.add_argument("--message")
    sig.add_argument("--run-id"); sig.add_argument("--project-id"); sig.add_argument("--window-handle")
    one = sub.add_parser("status")
    args = p.parse_args()
    if args.cmd == "signal": return signal_task(args)
    wd = Watchdog(getattr(args, "port", DEFAULT_PORT))
    if args.cmd == "status":
        print(json.dumps(wd.refresh(True), ensure_ascii=False, indent=2)); return 0
    RUNTIME.mkdir(parents=True, exist_ok=True); wd.refresh(False)
    t = threading.Thread(target=wd.run_poller, name="hq-watchdog-poller", daemon=True); t.start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(wd))
    try: server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt: pass
    finally: wd.stop.set(); server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

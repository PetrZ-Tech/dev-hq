import importlib.util
import json
import time
import tempfile
import threading
import unittest
import urllib.request
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "hq_watchdog.py"
spec = importlib.util.spec_from_file_location("hq_watchdog", MODULE_PATH)
wd = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(wd)


class WatchdogStateTests(unittest.TestCase):
    def tools(self, ok=True):
        return {"Desktop Commander": ok, "Chrome DevTools": ok, "Codebase Memory": ok,
                "Browser Adapter": ok, "Desktop Control Adapter": ok, "HQ Watchdog": True}

    def test_idle(self):
        state, stall, offline = wd.decide_state({"state": "IDLE"}, self.tools(), "unknown", 1000, 995)
        self.assertEqual((state, stall, offline), ("IDLE", 0, None))

    def test_working(self):
        state, stall, _ = wd.decide_state({"state": "WORKING"}, self.tools(), "ready_or_unknown", 1000, 970)
        self.assertEqual(state, "WORKING")
        self.assertEqual(stall, 30)

    def test_waiting(self):
        state, _, _ = wd.decide_state({"state": "WAITING"}, self.tools(), "ready_or_unknown", 1000, 900)
        self.assertEqual(state, "WAITING")

    def test_stalled(self):
        state, stall, _ = wd.decide_state({"state": "WORKING"}, self.tools(), "ready_or_unknown", 1000, 879)
        self.assertEqual(state, "STALLED")
        self.assertEqual(stall, 121)

    def test_generation_prevents_stall(self):
        state, _, _ = wd.decide_state({"state": "WORKING"}, self.tools(), "generating", 1000, 100)
        self.assertEqual(state, "WORKING")

    def test_error_marker(self):
        state, _, _ = wd.decide_state({"state": "WORKING"}, self.tools(), "error", 1000, 999)
        self.assertEqual(state, "ERROR")

    def test_tool_offline_active_is_error(self):
        t = self.tools(); t["Codebase Memory"] = False
        state, _, offline = wd.decide_state({"state": "WORKING"}, t, "ready_or_unknown", 1000, 999)
        self.assertEqual(state, "ERROR")
        self.assertEqual(offline, "Codebase Memory")

    def test_tool_offline_idle_is_offline(self):
        t = self.tools(); t["Browser Adapter"] = False
        state, _, offline = wd.decide_state({"state": "IDLE"}, t, "ready_or_unknown", 1000, None)
        self.assertEqual(state, "OFFLINE")
        self.assertEqual(offline, "Browser Adapter")

    def test_ui_generation_can_promote_idle_to_working(self):
        state, _, _ = wd.decide_state({"state": "IDLE"}, self.tools(), "generating", 1000, None)
        self.assertEqual(state, "WORKING")

    def test_recommendations_never_auto_retry(self):
        self.assertEqual(wd.recommend("STALLED"), "Run read-only recovery audit before retry")
        self.assertEqual(wd.recommend("ERROR"), "Recovery audit — do not blind Retry")

    def test_log_rotation(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.jsonl"
            for i in range(130):
                wd.append_bounded_event(p, {"i": i}, max_events=100)
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 100)
            self.assertEqual(rows[0]["i"], 30)
            self.assertEqual(rows[-1]["i"], 129)


def chat(handle="1", pid=10, process="chatgpt.exe", title="ChatGPT", foreground=False):
    return {"handle": handle, "pid": pid, "process": process, "title": title, "foreground": foreground}


class WindowBindingTests(unittest.TestCase):
    def test_foreground_settings_is_not_a_chat(self):
        target = chat(process="chrome.exe", title="HQ - ChatGPT - Google Chrome")
        other = chat("2", process="chrome.exe", title="Settings - Google Chrome", foreground=True)
        self.assertEqual(wd.choose_chat_window([other, target]), target)

    def test_arbitrary_browser_is_not_a_fallback(self):
        for title in ["OpenAI - Google Chrome", "HQ dashboard - Google Chrome",
                      "Sign in to Codex with ChatGPT - OpenAI - Google Chrome"]:
            self.assertIsNone(wd.choose_chat_window([chat(process="chrome.exe", title=title)]))

    def test_multiple_chats_are_ambiguous_even_with_foreground(self):
        self.assertIsNone(wd.choose_chat_window([chat(), chat("2", pid=20, foreground=True)]))

    def test_explicit_binding_wins_over_another_foreground_chat(self):
        target = chat()
        self.assertEqual(wd.choose_chat_window([chat("2", pid=20, foreground=True), target], wd.bind_window(target)), target)

    def test_reused_handle_with_changed_pid_is_not_followed(self):
        self.assertIsNone(wd.choose_chat_window([chat(pid=20)], wd.bind_window(chat(pid=10))))

    def test_bound_chrome_tab_change_does_not_follow_other_chat(self):
        bound = chat(process="chrome.exe", title="Task A - ChatGPT - Google Chrome")
        changed = chat(process="chrome.exe", title="Task B - ChatGPT - Google Chrome")
        self.assertIsNone(wd.choose_chat_window([changed, chat("2")], wd.bind_window(bound)))

    def test_codex_process_is_supported(self):
        target = chat(process="codex.exe", title="Codex")
        self.assertEqual(wd.choose_chat_window([target]), target)


class WatchdogObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name)
        for name, value in {"RUNTIME": self.runtime, "TASK_FILE": self.runtime / "marker.json",
                            "STATUS_FILE": self.runtime / "status.json", "EVENTS_FILE": self.runtime / "events.jsonl"}.items():
            self.enterContext(patch.object(wd, name, value))
        self.enterContext(patch.object(wd.time, "time", return_value=1000.0))
        self.windows = self.enterContext(patch.object(wd, "visible_windows", return_value=[chat()]))
        self.monitor = wd.Watchdog()
        self.enterContext(patch.object(self.monitor, "tool_health", return_value={"test-tool": True}))
        self.enterContext(patch.object(self.monitor.resources, "sample", return_value={}))
        self.deep = self.enterContext(patch.object(self.monitor, "deep_ui_check", return_value=("unknown", "bounded UI scan timed out without marker")))

    @staticmethod
    def stamp(epoch):
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat()

    def marker(self, state="WORKING", at=800, **extra):
        value = {"state": state, "last_activity_at": self.stamp(at),
                 "task_started_at": self.stamp(700), "current_task": "Task A", **extra}
        wd.atomic_json(wd.TASK_FILE, value)
        return value

    def run_record(self, project_id, run_id, at):
        path = self.runtime / "task-runs" / project_id / (run_id + ".json")
        wd.atomic_json(path, {"project_id": project_id, "run_id": run_id, "updated_at": self.stamp(at)})
        return path

    def test_unrelated_project_activity_cannot_reset_stall(self):
        self.marker(run_id="run-a", project_id="project-a")
        self.run_record("project-b", "run-b", 999)
        status = self.monitor.refresh()
        self.assertEqual((status["state"], status["stall_seconds"]), ("STALLED", 200))

    def test_matching_run_semantic_activity_is_used(self):
        self.marker(run_id="run-a", project_id="project-a")
        self.run_record("project-a", "run-a", 990)
        status = self.monitor.refresh()
        self.assertEqual((status["state"], status["stall_seconds"]), ("WORKING", 10))

    def test_touching_record_is_not_new_activity(self):
        marker = self.marker(run_id="run-a", project_id="project-a")
        path = self.run_record("project-a", "run-a", 790)
        path.touch()
        self.assertEqual(wd.latest_lifecycle_activity(marker), (790, "run-a"))
        self.assertEqual(self.monitor.refresh()["state"], "STALLED")

    def test_legacy_marker_does_not_borrow_any_run(self):
        self.marker()
        self.run_record("project-a", "run-a", 999)
        self.assertEqual(self.monitor.refresh()["stall_seconds"], 200)

    def test_result_notification_requests_verification_without_false_deadline_claim(self):
        self.marker()
        view = {'state': 'RESULT_AVAILABLE', 'coverage': 'REGISTERED_OPERATIONS_ONLY',
                'operations': [{'id': 'fixture', 'state': 'RESULT_AVAILABLE', 'label': 'Owned fixture',
                                'tool': 'fixture', 'result_observation': {'reason': 'process-exit-recorded'}}]}
        with patch.object(wd.operations, 'inspect', return_value=view):
            status = self.monitor.refresh()
        self.assertEqual(status['state'], 'CHECK_REQUIRED')
        self.assertEqual(status['notification']['next_action'], 'VERIFY_RESULT_AND_ACKNOWLEDGE')
        self.assertIn('verify evidence', status['recommendation'])
        self.assertNotIn('exceeded', status['recommendation'])

    def test_identity_mismatch_or_unsafe_path_is_ignored(self):
        marker = self.marker(run_id="run-a", project_id="project-a")
        p = self.run_record("project-a", "run-a", 999)
        wd.atomic_json(p, {"run_id": "other", "project_id": "project-a", "updated_at": self.stamp(999)})
        self.assertEqual(wd.latest_lifecycle_activity(marker), (None, None))
        marker["run_id"] = "../../other"
        self.assertEqual(wd.latest_lifecycle_activity(marker), (None, None))

    def test_stale_idle_plus_ui_timeout_is_unknown(self):
        self.marker("IDLE", at=800, current_task="")
        status = self.monitor.refresh()
        self.assertEqual(status["state"], "UNKNOWN")
        self.assertEqual(status["observation"]["state"], "DEGRADED")
        self.assertNotEqual(status["recommendation"], "No active task")

    def test_missing_or_corrupt_marker_is_unknown(self):
        self.assertEqual(self.monitor.refresh()["state"], "UNKNOWN")
        wd.TASK_FILE.write_bytes(b"\xff\xfe invalid")
        self.assertEqual(self.monitor.refresh()["state"], "UNKNOWN")

    def test_fresh_working_marker_survives_unknown_ui(self):
        self.marker(at=990)
        status = self.monitor.refresh()
        self.assertEqual(status["state"], "WORKING")
        self.assertEqual(status["observation"]["state"], "DEGRADED")

    def test_task_name_never_comes_from_window_title(self):
        self.marker("IDLE", at=995, current_task="")
        status = self.monitor.refresh()
        self.assertEqual(status["current_task"], "")
        self.assertEqual(status["chatgpt_window"]["title"], "ChatGPT")

    def test_cached_generation_is_invalidated_when_window_disappears(self):
        self.marker("IDLE", at=800, current_task="")
        self.deep.return_value = ("generating", "visible generation control")
        self.assertEqual(self.monitor.refresh(manual=True)["state"], "WORKING")
        self.windows.return_value = []
        self.assertEqual(self.monitor.refresh()["state"], "UNKNOWN")

    def test_new_run_cannot_reuse_cached_generation_from_old_run(self):
        self.marker("IDLE", at=800, run_id="old", project_id="a")
        self.deep.return_value = ("generating", "visible generation control")
        self.monitor.refresh(manual=True)
        self.marker("IDLE", at=800, run_id="new", project_id="a")
        self.windows.return_value = [chat("2", pid=20)]
        self.assertEqual(self.monitor.refresh()["state"], "UNKNOWN")

    def test_new_run_same_window_also_discards_old_generation(self):
        self.marker("IDLE", at=800, run_id="old", project_id="a")
        self.deep.return_value = ("generating", "visible generation control")
        self.monitor.refresh(manual=True)
        self.marker("IDLE", at=800, run_id="new", project_id="a")
        self.assertEqual(self.monitor.refresh()["state"], "UNKNOWN")

    def test_bound_window_does_not_jump_when_other_window_is_added(self):
        self.marker()
        self.monitor.refresh()
        self.windows.return_value = [chat("2", pid=20, foreground=True), chat()]
        self.assertEqual(self.monitor.refresh()["chatgpt_window"]["handle"], "1")

    def test_unknown_working_timestamp_is_not_fresh_activity(self):
        state, _, _ = wd.decide_state({"state": "WORKING"}, {"tool": True}, "unknown", 1000, None)
        self.assertEqual(state, "UNKNOWN")

    def test_zero_epoch_activity_is_not_replaced_with_now(self):
        state, stall, _ = wd.decide_state({"state": "WORKING"}, {"tool": True}, "unknown", 1000, 0)
        self.assertEqual((state, stall), ("STALLED", 1000))


class DeepUiTests(unittest.TestCase):
    def setUp(self):
        self.monitor = wd.Watchdog()
        self.enterContext(patch.object(wd, "tcp_alive", return_value=True))
        self.mcp = self.enterContext(patch.object(self.monitor, "mcp_tool"))

    def payload(self, value):
        self.mcp.return_value = {"result": {"content": [{"text": json.dumps(value)}]}}

    def test_ui_timeout_is_unknown(self):
        self.payload({"errorType": "timeout"})
        self.assertEqual(self.monitor.deep_ui_check(chat())[0], "unknown")

    def test_no_marker_is_not_proof_of_idle(self):
        self.payload({"success": False, "errorType": "not_found"})
        self.assertEqual(self.monitor.deep_ui_check(chat())[0], "unknown")

    def test_generation_control_is_observed_without_storing_user_text(self):
        self.payload({"success": True, "elements": [{"name": "Stop generating"}]})
        state, detail = self.monitor.deep_ui_check(chat())
        self.assertEqual((state, detail), ("generating", "visible generation control"))

    def test_body_text_containing_retry_is_not_an_error_control(self):
        self.payload({"success": True, "elements": [{"name": "My private draft says Retry later"}]})
        state, detail = self.monitor.deep_ui_check(chat())
        self.assertEqual(state, "unknown")
        self.assertNotIn("private", detail)

    def test_missing_window_never_calls_ui_provider(self):
        self.assertEqual(self.monitor.deep_ui_check(None)[0], "unknown")
        self.mcp.assert_not_called()

    def test_ui_text_is_valid_utf8_and_no_mojibake(self):
        self.assertIn("Перепроверить", wd.HTML)
        self.assertIn("Готово", wd.HTML)
        self.assertNotIn("РџРµ", wd.HTML)
        self.assertNotIn("вЂ”,", wd.HTML)


class SignalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "marker.json"
        self.enterContext(patch.object(wd, "TASK_FILE", self.path))

    def args(self, **overrides):
        values = dict(state="WORKING", task="Task", source="fixture", tool=None,
                      checkpoint=None, message=None, run_id=None, project_id=None, window_handle=None)
        return Namespace(**{**values, **overrides})

    def test_manual_signal_does_not_borrow_old_identity(self):
        wd.atomic_json(self.path, {"state": "WORKING", "current_task": "Task", "run_id": "old", "project_id": "a"})
        with patch("sys.stdout"):
            wd.signal_task(self.args())
        self.assertNotIn("run_id", wd.read_json(self.path))

    def test_partial_identity_is_rejected_without_writes(self):
        with self.assertRaises(ValueError):
            wd.signal_task(self.args(run_id="run"))
        self.assertFalse(self.path.exists())

    def test_explicit_binding_requires_eligible_window(self):
        with patch.object(wd, "visible_windows", return_value=[chat()]), patch("sys.stdout"):
            wd.signal_task(self.args(window_handle="1", run_id="run", project_id="a"))
        self.assertEqual(wd.read_json(self.path)["window_binding"]["pid"], 10)

    def test_new_identity_does_not_preserve_old_binding(self):
        wd.atomic_json(self.path, {"state": "WORKING", "current_task": "Task", "run_id": "old", "project_id": "a", "window_binding": wd.bind_window(chat())})
        with patch("sys.stdout"):
            wd.signal_task(self.args(run_id="new", project_id="a"))
        marker = wd.read_json(self.path)
        self.assertEqual(marker["run_id"], "new")
        self.assertNotIn("window_binding", marker)


class LifecycleMarkerIdentityTests(unittest.TestCase):
    def test_lifecycle_signals_keep_only_the_same_run_binding(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "task_lifecycle.py"
        spec = importlib.util.spec_from_file_location("lifecycle_identity_test", path)
        lc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lc)
        with tempfile.TemporaryDirectory() as td, patch.object(lc, "WATCHDOG_TASK_FILE", Path(td) / "marker.json"):
            lc.watchdog_signal("WORKING", "A", "start", run_id="run-a", project_id="a")
            marker = json.loads(lc.WATCHDOG_TASK_FILE.read_text(encoding="utf-8"))
            self.assertEqual((marker["run_id"], marker["project_id"]), ("run-a", "a"))
            marker["window_binding"] = wd.bind_window(chat())
            lc.WATCHDOG_TASK_FILE.write_text(json.dumps(marker), encoding="utf-8")
            lc.watchdog_signal("WORKING", "A", "verify", run_id="run-a", project_id="a")
            same = json.loads(lc.WATCHDOG_TASK_FILE.read_text(encoding="utf-8"))
            self.assertIn("window_binding", same)
            lc.watchdog_signal("WORKING", "B", "start", run_id="run-b", project_id="b")
            other = json.loads(lc.WATCHDOG_TASK_FILE.read_text(encoding="utf-8"))
            self.assertEqual(other["run_id"], "run-b")
            self.assertNotIn("window_binding", other)

    def test_idle_lifecycle_signal_preserves_run_identity_without_task_name(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "task_lifecycle.py"
        spec = importlib.util.spec_from_file_location("lifecycle_identity_idle", path)
        lc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lc)
        with tempfile.TemporaryDirectory() as td, patch.object(lc, "WATCHDOG_TASK_FILE", Path(td) / "marker.json"):
            lc.watchdog_signal("IDLE", "A", "ready", run_id="run-a", project_id="a")
            marker = json.loads(lc.WATCHDOG_TASK_FILE.read_text(encoding="utf-8"))
            self.assertEqual(marker["run_id"], "run-a")
            self.assertEqual(marker["current_task"], "")


class HttpContractTests(unittest.TestCase):
    def test_live_http_contract_preserves_unknown_and_utf8(self):
        monitor = wd.Watchdog()
        monitor.status = {"state": "UNKNOWN", "version": wd.WATCHDOG_VERSION,
                          "observation": {"state": "DEGRADED"}, "updated_at": wd.now_iso()}
        with wd.ThreadingHTTPServer(("127.0.0.1", 0), wd.make_handler(monitor)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(base + "/healthz", timeout=5) as response:
                    self.assertEqual(json.load(response)["version"], wd.WATCHDOG_VERSION)
                with urllib.request.urlopen(base + "/api/status", timeout=5) as response:
                    self.assertEqual(json.load(response)["state"], "UNKNOWN")
                with urllib.request.urlopen(base + "/hq-status", timeout=5) as response:
                    self.assertIn("Перепроверить", response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

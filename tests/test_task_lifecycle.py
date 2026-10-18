import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "task_lifecycle.py"
SPEC = importlib.util.spec_from_file_location("task_lifecycle_under_test", MODULE_PATH)
lc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lc)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.projects = Path(self.tmp.name) / "Projects"
        self.hq = self.projects / "dev-hq"
        self.project = self.projects / "fixture-project"
        self.project.mkdir(parents=True)
        self.run_root = self.hq / "runtime" / "task-runs"
        self.run_path = self.run_root / "fixture-project" / "fixture.json"
        self.report_path = self.project / "report.md"
        self.report_path.write_text("# Result\nVerified local fixture.\n", encoding="utf-8")
        for name, value in {"PROJECTS_ROOT": self.projects, "HQ_ROOT": self.hq,
                            "RUN_ROOT": self.run_root,
                            "WATCHDOG_TASK_FILE": self.hq / "runtime" / "marker.json"}.items():
            self.enterContext(patch.object(lc, name, value))
        self.signal = self.enterContext(patch.object(lc, "watchdog_signal"))
        self.enterContext(patch.object(lc, "git_snapshot", return_value={"is_git": False}))
        self.record = {
            "schema_version": 2, "run_id": "fixture", "project_id": "fixture-project",
            "project_path": str(self.project), "task": "Fixture task", "status": "IN_PROGRESS",
            "completed_at": None, "technical_completed_at": None, "change_kind": "code",
            "reporting": {"preparation": "PENDING", "delivery": "UNCONFIRMED"},
            "stages": {s: {"status": "PASS", "note": "Fixture verified", "evidence": {}}
                       for s in lc.STAGES},
        }
        self.record["stages"]["verify"]["evidence"] = {"reference": "fixture-tests:PASS"}
        self.record["stages"]["quality_gate"]["evidence"] = {
            "quality_gate": "PASS", "exit_code": 0, "checks": [{"name": "fixture", "status": "PASS"}]}
        self.record["stages"]["report"] = {"status": "PENDING", "note": "", "evidence": {}}
        self.persist()

    def persist(self):
        lc.save(self.record, self.run_path)

    def read(self):
        return json.loads(self.run_path.read_text(encoding="utf-8"))

    def invoke(self, command, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = command(Namespace(run=str(self.run_path), **kwargs))
        return code, json.loads(output.getvalue())

    def test_finish_only_completes_technical_work(self):
        code, result = self.invoke(lc.cmd_finish)
        record = self.read()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "TECHNICAL_COMPLETE")
        self.assertEqual(record["stages"]["report"]["status"], "PENDING")
        self.assertEqual(record["reporting"]["delivery"], "UNCONFIRMED")
        self.assertIsNone(record["completed_at"])
        self.assertTrue(record["technical_completed_at"])
        self.assertEqual(self.signal.call_args.args[-1], "technical:COMPLETE;report:PENDING")

    def test_mandatory_stages_cannot_be_skipped(self):
        for stage in lc.NON_SKIPPABLE:
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                lc.set_stage(self.record, stage, "SKIP", "Attempted bypass")

    def test_optional_skips_need_reasons(self):
        for stage in {"checkpoint", "state_handoff", "adr", "backup", "memory"}:
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                lc.set_stage(self.record, stage, "SKIP", " ")
            lc.set_stage(self.record, stage, "SKIP", "Not applicable to this fixture")

    def test_quality_gate_cannot_be_skipped_for_code_config_or_legacy(self):
        for kind in ["code", "config", None]:
            record = copy.deepcopy(self.record)
            if kind is None:
                record.pop("change_kind")
            else:
                record["change_kind"] = kind
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                lc.set_stage(record, "quality_gate", "SKIP", "Attempted bypass")

    def test_docs_and_read_only_gate_exceptions_are_explicit(self):
        for kind in ["docs", "read-only"]:
            self.record["change_kind"] = kind
            lc.set_stage(self.record, "quality_gate", "SKIP", "No code or config changed")
            self.assertFalse(lc.summary(self.record)["invalid"])

    def test_verify_needs_note_and_evidence_reference(self):
        for note, evidence in [("checked", {}), ("", {"reference": "tests:PASS"}),
                               ("checked", {"reference": " "})]:
            with self.subTest(note=note, evidence=evidence), self.assertRaises(ValueError):
                lc.set_stage(self.record, "verify", "PASS", note, evidence)
        lc.set_stage(self.record, "verify", "PASS", "Tests passed", {"reference": "tests:PASS"})

    def test_quality_gate_mark_requires_runner_evidence(self):
        with self.assertRaises(ValueError):
            lc.set_stage(self.record, "quality_gate", "PASS", "Trust me")

    def test_gate_rejects_exit_code_result_mismatch(self):
        payload = {"quality_gate": "PASS", "checks": [{"name": "fixture", "status": "PASS"}]}
        before = self.run_path.read_bytes()
        with patch.object(lc, "run_cmd", return_value=(2, json.dumps(payload))):
            with self.assertRaises(ValueError):
                self.invoke(lc.cmd_gate, criteria_ok="yes")
        self.assertEqual(before, self.run_path.read_bytes())

    def test_finish_revalidates_injected_skip(self):
        for stage in ["verify", "quality_gate"]:
            record = copy.deepcopy(self.record)
            record["stages"][stage] = {"status": "SKIP", "note": "", "evidence": {}}
            lc.save(record, self.run_path)
            before = self.run_path.read_bytes()
            code, result = self.invoke(lc.cmd_finish)
            self.assertEqual(code, 2)
            self.assertTrue(result["invalid"])
            self.assertEqual(before, self.run_path.read_bytes())
        self.signal.assert_not_called()

    def test_finish_blocks_missing_stage(self):
        del self.record["stages"]["verify"]
        self.persist()
        code, result = self.invoke(lc.cmd_finish)
        self.assertEqual(code, 2)
        self.assertIn("verify", result["pending"])

    def test_finish_blocks_failed_check(self):
        self.record["stages"]["verify"]["status"] = "FAIL"
        self.persist()
        code, result = self.invoke(lc.cmd_finish)
        self.assertEqual(code, 2)
        self.assertIn("verify", result["failed"])

    def test_warning_is_not_hidden(self):
        self.record["stages"]["verify"]["status"] = "WARN"
        self.persist()
        code, result = self.invoke(lc.cmd_finish)
        self.assertEqual(code, 0)
        self.assertIn("verify", result["warnings"])
        self.assertEqual(result["status"], "TECHNICAL_COMPLETE")

    def test_report_cannot_be_forged_by_mark(self):
        with self.assertRaises(ValueError):
            self.invoke(lc.cmd_mark, stage="report", status="PASS", note="sent", evidence_ref="")

    def test_report_requires_technical_completion_first(self):
        before = self.run_path.read_bytes()
        code, result = self.invoke(lc.cmd_prepare_report, file=str(self.report_path))
        self.assertEqual((code, result["status"]), (2, "BLOCKED"))
        self.assertEqual(before, self.run_path.read_bytes())

    def test_prepared_report_has_hash_but_no_delivery_claim(self):
        self.invoke(lc.cmd_finish)
        code, result = self.invoke(lc.cmd_prepare_report, file=str(self.report_path))
        record = self.read()
        self.assertEqual((code, result["status"]), (0, "READY_TO_REPORT"))
        self.assertEqual(record["reporting"]["delivery"], "UNCONFIRMED")
        self.assertEqual(record["reporting"]["artifact"]["sha256"],
                         hashlib.sha256(self.report_path.read_bytes()).hexdigest())
        self.assertIsNone(record["completed_at"])
        self.assertEqual(record["stages"]["report"]["status"], "PASS")
        self.assertIn("unconfirmed", record["stages"]["report"]["note"])

    def test_report_file_must_exist(self):
        self.invoke(lc.cmd_finish)
        with self.assertRaises(ValueError):
            self.invoke(lc.cmd_prepare_report, file=str(self.project / "missing.md"))

    def test_finish_retry_preserves_current_report_without_writes(self):
        self.invoke(lc.cmd_finish)
        self.invoke(lc.cmd_prepare_report, file=str(self.report_path))
        before = self.run_path.read_bytes()
        calls = self.signal.call_count
        code, result = self.invoke(lc.cmd_finish)
        self.assertEqual((code, result["status"]), (0, "READY_TO_REPORT"))
        self.assertEqual(before, self.run_path.read_bytes())
        self.assertEqual(calls, self.signal.call_count)

    def test_finish_retry_does_not_certify_changed_report(self):
        self.invoke(lc.cmd_finish)
        self.invoke(lc.cmd_prepare_report, file=str(self.report_path))
        self.report_path.write_text("Changed after verification", encoding="utf-8")
        code, result = self.invoke(lc.cmd_finish)
        self.assertEqual((code, result["status"]), (0, "TECHNICAL_COMPLETE"))
        self.assertEqual(self.read()["stages"]["report"]["status"], "PENDING")

    def test_report_cannot_be_empty_or_whitespace(self):
        self.invoke(lc.cmd_finish)
        for content in ["", " \n "]:
            self.report_path.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.invoke(lc.cmd_prepare_report, file=str(self.report_path))

    def test_report_must_be_text_inside_projects(self):
        self.invoke(lc.cmd_finish)
        for path in [Path(self.tmp.name) / "outside.md", self.project / "run.json"]:
            path.write_text("not a user report", encoding="utf-8")
            with self.subTest(path=str(path)), self.assertRaises(ValueError):
                self.invoke(lc.cmd_prepare_report, file=str(path))

    def test_new_technical_work_invalidates_prepared_report(self):
        self.invoke(lc.cmd_finish)
        self.invoke(lc.cmd_prepare_report, file=str(self.report_path))
        self.invoke(lc.cmd_mark, stage="execute", status="PASS", note="New work", evidence_ref="")
        record = self.read()
        self.assertEqual(record["status"], "IN_PROGRESS")
        self.assertEqual(record["stages"]["report"]["status"], "PENDING")
        self.assertEqual(record["reporting"]["preparation"], "PENDING")
        self.assertIsNone(record["technical_completed_at"])

    def test_legacy_status_is_read_only_and_not_delivery_proof(self):
        self.record.pop("reporting")
        self.record["schema_version"] = 1
        self.record["status"] = "DONE"
        self.record["stages"]["report"] = {"status": "PASS", "note": "Old auto report"}
        self.persist()
        before = self.run_path.read_bytes()
        code, result = self.invoke(lc.cmd_status)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "DONE")
        self.assertEqual(result["reporting"]["delivery"], "UNCONFIRMED")
        self.assertEqual(result["reporting"]["preparation"], "LEGACY_UNVERIFIED")
        self.assertEqual(before, self.run_path.read_bytes())

    def test_start_default_is_code_and_has_no_report_claim(self):
        args = lc.build_parser().parse_args([
            "start", "--project", str(self.project), "--project-id", "fixture-project",
            "--task", "test start", "--model", "test model", "--effort", "Low"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(lc.cmd_start(args), 0)
        records = list((self.run_root / "fixture-project").glob("*test-start*.json"))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text(encoding="utf-8"))
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(record["change_kind"], "code")
        self.assertEqual(record["reporting"]["delivery"], "UNCONFIRMED")


if __name__ == "__main__":
    unittest.main()

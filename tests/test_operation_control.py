import copy
import json
import os
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import operation_control as op
from test_task_lifecycle import LifecycleTests, lc
from test_hq_watchdog import WatchdogObservationTests, wd


class OperationControlTests(unittest.TestCase):
    def setUp(self):
        self.record = {'run_id': 'run-a'}
        self.operation = self.begin()

    def begin(self, **kwargs):
        return op.begin(self.record, **dict(kind='plugin', tool='fixture', label='Controlled operation',
                        expected_seconds=300, at=1000, **kwargs))

    def event(self, name, **kwargs):
        return op.event(self.record, self.operation['id'], name, evidence_ref='fixture:result',
                        note='Controlled observation', at=1010, **kwargs)

    def test_every_kind_has_same_deadline_contract(self):
        for kind in op.KINDS:
            with self.subTest(kind=kind):
                record = {'run_id': kind}
                op.begin(record, kind=kind, tool='fixture', label=kind, expected_seconds=60, at=1000)
                self.assertEqual(op.inspect(record, at=1060)['state'], 'OVERDUE')

    def test_normal_long_operation_waits_past_old_stall_threshold(self):
        self.assertEqual(op.inspect(self.record, at=1200)['state'], 'WAITING_RESULT')

    def test_overdue_is_not_proof_of_failure(self):
        view = op.inspect(self.record, at=1301)
        self.assertEqual(view['state'], 'OVERDUE')
        self.assertEqual(self.operation['state'], 'RUNNING')
        self.assertFalse(view['operations'][0]['automatic_retry'])

    def test_observation_never_advances_progress(self):
        progress = self.operation['last_progress_at']
        self.event('observed')
        self.assertEqual(self.operation['last_progress_at'], progress)
        self.assertEqual(self.operation['last_observed_at'], op.iso(1010))

    def test_extension_is_observation_not_progress(self):
        self.event('extend', expected_seconds=600)
        self.assertEqual(self.operation['deadline_at'], op.iso(1610))
        self.assertEqual(self.operation['last_progress_at'], op.iso(1000))

    def test_extension_requires_integer_bounded_duration(self):
        for value in (None, True, '30', 0, 86401):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.event('extend', expected_seconds=value)

    def test_explicit_progress_updates_timestamp(self):
        self.event('progress')
        self.assertEqual(self.operation['last_progress_at'], op.iso(1010))

    def test_waiting_user_does_not_overdue_and_resume_preserves_budget(self):
        self.event('waiting-input')
        self.assertEqual(op.inspect(self.record, at=5000)['state'], 'WAITING_INPUT')
        op.event(self.record, self.operation['id'], 'progress', evidence_ref='fixture:input',
                 note='Input supplied', at=5010)
        self.assertEqual(self.operation['deadline_at'], op.iso(5300))
        self.assertEqual(op.inspect(self.record, at=5010)['state'], 'WAITING_RESULT')

    def test_wait_cannot_be_extended_without_resume(self):
        self.event('waiting-input')
        with self.assertRaises(ValueError):
            self.event('extend', expected_seconds=60)

    def test_terminal_completion_needs_evidence(self):
        with self.assertRaises(ValueError):
            op.event(self.record, self.operation['id'], 'succeeded', evidence_ref='', note='Done')
        self.event('succeeded')
        self.assertEqual(op.guard(self.record), {'blocked': [], 'invalid': []})
        self.assertEqual(op.inspect(self.record, at=1500)['state'], 'IDLE')

    def test_failure_blocks_until_recorded_resolution(self):
        self.event('failed')
        self.assertEqual(op.guard(self.record)['blocked'], [self.operation['id']])
        self.event('resolve', resolution='FAILED')
        self.assertFalse(op.guard(self.record)['blocked'])

    def test_unknown_cannot_be_blindly_marked_success(self):
        self.event('outcome-unknown')
        with self.assertRaises(ValueError):
            self.event('succeeded')
        with self.assertRaises(ValueError):
            self.event('resolve')
        self.event('resolve', resolution='SUCCEEDED')
        self.assertEqual(self.operation['resolved_outcome'], 'SUCCEEDED')

    def test_side_effect_needs_key_and_unresolved_duplicate_is_blocked(self):
        with self.assertRaises(ValueError):
            self.begin(side_effect=True)
        effect = self.begin(side_effect=True, action_key='create-item')
        for state in ('RUNNING', 'WAITING_INPUT', 'FAILED', 'OUTCOME_UNKNOWN'):
            effect.update(state=state, paused_at=op.iso(1000), evidence_ref='fixture:failure')
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.begin(side_effect=True, action_key='create-item')
        op.event(self.record, effect['id'], 'resolve', evidence_ref='fixture:lookup',
                 note='No item exists', resolution='NOT_EXECUTED', at=1200)
        self.begin(side_effect=True, action_key='create-item')

    def test_live_pid_does_not_prove_progress_or_success(self):
        self.operation['probe'] = {'kind': 'process', 'pid': 42, 'identity': '42:start'}
        before = copy.deepcopy(self.record)
        view = op.inspect(self.record, at=1301, probe_fn=lambda _: {'state': 'ALIVE', 'identity': '42:start'})
        self.assertEqual(view['state'], 'OVERDUE')
        self.assertEqual(self.record, before)

    def test_exited_missing_reused_or_unavailable_process_is_unknown(self):
        self.operation['probe'] = {'kind': 'process', 'pid': 42, 'identity': '42:start'}
        for result in ({'state': 'EXITED', 'identity': '42:start'}, {'state': 'NOT_OBSERVED'},
                       {'state': 'ALIVE', 'identity': '42:reused'}):
            with self.subTest(result=result):
                view = op.inspect(self.record, at=1010, probe_fn=lambda _: result)
                self.assertEqual(view['state'], 'OUTCOME_UNKNOWN')
        def broken(_):
            raise OSError('unavailable')
        self.assertEqual(op.inspect(self.record, at=1010, probe_fn=broken)['state'], 'OUTCOME_UNKNOWN')

    def test_pid_probe_is_periodic_and_cache_never_writes_record(self):
        self.operation['probe'] = {'kind': 'process', 'pid': 42, 'identity': '42:start'}
        calls, cache, original = [], {}, copy.deepcopy(self.record)
        def probe(pid):
            calls.append(pid)
            return {'state': 'ALIVE', 'identity': '42:start'}
        for at in (1000, 1001, 1009, 1010):
            op.inspect(self.record, at=at, cache=cache, probe_fn=probe)
        self.assertEqual(calls, [42, 42])
        self.assertEqual(self.record, original)

    def test_uninstrumented_legacy_is_explicit(self):
        self.assertEqual(op.inspect({'run_id': 'legacy'}, at=1000)['coverage'], 'NOT_REGISTERED')

    def test_malformed_metadata_degrades_and_blocks(self):
        for malformed in ([], {'bad': None}, {'bad': {}}, {self.operation['id']: dict(self.operation, check_every_seconds='bad')},
                          {self.operation['id']: dict(self.operation, state='WAITING_INPUT')}):
            with self.subTest(malformed=malformed):
                record = {'operations': malformed}
                self.assertTrue(op.guard(record)['invalid'])
                self.assertEqual(op.inspect(record, at=1000)['state'], 'OUTCOME_UNKNOWN')
                with self.assertRaises(ValueError):
                    op.begin(record, kind='other', tool='fixture', label='Invalid', expected_seconds=30, at=1000)

    def test_invalid_future_progress_is_uncertain(self):
        self.operation['last_progress_at'] = op.iso(2000)
        self.assertEqual(op.inspect(self.record, at=1000)['state'], 'OUTCOME_UNKNOWN')

    def test_real_current_process_can_be_identified(self):
        observed = op.probe_process(os.getpid())
        if os.name != 'nt' and observed['state'] == 'NOT_OBSERVED':
            self.skipTest('Sandbox does not expose this process through /proc; native Windows check required')
        self.assertEqual(observed['state'], 'ALIVE')
        self.assertTrue(observed['identity'].startswith(str(os.getpid()) + ':'))

    def test_invalid_pid_cannot_be_bound(self):
        for pid in (-1, 0, True):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                self.begin(pid=pid)


class OperationLifecycleTests(LifecycleTests):
    # Base tests remain in their original module; inherit fixtures only below.
    def register(self):
        operation = op.begin(self.record, kind='test', tool='fixture', label='Fixture', expected_seconds=30, at=1000)
        self.persist()
        return operation

    def test_operation_states_block_finish_and_report(self):
        operation = self.register()
        for state in ('RUNNING', 'WAITING_INPUT', 'FAILED', 'OUTCOME_UNKNOWN'):
            operation.update(state=state, paused_at=op.iso(1000), evidence_ref='fixture:result')
            self.persist()
            with self.subTest(state=state):
                self.assertNotEqual(self.invoke(lc.cmd_finish)[0], 0)
                self.assertNotEqual(self.invoke(lc.cmd_prepare_report, file=str(self.report_path))[0], 0)

    def test_observation_does_not_write_global_progress_or_signal(self):
        operation = self.register()
        self.record['last_progress_at'] = op.iso(1000)
        self.run_path.write_text(json.dumps(self.record), encoding='utf-8')
        self.signal.reset_mock()
        self.invoke(lc.cmd_operation_event, operation=operation['id'], event='observed',
                    evidence_ref='fixture:alive', note='Alive only', expected_seconds=None, resolution=None, pid=None)
        self.assertEqual(self.read()['last_progress_at'], op.iso(1000))
        self.signal.assert_not_called()

    def test_execute_invalidates_previous_verification(self):
        self.invoke(lc.cmd_mark, stage='execute', status='PASS', note='Next stage', evidence_ref='fixture:changes')
        self.assertEqual(self.read()['stages']['verify']['status'], 'PENDING')
        self.assertEqual(self.read()['stages']['quality_gate']['status'], 'PENDING')


class OperationMonitorTests(WatchdogObservationTests):
    def setup_operation(self, expected=300):
        self.marker(run_id='run-a', project_id='project-a')
        path = self.run_record('project-a', 'run-a', 800)
        record = json.loads(path.read_text())
        operation = op.begin(record, kind='other', tool='fixture', label='Fixture', expected_seconds=expected, at=800)
        record['last_progress_at'] = op.iso(800)
        wd.atomic_json(path, record)
        return path, record, operation

    def test_registered_long_operation_overrides_generic_stall(self):
        self.setup_operation()
        self.assertEqual(self.monitor.refresh()['state'], 'WAITING_RESULT')

    def test_registered_deadline_requests_diagnosis(self):
        self.setup_operation(expected=100)
        status = self.monitor.refresh()
        self.assertEqual(status['state'], 'CHECK_REQUIRED')
        self.assertEqual(status['operation_watch']['state'], 'OVERDUE')

    def test_pid_disappearance_overrides_normal_wait(self):
        path, record, operation = self.setup_operation()
        operation['probe'] = {'kind': 'process', 'pid': 42, 'identity': '42:start'}
        wd.atomic_json(path, record)
        with patch.object(op, 'probe_process', return_value={'state': 'NOT_OBSERVED'}):
            self.assertEqual(self.monitor.refresh()['state'], 'UNKNOWN')

    def test_observation_updated_at_cannot_refresh_progress(self):
        path, record, operation = self.setup_operation()
        record.update(updated_at=op.iso(999), operations={})
        wd.atomic_json(path, record)
        self.assertEqual(self.monitor.refresh()['stall_seconds'], 200)

# Do not count inherited baseline tests again.
for cls, base in ((OperationLifecycleTests, LifecycleTests), (OperationMonitorTests, WatchdogObservationTests)):
    for name in base.__dict__:
        if name.startswith('test_'):
            setattr(cls, name, None)
# unittest also discovers imported classes; only expose fixtures via aliases.
del LifecycleTests, WatchdogObservationTests, cls, base

if __name__ == '__main__':
    unittest.main()

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import operation_control as op
import operation_adapters as adapters
import task_lifecycle as lc
import observed_process as runner


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.enterContext(patch.object(adapters, 'PROJECTS_ROOT', self.root))
        self.record = {'run_id': 'fixture'}
        self.operation = op.begin(self.record, kind='plugin', tool='n8n-fixture', label='Controlled', expected_seconds=300, at=1000)
        self.path = self.root/'receipt.json'
        self.binding = {'kind':'n8n', 'path':str(self.path), 'workflow_id':'wf-a','execution_id':'exec-a',
                        'max_age_seconds':120,'allow_historical':False}
        self.operation['observer'] = self.binding
        self.execution = {'id':'exec-a','workflowId':'wf-a','status':'running','startedAt':op.iso(1001),'stoppedAt':None,'waitTill':None}
        self.write()

    def write(self, **changes):
        value = {'schema_version':1,'kind':self.binding['kind'],'run_id':'fixture','operation_id':self.operation['id'],
                 'observed_at':op.iso(1010),'execution':self.execution, **changes}
        self.path.write_text(json.dumps(value),encoding='utf-8')

    def view(self, at=1015): return op.inspect(self.record,at=at)

    def test_running_is_not_progress_and_observer_never_mutates_record(self):
        before=copy.deepcopy(self.record)
        self.assertEqual(self.view()['state'],'WAITING_RESULT')
        self.assertEqual(self.record,before)

    def test_success_is_available_not_task_completion(self):
        self.execution.update(status='success',stoppedAt=op.iso(1012));self.write()
        self.assertEqual(self.view()['state'],'RESULT_AVAILABLE')
        self.assertEqual(op.guard(self.record)['blocked'],[self.operation['id']])

    def test_terminal_failure_variants(self):
        for status in ('error','crashed','canceled'):
            with self.subTest(status=status):
                self.execution.update(status=status,stoppedAt=op.iso(1012));self.write()
                self.assertEqual(self.view()['state'],'FAILED')
                self.assertFalse(self.view()['operations'][0]['automatic_retry'])

    def test_waiting_external_does_not_become_user_waiting(self):
        self.execution.update(status='waiting',waitTill=op.iso(1500));self.write()
        self.assertEqual(self.view()['state'],'WAITING_RESULT')

    def test_fresh_remote_running_does_not_hide_deadline(self):
        self.operation['deadline_at']=op.iso(1011)
        self.assertEqual(self.view()['state'],'OVERDUE')

    def test_stale_snapshot_including_success_is_unknown(self):
        self.execution.update(status='success',stoppedAt=op.iso(1012));self.write()
        self.assertEqual(self.view(at=1131)['state'],'OUTCOME_UNKNOWN')

    def test_status_unknown_and_unrecognized(self):
        for value in ('unknown','finished',''):
            self.execution['status']=value;self.write()
            self.assertEqual(self.view()['state'],'OUTCOME_UNKNOWN')

    def test_mismatched_workflow_or_execution_is_unknown(self):
        for key in ('id','workflowId'):
            self.execution[key]='other';self.write()
            self.assertEqual(self.view()['state'],'OUTCOME_UNKNOWN')
            self.execution[key]={'id':'exec-a','workflowId':'wf-a'}[key]

    def test_missing_and_corrupt_metadata_is_unknown(self):
        for content in ('{','[]','{}','x'*32769):
            self.path.write_text(content)
            self.assertEqual(self.view()['state'],'OUTCOME_UNKNOWN')
        self.path.unlink();self.assertEqual(self.view()['state'],'OUTCOME_UNKNOWN')

    def test_wrong_run_or_operation_is_unknown(self):
        for kwargs in ({'run_id':'other'},{'operation_id':'other'},{'kind':'other'}):
            self.write(**kwargs);self.assertEqual(self.view()['state'],'OUTCOME_UNKNOWN')

    def test_future_or_naive_observation_time_is_unknown(self):
        for value in (op.iso(1100),'2026-01-01T10:00:00',None):
            self.write(observed_at=value);self.assertEqual(self.view()['state'],'OUTCOME_UNKNOWN')

    def test_old_execution_requires_explicit_historical_mode(self):
        self.execution.update(startedAt=op.iso(800),stoppedAt=op.iso(900),status='success');self.write()
        self.assertEqual(self.view()['state'],'OUTCOME_UNKNOWN')
        self.binding['allow_historical']=True
        self.assertEqual(self.view()['state'],'RESULT_AVAILABLE')
        self.assertTrue(self.view()['operations'][0]['result_observation']['historical'])

    def test_inconsistent_terminal_and_active_timestamps(self):
        for status,stop in (('success',None),('success',op.iso(700)),('success',op.iso(2000)),('running',op.iso(1010))):
            self.execution.update(status=status,stoppedAt=stop);self.write()
            self.assertEqual(self.view()['state'],'OUTCOME_UNKNOWN')

    def test_unsafe_binding_path_is_invalid(self):
        for path in (self.root.parent/'outside.json',self.root/'.env.json',self.root/'plain.txt'):
            self.binding['path']=str(path)
            self.assertTrue(op.guard(self.record)['invalid'])

    def test_notification_has_specific_action_no_outbound_delivery(self):
        self.execution.update(status='error',stoppedAt=op.iso(1012));self.write()
        note=adapters.notification(self.view())
        self.assertEqual(note['operation_id'],self.operation['id'])
        self.assertEqual(note['next_action'],'READ_ONLY_RECOVERY')
        self.assertEqual(note['delivery'],'LOCAL_MONITOR_ONLY')
        self.assertFalse(note['automatic_retry'])

    def process_binding(self):
        self.binding={'kind':'process-result','path':str(self.path)}
        self.operation['observer']=self.binding
        self.operation['probe']={'kind':'process','pid':42,'identity':'42:creation'}

    def test_process_receipt_overrides_missing_pid_without_claiming_success(self):
        self.process_binding()
        self.write(started_at=self.operation['started_at'],pid=42,process_identity='42:creation',
                   finished_at=op.iso(1010),exit_code=0,outcome='finished')
        view=op.inspect(self.record,at=1015,probe_fn=lambda _:{'state':'NOT_OBSERVED'})
        self.assertEqual(view['state'],'RESULT_AVAILABLE')
        self.assertEqual(self.operation['state'],'RUNNING')

    def test_process_failure_and_timeout(self):
        self.process_binding()
        for code,outcome,expected in ((3,'finished','FAILED'),(None,'unknown','OUTCOME_UNKNOWN')):
            self.write(started_at=self.operation['started_at'],pid=42,process_identity='42:creation',
                       finished_at=op.iso(1010),exit_code=code,outcome=outcome)
            self.assertEqual(op.inspect(self.record,at=1015,probe_fn=lambda _:{'state':'NOT_OBSERVED'})['state'],expected)

    def test_alive_process_without_receipt_remains_waiting(self):
        self.process_binding();self.path.unlink()
        self.assertEqual(op.inspect(self.record,at=1015,probe_fn=lambda _:{'state':'ALIVE','identity':'42:creation'})['state'],'WAITING_RESULT')
        self.assertEqual(op.inspect(self.record,at=1400,probe_fn=lambda _:{'state':'ALIVE','identity':'42:creation'})['state'],'OVERDUE')

    def test_process_receipt_wrong_identity_is_unknown(self):
        self.process_binding()
        self.write(started_at=self.operation['started_at'],pid=42,process_identity='42:other',
                   finished_at=op.iso(1010),exit_code=0,outcome='finished')
        self.assertEqual(self.view()['state'],'OUTCOME_UNKNOWN')

    def test_observe_n8n_projects_metadata_only_and_does_not_signal_progress(self):
        self.operation.pop('observer')
        self.execution.update(nodeData='PRIVATE_FIXTURE_NOT_TO_STORE',error='PRIVATE_FIXTURE_NOT_TO_STORE')
        source=self.root/'response.json';source.write_text(json.dumps({'execution':self.execution,'data':'PRIVATE_FIXTURE_NOT_TO_STORE'}))
        record_path=self.root/'record.json';record=dict(self.record,last_progress_at=op.iso(1000))
        record_path.write_text(json.dumps(record))
        with patch.object(lc,'load_run',return_value=(record,record_path)),patch.object(lc,'HQ_ROOT',self.root),patch.object(lc,'RUN_ROOT',self.root),patch.object(lc,'watchdog_signal') as signal,contextlib.redirect_stdout(io.StringIO()):
            lc.cmd_observe_n8n(Namespace(run='fixture',operation=self.operation['id'],workflow_id='wf-a',execution_id='exec-a',response_file=str(source),evidence_ref='tool-result:fixture',max_age=120,historical=False))
            snapshot=Path(record['operations'][self.operation['id']]['observer']['path']).read_text()
            self.assertNotIn('PRIVATE_FIXTURE_NOT_TO_STORE',snapshot)
            self.assertEqual(record['last_progress_at'],op.iso(1000))
            signal.assert_not_called()

    def test_receipt_identifiers_cannot_escape_run_directory(self):
        for run_id, operation_id in (('../other', 'ok'), ('run', '../../other'), ('run', 'C:other'), ('', 'op')):
            with self.subTest(run_id=run_id, operation_id=operation_id), self.assertRaises(ValueError):
                adapters.receipt_path(self.root, run_id, operation_id)


class NativeRunnerTests(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self):
        if os.name != 'nt': self.skipTest('Native Windows process identity acceptance')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);hq=root/'hq';hq.mkdir();runs=hq/'runtime/task-runs';path=runs/'p/run.json';path.parent.mkdir(parents=True)
            record={'run_id':'run','operations':{}}
            operation=op.begin(record,kind='terminal',tool='owned-fixture',label='Controlled result',expected_seconds=30)
            path.write_text(json.dumps(record))
            with patch.object(lc,'HQ_ROOT',hq),patch.object(lc,'RUN_ROOT',runs),patch.object(lc,'PROJECTS_ROOT',root),patch.object(adapters,'PROJECTS_ROOT',root),contextlib.redirect_stdout(io.StringIO()):
                args=Namespace(run=str(path),operation=operation['id'],cwd=str(hq),timeout=5,command=[])
                yield args,path,hq

    def test_native_failure_exit_is_not_success(self):
        with self.fixture() as (args,path,hq):
            args.command=[sys.executable,'-c','raise SystemExit(7)']
            runner.run(args)
            view=op.inspect(json.loads(path.read_text()),at=time.time())
            self.assertEqual(view['state'],'FAILED')
            self.assertEqual(view['operations'][0]['result_observation']['exit_code'],7)

    def test_native_timeout_leaves_child_alive_and_prevents_second_effect(self):
        with self.fixture() as (args,path,hq):
            counter=hq/'counter.txt'
            args.timeout=1
            args.command=[sys.executable,'-c',"import time,pathlib;time.sleep(2);pathlib.Path('counter.txt').write_text('once')"]
            children=[];popen=runner.subprocess.Popen
            def remember_child(*a,**kw):
                child=popen(*a,**kw);children.append(child);return child
            with patch.object(runner.subprocess,'Popen',side_effect=remember_child):runner.run(args)
            record=json.loads(path.read_text());operation=record['operations'][args.operation]
            self.assertEqual(op.probe_process(operation['probe']['pid'])['state'],'ALIVE')
            self.assertEqual(op.inspect(record,at=time.time())['state'],'OUTCOME_UNKNOWN')
            with self.assertRaises(ValueError):runner.run(args)
            deadline=time.monotonic()+5
            while not counter.exists() and time.monotonic()<deadline:time.sleep(.05)
            self.assertEqual(counter.read_text(),'once')
            children[0].wait(timeout=5)
            self.assertEqual(op.inspect(json.loads(path.read_text()),at=time.time())['state'],'OUTCOME_UNKNOWN')

    def test_native_concurrent_invocation_launches_only_one_child(self):
        import concurrent.futures
        with self.fixture() as (args,path,hq):
            args.command=[sys.executable,'-c',"import time,pathlib;p=pathlib.Path('counter.txt');p.open('a').write('once\\n');time.sleep(.3)"]
            def attempt():
                try:return runner.run(args)
                except (ValueError,OSError):return 'REFUSED'
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:attempt(),range(2)))
            self.assertEqual(results.count(0),1)
            self.assertEqual(results.count('REFUSED'),1)
            self.assertEqual((hq/'counter.txt').read_text(),'once\n')

    def test_real_local_runner_records_exit_and_blocks_relaunch(self):
        if os.name!='nt': self.skipTest('Native Windows process identity acceptance')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);hq=root/'hq';hq.mkdir();runs=hq/'runtime/task-runs';path=runs/'p/run.json';path.parent.mkdir(parents=True)
            record={'run_id':'run','operations':{}}
            operation=op.begin(record,kind='terminal',tool='owned-fixture',label='Controlled exit',expected_seconds=30)
            path.write_text(json.dumps(record))
            with patch.object(lc,'HQ_ROOT',hq),patch.object(lc,'RUN_ROOT',runs),patch.object(lc,'PROJECTS_ROOT',root),patch.object(adapters,'PROJECTS_ROOT',root),contextlib.redirect_stdout(io.StringIO()):
                args=Namespace(run=str(path),operation=operation['id'],cwd=str(hq),timeout=5,command=['--',sys.executable,'-c','raise SystemExit(0)'])
                self.assertEqual(runner.run(args),0)
                fresh=json.loads(path.read_text())
                self.assertEqual(op.inspect(fresh,at=time.time())['state'],'RESULT_AVAILABLE')
                with self.assertRaises(ValueError): runner.run(args)

if __name__=='__main__':unittest.main()

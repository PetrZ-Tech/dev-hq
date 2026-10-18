import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import quality_commands as policy
import quality_gate as gate


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('prepare.js', 'test.js', 'after.js', 'nested.js', 'safe file.js'):
            (self.root / name).write_text("require('fs').appendFileSync('effects.txt', '" + name + "\\n')")

    def package(self, scripts):
        (self.root / 'package.json').write_text(json.dumps({'scripts': scripts}), encoding='utf-8')

    def plan(self, command='npm test'):
        return policy.compile_plan(self.root, command)

    def check(self, config=None, side_effect=None):
        with patch.object(gate, 'load_quality_config', return_value=config or {}), patch.object(gate, 'run', side_effect=side_effect or (lambda *a, **kw: (0, 'PASS'))) as run, patch.object(policy, 'resolve_argv', side_effect=lambda p, a:a):
            checks = gate.automated_checks(self.root, False)
            return checks, run.call_args_list

    def test_normal_lifecycle_order_and_no_package_manager_process(self):
        self.package({'pretest':'node prepare.js', 'test':'node test.js', 'posttest':'node after.js'})
        checks, calls = self.check()
        self.assertEqual([c.status for c in checks], ['PASS'])
        self.assertEqual([c.args[0] for c in calls], [['node','prepare.js'],['node','test.js'],['node','after.js']])
        self.assertTrue(all(c.kwargs['shell'] is False for c in calls))

    def test_unsafe_pretest_refuses_all_execution(self):
        self.package({'test':'node test.js', 'pretest':'npm run deploy', 'deploy':'node prepare.js'})
        checks, calls = self.check()
        self.assertEqual(checks[0].status, 'FAIL'); self.assertEqual(calls, [])

    def test_unsafe_posttest_is_checked_before_test_runs(self):
        self.package({'test':'node test.js', 'posttest':'curl https://example.invalid'})
        checks, calls = self.check()
        self.assertEqual(checks[0].status, 'FAIL'); self.assertEqual(calls, [])

    def test_nested_scripts_include_nested_hooks(self):
        self.package({'test':'npm run check', 'precheck':'node prepare.js', 'check':'node nested.js', 'postcheck':'node after.js'})
        self.assertEqual([s['argv'][1] for s in self.plan()['steps']], ['prepare.js','nested.js','after.js'])

    def test_nested_unsafe_hook_is_not_hidden_by_alias(self):
        self.package({'test':'npm run check', 'check':'node test.js', 'precheck':'npm run publish'})
        checks, calls = self.check(); self.assertEqual(checks[0].status,'FAIL'); self.assertFalse(calls)

    def test_automatic_hooks_do_not_run_hooks_of_hooks(self):
        self.package({'test':'node test.js', 'pretest':'node prepare.js', 'prepretest':'curl https://example.invalid'})
        self.assertEqual(len(self.plan()['steps']),2)

    def test_explicit_hook_reference_does_check_its_own_hooks(self):
        self.package({'test':'npm run pretest', 'pretest':'node test.js', 'prepretest':'curl https://example.invalid'})
        with self.assertRaises(policy.Refused): self.plan()

    def test_cycles_missing_alias_and_depth_are_refused(self):
        for scripts in ({'test':'npm run test'}, {'test':'npm run missing'},
                        {'test':'npm run a','a':'npm run b','b':'npm test'},
                        {'test':'npm run x0', **{'x'+str(i):'npm run x'+str(i+1) for i in range(20)}}):
            with self.subTest(scripts=scripts):
                self.package(scripts)
                with self.assertRaises(policy.Refused): self.plan()

    def test_shell_constructs_and_unknown_executables_are_refused(self):
        for command in ('node test.js; node after.js', 'node test.js | node after.js',
                        'node test.js || node after.js', 'node test.js & node after.js',
                        'node test.js > result.txt', 'node test.js $(echo x)',
                        'node test.js %COMSPEC%', 'node test.js `echo x`',
                        'node test.js\nnode after.js', 'node test.js "&&" node after.js',
                        'node test.js &&node after.js', 'cmd /c node test.js',
                        'powershell -Command example', 'bash helper.sh', 'curl https://example.invalid',
                        'ENV=value node test.js', 'python -c pass', 'node -e process.exit(0)'):
            with self.subTest(command=command), self.assertRaises(policy.Refused):self.plan(command)

    def test_valid_chain_preserves_explicit_order(self):
        self.assertEqual([s['argv'][1] for s in self.plan('node prepare.js && node test.js')['steps']],['prepare.js','test.js'])

    def test_quoted_path_with_spaces_and_argv_supported(self):
        self.assertEqual(self.plan('node "safe file.js"')['steps'][0]['argv'],['node','safe file.js'])
        self.assertEqual(self.plan([sys.executable,'-m','unittest'])['steps'][0]['argv'],[sys.executable,'-m','unittest'])

    def test_argv_operator_is_never_interpreted_as_chain(self):
        with self.assertRaises(policy.Refused):self.plan(['node','test.js','&&','node','after.js'])

    def test_npx_does_not_install_or_invoke_npx(self):
        self.assertEqual(self.plan('npx --no-install tsc --noEmit')['steps'][0]['argv'],['tsc','--noEmit'])
        for command in ('npx tsc', 'npx --yes tsc', 'npm install', 'npm --prefix ../other run test'):
            with self.subTest(command=command), self.assertRaises(policy.Refused):self.plan(command)

    def test_forwarded_arguments_go_to_main_not_posthook(self):
        self.package({'test':'node test.js','posttest':'node after.js'})
        steps=self.plan('npm run test -- --check')['steps']
        self.assertEqual(steps[0]['argv'],['node','test.js','--check']);self.assertEqual(steps[1]['argv'],['node','after.js'])

    def test_ambiguous_forwarding_is_refused(self):
        for body in ('npm run check', 'node prepare.js && node test.js'):
            self.package({'test':body, 'check':'node test.js', 'postcheck':'node after.js'})
            with self.assertRaises(policy.Refused):self.plan('npm run test -- --check')

    def test_one_time_budget_for_entire_chain(self):
        self.package({'test':'node prepare.js && node test.js'})
        with patch.object(gate.time,'monotonic',side_effect=[0,0,1201]):
            checks,calls=self.check()
        self.assertEqual(len(calls),1);self.assertEqual(checks[-1].status,'FAIL')

    def test_finite_tool_modes_required(self):
        for command in ('vite', 'vite serve', 'vitest', 'tsc --watch', 'jest --watchAll=true',
                        'eslint --fix test.js', 'next dev', 'astro preview', 'ruff format .',
                        'ruff check --fix-only .', 'mypy --install-types .', 'jest -u'):
            with self.subTest(command=command), self.assertRaises(policy.Refused):self.plan(command)
        self.assertEqual(self.plan('vitest run')['steps'][0]['argv'],['vitest','run'])

    def test_entry_point_outside_project_or_missing_refused(self):
        for command in ('node ../other.js','node absent.js','python absent.py'):
            with self.subTest(command=command),self.assertRaises(policy.Refused):self.plan(command)

    def test_changed_metadata_stops_before_next_step(self):
        self.package({'pretest':'node prepare.js','test':'node test.js'})
        def execute(*a,**kw):self.package({'test':'node after.js'});return 0,''
        checks,calls=self.check(side_effect=execute)
        self.assertEqual(len(calls),1);self.assertEqual(checks[-1].status,'FAIL')

    def test_failed_hook_stops_test_posthook_and_other_checks(self):
        self.package({'pretest':'node prepare.js','test':'node test.js','posttest':'node after.js','build':'node nested.js'})
        checks,calls=self.check(side_effect=lambda *a,**kw:(7,'controlled failure'))
        self.assertEqual(len(calls),1);self.assertEqual(checks[-1].status,'FAIL')

    def test_unsafe_npm_never_falls_back_to_python_or_test_js(self):
        (self.root/'tests').mkdir()
        self.package({'test':'npm run deploy'})
        checks,calls=self.check();self.assertEqual(checks[0].status,'FAIL');self.assertFalse(calls)

    def test_configured_npm_is_not_a_bypass(self):
        self.package({'test':'node test.js','pretest':'npm run deploy'})
        checks,calls=self.check({'commands':[{'name':'test','command':'npm test','required':False}],'skip_auto_commands':True})
        self.assertEqual(checks[0].status,'FAIL');self.assertFalse(calls)

    def test_malformed_config_and_package_fail_closed(self):
        for config in ({'commands':{}},{'commands':'x'}, {'skip_auto_commands':'false'},
                       {'commands':[{'name':'test','command':'node test.js','required':'false'}]},
                       {'commands':[{'name':'test','command':[]} ]},
                       {'commands':[{'name':'test','command':'node test.js'}]*2}):
            with self.subTest(config=config):
                checks,_=gate.discover_commands(self.root,config)
                self.assertTrue(any(x.status=='FAIL' for x in _))
        for content in ('{','[]','{"scripts":[]}','{"scripts":{"test":123}}'):
            (self.root/'package.json').write_text(content)
            commands,checks=gate.discover_commands(self.root,{})
            self.assertEqual(commands,[]);self.assertEqual(checks[0].status,'FAIL')

    def test_step_limit(self):
        with self.assertRaises(policy.Refused):self.plan(' && '.join(['node test.js']*129))

    def test_skip_exec_still_validates_hooks_but_executes_nothing(self):
        self.package({'test':'node test.js','posttest':'npm run deploy'})
        with patch.object(gate,'run') as run:
            checks=gate.automated_checks(self.root,True)
        self.assertEqual(checks[0].status,'FAIL');run.assert_not_called()

    def test_actual_node_hooks_execute_once_in_order(self):
        if shutil.which('node') is None:self.skipTest('Node not installed')
        self.package({'pretest':'node prepare.js','test':'node test.js','posttest':'node after.js'})
        checks=gate.automated_checks(self.root,False)
        self.assertEqual([x.status for x in checks],['PASS'])
        self.assertEqual((self.root/'effects.txt').read_text().splitlines(),['prepare.js','test.js','after.js'])

    def test_actual_unsafe_hook_writes_no_marker(self):
        self.package({'pretest':'npm run deploy','test':'node test.js','deploy':'node prepare.js'})
        checks=gate.automated_checks(self.root,False)
        self.assertEqual(checks[0].status,'FAIL');self.assertFalse((self.root/'effects.txt').exists())


if __name__=='__main__':unittest.main()

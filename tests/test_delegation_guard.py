import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import configure_delegation as delegation_config


LEGACY_FILES = ('tool_scope_hook.py', 'session_workflow_hook.py')


class DelegationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='delegation-guard-test-', dir=Path.home())
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir()
        self.core_dir = self.home / 'trusted-legacy' / 'bin'
        self.core_dir.mkdir(parents=True)
        sources = ROOT / 'claude-plugin/workflow-hooks-kit/scripts'
        sys.path.insert(0, str(sources))
        import hook_receipt
        self.hook_receipt = hook_receipt
        core_source = (sources / 'tool_scope_hook.py').read_text()
        core_source = core_source.replace(
            'CLAUDE_STATE = Path.home() / ".claude" / "workflow-hooks-kit"',
            f'CLAUDE_STATE = Path({str(self.home / ".claude/workflow-hooks-kit")!r})', 1)
        legacy_routes = (
            'import delegation_gate\n',
            'DELEGATION_TOOLS = delegation_gate.DELEGATION_TOOLS\n',
            '    if tool in DELEGATION_TOOLS:\n        return delegation_gate.check(sys.modules[__name__], p, state)\n',
            '        if _tool_name(payload) in DELEGATION_TOOLS and _event(payload) == "PreToolUse":\n'
            '            return _deny("PreToolUse", f"Delegation gate unavailable: {type(exc).__name__}; repair task identity/state before retrying.")\n'
        )
        for route in legacy_routes:
            self.assertIn(route, core_source)
            core_source = core_source.replace(route, '', 1)
        (self.core_dir / 'tool_scope_hook.py').write_text(core_source)
        workflow_source = (sources / 'session_workflow_hook.py').read_text()
        workflow_source = workflow_source.replace(
            'STATE = Path.home() / ".codex" / "workflow-hooks-kit" / "state"',
            f'STATE = Path({str(self.home / ".codex/workflow-hooks-kit/state")!r})', 1)
        (self.core_dir / 'session_workflow_hook.py').write_text(workflow_source)

    def tearDown(self):
        self.temp.cleanup()

    def config_path(self, platform):
        return self.home / ('.codex/hooks.json' if platform == 'codex' else '.claude/settings.json')

    def configure(self, platform='codex', uninstall=False):
        return delegation_config.configure(self.home, platform, self.core_dir, uninstall)

    def run_guard(self, payload, platform='codex'):
        folder = '.codex' if platform == 'codex' else '.claude'
        kit = self.home / folder / 'workflow-hooks-kit'
        script = kit / 'bin/delegation-guard/delegation_guard.py'
        args = [sys.executable, '-B', str(script), '--core-dir', str(self.core_dir),
                '--state-dir', str(kit / 'delegation-receipts')]
        if platform == 'claude':
            args.append('--claude')
        env = {**os.environ, 'HOME': str(self.home)}
        result = subprocess.run(args, input=json.dumps(payload), text=True, capture_output=True,
                                timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout or '{}')

    @staticmethod
    def payload(platform='codex', **extra):
        payload = {'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'tool_input': {},
                   'session_id': 'fixture-session', 'cwd': '/tmp'}
        if platform == 'claude':
            payload.update(prompt_id='fixture-prompt')
        else:
            payload['turn_id'] = 'fixture-turn'
        payload.update(extra)
        return payload

    def test_dedicated_cli_invalid_input_denies_without_receipt_or_ledger(self):
        self.configure()
        kit = self.home / '.codex/workflow-hooks-kit'
        script = kit / 'bin/delegation-guard/delegation_guard.py'
        receipt_before = sorted(str(p.relative_to(kit)) for p in kit.rglob('*'))
        for raw in ('{broken', 'null', '[]', '{}',
                    json.dumps({'tool_name': 'Agent'}),
                    json.dumps({'hook_event_name': 'PreToolUse'}),
                    json.dumps({'hook_event_name': ['PreToolUse'], 'tool_name': 'Agent'}),
                    json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 3}),
                    json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': ' Agent'}),
                    'x' * 1_000_001):
            with self.subTest(raw_size=len(raw)):
                result = subprocess.run([sys.executable, '-B', str(script)], input=raw,
                                        text=True, capture_output=True, timeout=10,
                                        env={**os.environ, 'HOME': str(self.home)})
                self.assertEqual(result.returncode, 0, result.stderr)
                decision = json.loads(result.stdout)['hookSpecificOutput']
                self.assertEqual(decision['permissionDecision'], 'deny')
                self.assertNotIn('[wf:', decision['permissionDecisionReason'])
                self.assertLessEqual(len(decision['permissionDecisionReason']), 300)
        unrelated = self.run_guard({'hook_event_name': 'PreToolUse', 'tool_name': 'Read'})
        self.assertEqual(unrelated, {})
        self.assertEqual(receipt_before, sorted(str(p.relative_to(kit)) for p in kit.rglob('*')))
        self.assertFalse((kit / 'state').exists())

    def test_install_keeps_legacy_core_bytes_and_old_matcher(self):
        hashes = {name: hashlib.sha256((self.core_dir / name).read_bytes()).hexdigest() for name in LEGACY_FILES}
        old_matcher = 'Bash|apply_patch|Edit|Write|MultiEdit|NotebookEdit'
        config = {'permissions': {'allow': ['Read']}, 'hooks': {'PreToolUse': [
            {'matcher': old_matcher, 'hooks': [{'type': 'command', 'command': 'echo legacy'}]}]}}
        path = self.config_path('codex')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(config))
        self.configure()
        after = json.loads(path.read_text())
        self.assertEqual(after['permissions'], config['permissions'])
        self.assertEqual(after['hooks']['PreToolUse'][0], config['hooks']['PreToolUse'][0])
        self.assertEqual(hashes, {name: hashlib.sha256((self.core_dir / name).read_bytes()).hexdigest() for name in LEGACY_FILES})
        runtime = path.parent / 'workflow-hooks-kit/bin/delegation-guard'
        self.assertTrue((runtime / 'delegation_gate.py').is_file())
        self.assertTrue((runtime / 'delegation_guard.py').is_file())
        self.assertTrue((runtime / 'hook_receipt.py').is_file())
        self.assertFalse((runtime / 'tool_scope_hook.py').exists())

    def test_unprepared_dispatch_is_denied(self):
        self.configure()
        for tool_name in ('Agent', 'spawn_agent'):
            result = self.run_guard(self.payload(tool_name=tool_name))
            self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_missing_ledger_denial_is_repeatable_and_has_no_ledger_side_effect(self):
        self.configure()
        payload = self.payload()
        state = self.home / '.codex/workflow-hooks-kit/state'
        digest = hashlib.sha256((payload['session_id'] + '\0' + payload['turn_id']).encode()).hexdigest()
        ledger_path = state / (digest + '.json')
        first = self.run_guard(payload)
        before = {str(path.relative_to(state)): path.read_bytes() for path in state.rglob('*') if path.is_file()} if state.exists() else {}
        second = self.run_guard(payload)
        after = {str(path.relative_to(state)): path.read_bytes() for path in state.rglob('*') if path.is_file()} if state.exists() else {}
        reason = first['hookSpecificOutput']['permissionDecisionReason']
        repeat_reason = second['hookSpecificOutput']['permissionDecisionReason']
        self.assertEqual(reason.split(' [wf:', 1)[0], repeat_reason.split(' [wf:', 1)[0])
        self.assertEqual(first['hookSpecificOutput']['permissionDecision'], second['hookSpecificOutput']['permissionDecision'])
        self.assertIn('Do not retry Agent until', reason)
        self.assertFalse(ledger_path.exists())
        self.assertEqual(before, after)

        code = ('import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                'import session_workflow_hook as workflow; workflow.STATE=Path(sys.argv[2]); '
                'print(json.dumps(workflow._stop(json.loads(sys.argv[3]))))')
        result = subprocess.run([sys.executable, '-B', '-c', code, str(self.core_dir), str(state),
                                 json.dumps(payload)], text=True, capture_output=True, timeout=10,
                                env={**os.environ, 'HOME': str(self.home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertFalse(ledger_path.exists())

    def test_real_legacy_plan_api_creates_substantial_plan_that_allows_dispatch(self):
        self.configure()
        payload, ledger_path, before = self._create_ready_plan()
        ledger = json.loads(before)
        self.assertEqual(ledger['task_kind'], 'substantial')
        self.assertEqual(ledger['state'], 'in-progress')
        result = self.run_guard(payload)
        self.assertIn('worker completion is not verified', result['systemMessage'])
        self.assertEqual(ledger_path.read_bytes(), before)

    def test_invalid_and_terminal_ledgers_are_denied_without_mutation(self):
        self.configure()
        for label, mutation, corrupt in (
            ('corrupt', None, True),
            ('boolean schema', lambda ledger: ledger.update(schema_version=True), False),
            ('float schema', lambda ledger: ledger.update(schema_version=1.0), False),
            ('identity mismatch', lambda ledger: ledger.update(session_id='different'), False),
            ('small plan', lambda ledger: ledger.update(task_kind='small'), False),
            ('blocked', lambda ledger: ledger.update(state='blocked', blocker='fixture'), False),
            ('complete', lambda ledger: ledger.update(state='complete'), False),
            ('awaiting user', lambda ledger: ledger.update(state='awaiting-user', question='fixture'), False),
        ):
            with self.subTest(case=label):
                payload = self.payload(session_id='fixture-session-' + label.replace(' ', '-'))
                payload, ledger_path, _ = self._create_ready_plan(payload=payload)
                original = json.loads(ledger_path.read_text())
                if corrupt:
                    ledger_path.write_text('{broken json')
                else:
                    mutation(original)
                    ledger_path.write_text(json.dumps(original))
                before = ledger_path.read_bytes()
                denied = self.run_guard(payload)
                self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
                self.assertEqual(ledger_path.read_bytes(), before)

    def test_plan_created_between_missing_read_and_deny_is_never_overwritten(self):
        payload = self.payload()
        state = self.home / '.codex/workflow-hooks-kit/state'
        plan = {'stages': [{
            'number': 1, 'name': 'race-plan', 'worker_id': 'fixture-worker',
            'worker_model': 'declared-model', 'worker_effort': 'low',
            'model_rationale': 'race fixture', 'inputs': ['fixture'], 'boundaries': ['fixture files'],
            'dependencies': [], 'definition_of_done': 'Saved plan survives a concurrent gate read.',
            'outputs': ['result.txt'], 'qa': {'check': 'Read result.txt', 'expected': 'contains result'}
        }]}
        code = '''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
sys.path.insert(0,sys.argv[5])
import session_workflow_hook as workflow, tool_scope_hook as core, delegation_gate
state=Path(sys.argv[2]); workflow.STATE=state; core.CLAUDE_STATE=state
payload=json.loads(sys.argv[3]); plan=json.loads(sys.argv[4]); real=core._load_existing; once=[False]
root=str(Path(payload["cwd"]).resolve())
core._protected_scope=lambda p,s:(True,root,root)
def raced(p,s):
    path,ledger=real(p,s)
    if ledger is None and not once[0]:
        once[0]=True
        core._apply_api(p,state,root,"plan",plan)
        return path,None
    return path,ledger
core._load_existing=raced
result=delegation_gate.check(core,payload,state)
path=workflow._ledger_path(payload["session_id"],payload["turn_id"])
print(json.dumps({"result":result,"ledger":json.loads(path.read_text()),"bytes":path.read_text()}))
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, str(self.core_dir), str(state),
                                 json.dumps(payload), json.dumps(plan),
                                 str(ROOT / 'claude-plugin/workflow-hooks-kit/scripts')], cwd=ROOT, text=True,
                                capture_output=True, timeout=10, env={**os.environ, 'HOME': str(self.home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        outcome = json.loads(result.stdout)
        self.assertEqual(outcome['result']['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertEqual(outcome['ledger']['task_kind'], 'substantial')
        self.assertEqual(outcome['ledger']['state'], 'in-progress')
        self.assertEqual(outcome['ledger']['stages'][0]['name'], 'race-plan')
        self.assertEqual(json.loads(outcome['bytes']), outcome['ledger'])

    def test_denial_receipt_is_verifiable_and_missing_ids_create_none(self):
        self.configure()
        payload = self.payload()
        denied = self.run_guard(payload)
        reason = denied['hookSpecificOutput']['permissionDecisionReason']
        self.assertLessEqual(len(reason), 300)
        marker = reason.split('[wf:', 1)[1].split(']', 1)[0]
        kit = self.home / '.codex/workflow-hooks-kit'
        runtime = kit / 'bin/delegation-guard'
        version = hashlib.sha256(b''.join((runtime / name).read_bytes() for name in
                                 ('delegation_guard.py', 'delegation_gate.py', 'hook_receipt.py')) +
                                 (self.core_dir / 'tool_scope_hook.py').read_bytes() +
                                 (self.core_dir / 'session_workflow_hook.py').read_bytes()).hexdigest()
        self.hook_receipt.verify(kit / 'delegation-receipts', marker, payload['session_id'],
                                 payload['turn_id'], 'PreToolUse', version, 'failure')
        missing = self.payload()
        missing.pop('turn_id')
        denied_missing = self.run_guard(missing)
        self.assertEqual(denied_missing['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertNotIn('[wf:', denied_missing['hookSpecificOutput']['permissionDecisionReason'])

    def test_receipt_failure_denies_ready_plan_and_unrelated_events_are_noop(self):
        self.configure()
        payload, _, _ = self._create_ready_plan()
        kit = self.home / '.codex/workflow-hooks-kit'
        state = kit / 'delegation-receipts'
        state.rmdir()
        target = self.home / 'unsafe-receipt-target'
        target.mkdir(mode=0o700)
        state.symlink_to(target, target_is_directory=True)
        denied = self.run_guard(payload)
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertNotIn('[wf:', denied['hookSpecificOutput']['permissionDecisionReason'])
        unrelated = {'hook_event_name': 'PreToolUse', 'tool_name': 'Read', 'session_id': 'x'}
        before = set(target.iterdir())
        self.assertEqual(self.run_guard(unrelated), {})
        self.assertEqual(set(target.iterdir()), before)

    def test_guard_keeps_shared_language_receipt_helper_on_install_and_uninstall(self):
        shared = self.home / '.codex/workflow-hooks-kit/bin/hook_receipt.py'
        shared.parent.mkdir(parents=True)
        shared.write_text('# language-owned helper\n')
        before = shared.read_bytes()
        self.configure()
        self.configure()
        self.configure(uninstall=True)
        self.assertEqual(shared.read_bytes(), before)

    def _create_ready_plan(self, platform='codex', payload=None, plan=None):
        state = self.home / ('.claude/workflow-hooks-kit' if platform == 'claude'
                             else '.codex/workflow-hooks-kit/state')
        payload = payload or self.payload(platform, cwd='/tmp')
        plan = plan or {'stages': [{
            'number': 1, 'name': 'guard-check', 'worker_id': 'fixture-worker',
            'worker_model': 'declared-model', 'worker_effort': 'low',
            'model_rationale': 'bounded fixture implementation', 'inputs': ['fixture'],
            'boundaries': ['fixture files'], 'dependencies': [],
            'definition_of_done': 'Guard accepts a valid substantial plan', 'outputs': ['result.txt'],
            'qa': {'check': 'Read result.txt', 'expected': 'contains result'}
        }]}
        code = ('import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                'import session_workflow_hook as workflow, tool_scope_hook as core; '
                'state=Path(sys.argv[2]); workflow.STATE=state; core.CLAUDE_STATE=state; '
                'payload=json.loads(sys.argv[3]); plan=json.loads(sys.argv[4]); '
                'core._apply_api(payload,state,str(Path(payload["cwd"]).resolve()),"plan",plan); '
                'path=workflow._ledger_path(payload["session_id"],payload.get("turn_id") or payload.get("prompt_id")); '
                'workflow._register_active(payload["session_id"],payload.get("turn_id") or payload.get("prompt_id"),path); '
                'print(json.dumps({"path":str(path)}))')
        env = {**os.environ, 'HOME': str(self.home)}
        result = subprocess.run([sys.executable, '-B', '-c', code, str(self.core_dir), str(state),
                                 json.dumps(payload), json.dumps(plan)], cwd=ROOT, text=True,
                                capture_output=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger_path = Path(json.loads(result.stdout)['path'])
        return payload, ledger_path, ledger_path.read_bytes()

    def test_frozen_plan_is_allowed_and_replay_creates_no_dispatch_receipt(self):
        self.configure()
        payload, ledger_path, before = self._create_ready_plan()
        result = self.run_guard(payload)
        self.assertIn('worker completion is not verified', result['systemMessage'])
        marker = result['systemMessage'].split('[wf:', 1)[1].split(']', 1)[0]
        state_dir = self.home / '.codex/workflow-hooks-kit/delegation-receipts'
        runtime = self.home / '.codex/workflow-hooks-kit/bin/delegation-guard'
        version = hashlib.sha256(b''.join((runtime / name).read_bytes() for name in
                                 ('delegation_guard.py', 'delegation_gate.py', 'hook_receipt.py')) +
                                 (self.core_dir / 'tool_scope_hook.py').read_bytes() +
                                 (self.core_dir / 'session_workflow_hook.py').read_bytes()).hexdigest()
        self.hook_receipt.verify(state_dir, marker, payload['session_id'], payload['turn_id'],
                                 'PreToolUse', version, 'success')
        self.assertEqual(ledger_path.read_bytes(), before)
        ledger = json.loads(before)
        self.assertNotIn('dispatch_receipt', ledger)

    def test_claude_prompt_id_is_adapted_and_conflicts_are_denied(self):
        self.configure('claude')
        payload, _, _ = self._create_ready_plan('claude')
        allowed = self.run_guard(payload, 'claude')
        self.assertIn('worker completion is not verified', allowed['systemMessage'])
        conflict = {**payload, 'turn_id': 'different-turn'}
        result = self.run_guard(conflict, 'claude')
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_repeat_install_has_one_guard_group_and_uninstall_preserves_later_changes(self):
        self.configure()
        self.configure()
        path = self.config_path('codex')
        data = json.loads(path.read_text())
        guard_groups = [group for group in data['hooks']['PreToolUse'] if group.get('matcher') == 'Agent|spawn_agent']
        self.assertEqual(len(guard_groups), 1)
        data['new-foreign-setting'] = {'preserve': True}
        data['hooks']['PreToolUse'].append({'matcher': 'Read', 'hooks': [{'type': 'command', 'command': 'echo later'}]})
        path.write_text(json.dumps(data))
        self.configure(uninstall=True)
        after = json.loads(path.read_text())
        self.assertEqual(after['new-foreign-setting'], {'preserve': True})
        self.assertIn({'matcher': 'Read', 'hooks': [{'type': 'command', 'command': 'echo later'}]}, after['hooks']['PreToolUse'])
        self.assertFalse(any(group.get('matcher') == 'Agent|spawn_agent' for group in after['hooks']['PreToolUse']))

    def test_changed_owned_command_is_never_replaced_or_removed(self):
        self.configure()
        path = self.config_path('codex')
        data = json.loads(path.read_text())
        guard = next(group for group in data['hooks']['PreToolUse'] if group.get('matcher') == 'Agent|spawn_agent')
        guard['hooks'][0]['command'] = 'python3 changed.py'
        path.write_text(json.dumps(data))
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.configure()
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.configure(uninstall=True)
        self.assertEqual(path.read_bytes(), before)

    def test_injected_receipt_write_failure_rolls_back_all_owned_changes(self):
        path = self.config_path('codex')
        original = {'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'echo foreign'}]}]}}
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(original))
        real_write_json = delegation_config.write_json
        calls = {'count': 0}
        def fail_receipt(target, data):
            calls['count'] += 1
            if calls['count'] == 2:
                raise OSError('injected receipt failure')
            return real_write_json(target, data)
        with patch.object(delegation_config, 'write_json', side_effect=fail_receipt):
            with self.assertRaises(OSError):
                self.configure()
        self.assertEqual(json.loads(path.read_text()), original)
        kit = path.parent / 'workflow-hooks-kit'
        self.assertFalse((kit / 'delegation-guard-receipt.json').exists())
        self.assertFalse((kit / 'bin/delegation-guard/delegation_gate.py').exists())
        self.assertFalse((kit / 'bin/delegation-guard/delegation_guard.py').exists())
        self.assertTrue(list((kit / 'backups').glob('*hooks.json')))

    def test_core_directory_symlink_is_rejected(self):
        link = self.home / 'core-link'
        link.symlink_to(self.core_dir, target_is_directory=True)
        with self.assertRaises(ValueError):
            delegation_config.configure(self.home, 'codex', link)

    def test_foreign_overlapping_observers_coexist_and_survive_repeat_uninstall(self):
        path = self.config_path('claude')
        for matcher in ('Agent|Task', '.*'):
            with self.subTest(matcher=matcher):
                original = {'hooks': {'PreToolUse': [{'matcher': matcher, 'hooks': [
                    {'type': 'command', 'command': 'python-launcher.sh/run.py/measure.py observer'}]}]}}
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(original))
                self.configure('claude')
                self.configure('claude')
                installed = json.loads(path.read_text())
                self.assertEqual(installed['hooks']['PreToolUse'][0], original['hooks']['PreToolUse'][0])
                self.assertEqual(sum(group.get('matcher') == 'Agent|spawn_agent'
                                     for group in installed['hooks']['PreToolUse']), 1)
                self.configure('claude', uninstall=True)
                self.assertEqual(json.loads(path.read_text()), original)

    def test_repeat_install_uninstall_restores_absent_hooks_structure(self):
        original = {'permissions': {'allow': ['Read']}}
        path = self.config_path('codex')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(original))
        self.configure()
        self.configure()
        self.configure(uninstall=True)
        self.assertEqual(json.loads(path.read_text()), original)

    def test_exact_existing_guard_command_is_refused(self):
        path = self.config_path('codex')
        path.parent.mkdir(parents=True)
        runtime = path.parent / 'workflow-hooks-kit/bin/delegation-guard/delegation_guard.py'
        state = path.parent / 'workflow-hooks-kit/delegation-receipts'
        command = delegation_config._command(runtime, self.core_dir, 'codex') + ' --state-dir ' + str(state)
        path.write_text(json.dumps({'hooks': {'PreToolUse': [{'matcher': 'Agent|Task', 'hooks': [
            {'type': 'command', 'command': command, 'timeout': 10}]}]}}))
        with self.assertRaisesRegex(ValueError, 'command already exists'):
            self.configure()

    def test_core_with_new_guard_is_refused(self):
        source = ROOT / 'claude-plugin/workflow-hooks-kit/scripts/tool_scope_hook.py'
        (self.core_dir / 'tool_scope_hook.py').write_bytes(source.read_bytes())
        with self.assertRaisesRegex(ValueError, 'already covered'):
            self.configure()

    def test_cli_is_runnable_and_runtime_errors_deny_dispatch(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/configure_delegation.py'),
                                 '--platform', 'codex', '--home', str(self.home), '--core-dir', str(self.core_dir)],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['action'], 'installed')
        script = self.home / '.codex/workflow-hooks-kit/bin/delegation-guard/delegation_guard.py'
        payload = self.payload()
        response = subprocess.run([sys.executable, '-B', str(script)], input=json.dumps(payload),
                                  text=True, capture_output=True, timeout=10,
                                  env={**os.environ, 'HOME': str(self.home)})
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(json.loads(response.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')


if __name__ == '__main__':
    unittest.main()

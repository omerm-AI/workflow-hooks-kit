import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'claude-plugin/workflow-hooks-kit/scripts'
CORE_SCRIPT = SCRIPTS / 'tool_scope_hook.py'
PLUGIN_SCRIPT = SCRIPTS / 'plugin_adapter.py'
sys.path.insert(0, str(SCRIPTS))
import hook_receipt
import native_receipt
import plugin_adapter


def core_components():
    return (CORE_SCRIPT, SCRIPTS / 'session_workflow_hook.py', SCRIPTS / 'hook_receipt.py',
            SCRIPTS / 'native_receipt.py', SCRIPTS / 'hygiene_guard.py', SCRIPTS / 'hygiene_adapter.py')


def plugin_components():
    return (PLUGIN_SCRIPT, CORE_SCRIPT, SCRIPTS / 'session_workflow_hook.py',
            SCRIPTS / 'hygiene_guard.py', SCRIPTS / 'hygiene_adapter.py',
            SCRIPTS / 'hook_receipt.py', SCRIPTS / 'native_receipt.py')


def cli(script, payload, home, *args, missing_helper=False):
    wrapper = r'''
import json, pathlib, sys
scripts, script, home, missing = sys.argv[1:5]
sys.path.insert(0, scripts)
from pathlib import Path
Path.home = classmethod(lambda cls: Path(home))
import session_workflow_hook as workflow
workflow.STATE = Path(home) / '.codex/workflow-hooks-kit/state'
import tool_scope_hook as core
import hygiene_adapter, hygiene_guard
core.CLAUDE_STATE = Path(home) / '.claude/workflow-hooks-kit'
if script.endswith('plugin_adapter.py'):
    import plugin_adapter as handler
else:
    handler = core
if missing == '1':
    sys.path.remove(scripts)
    sys.modules.pop('native_receipt', None)
sys.argv = [script, *sys.argv[5:]]
raise SystemExit(handler.main())
'''
    return subprocess.run(
        [sys.executable, '-B', '-c', wrapper, str(SCRIPTS), str(script), str(home),
         '1' if missing_helper else '0', *args], input=json.dumps(payload),
        text=True, capture_output=True, timeout=10,
    )


def receipt_entries(state):
    return sorted(state.glob('batch-*/*.json'))


def verify_single_receipt(state, receipt_path, session, turn, event, version, outcome):
    receipt = json.loads(receipt_path.read_text())
    marker = f"{receipt['batch']}:{receipt['nonce']}"
    verified = hook_receipt.verify(state, marker, session, turn, event, version, outcome)
    with unittest.TestCase().assertRaises(FileNotFoundError):
        hook_receipt.verify(state, marker, session, turn, event, version, outcome)
    return verified


class NativeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-receipt-test-', dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / 'project'
        self.project.mkdir()

    def event(self, event, tool=None, tool_input=None, **extra):
        payload = {'hook_event_name': event, 'session_id': 'receipt-session', 'turn_id': 'receipt-turn'}
        if tool is not None:
            payload.update(tool_name=tool, tool_input=tool_input or {}, cwd=str(self.project))
        return {**payload, **extra}

    def test_core_cli_creates_one_signed_receipt_and_replay_is_rejected(self):
        payload = self.event('PreToolUse', 'Bash', {'command': 'pwd'})
        result = cli(CORE_SCRIPT, payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        state = self.home / '.codex/workflow-hooks-kit/hook-receipts/tool-scope'
        entries = receipt_entries(state)
        self.assertEqual(len(entries), 1)
        version = native_receipt.handler_version('tool-scope-codex-v1', core_components())
        verified = verify_single_receipt(state, entries[0], 'receipt-session', 'receipt-turn',
                                         'PreToolUse', version, 'success')
        self.assertEqual(verified['outcome'], 'success')
        self.assertEqual(len(receipt_entries(state)), 0)

    def test_core_cli_denial_is_signed_as_failure_without_changing_deny_reason(self):
        payload = self.event('PreToolUse', 'Write', {
            'file_path': str(self.project / 'new.txt'), 'content': 'new'
        })
        result = cli(CORE_SCRIPT, payload, self.home)
        output = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertIn('Before editing', output['permissionDecisionReason'])
        state = self.home / '.codex/workflow-hooks-kit/hook-receipts/tool-scope'
        entries = receipt_entries(state)
        self.assertEqual(len(entries), 1)
        version = native_receipt.handler_version('tool-scope-codex-v1', core_components())
        verified = verify_single_receipt(state, entries[0], 'receipt-session', 'receipt-turn',
                                         'PreToolUse', version, 'failure')
        self.assertEqual(verified['outcome'], 'failure')

    def test_plugin_cli_records_one_skipped_dedup_receipt_without_output_changes(self):
        home = self.home
        runtime = home / '.claude/workflow-hooks-kit/bin'
        runtime.mkdir(parents=True)
        for name in ('tool_scope_hook.py', 'session_workflow_hook.py', 'hook_receipt.py', 'native_receipt.py', 'hygiene_guard.py', 'hygiene_adapter.py'):
            shutil.copyfile(SCRIPTS / name, runtime / name)
        expected = 'python3 -B ' + shlex.quote(str(runtime / 'tool_scope_hook.py')) + ' --claude'
        match = 'Bash|apply_patch|Edit|Write|MultiEdit|NotebookEdit|Agent|spawn_agent'
        hooks = {}
        for event in ('UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop'):
            matcher = match if event in {'PreToolUse', 'PostToolUse'} else None
            hooks[event] = [{'matcher': matcher, 'hooks': [{'command': expected}]}]
        settings = home / '.claude/settings.json'
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({'hooks': hooks}))

        self.assertTrue(plugin_adapter.global_adapter_active(home))
        helper = runtime / 'native_receipt.py'
        helper_bytes = helper.read_bytes()
        helper.unlink()
        self.assertFalse(plugin_adapter.global_adapter_active(home))
        helper.write_bytes(helper_bytes)
        helper.write_bytes(helper_bytes + b'\n# changed fixture\n')
        self.assertFalse(plugin_adapter.global_adapter_active(home))
        helper.write_bytes(helper_bytes)
        self.assertTrue(plugin_adapter.global_adapter_active(home))

        payload = self.event('PreToolUse', 'Bash', {'command': 'pwd'})
        result = cli(PLUGIN_SCRIPT, payload, home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        state = home / '.claude/workflow-hooks-kit/hook-receipts/plugin-adapter'
        entries = receipt_entries(state)
        self.assertEqual(len(entries), 1)
        version = native_receipt.handler_version('claude-plugin-adapter-v1', plugin_components())
        verified = verify_single_receipt(state, entries[0], 'receipt-session', 'receipt-turn',
                                         'PreToolUse', version, 'skipped')
        self.assertEqual(verified['outcome'], 'skipped')

    def test_unsafe_receipt_state_denies_known_pretool_but_leaves_conversation_unchanged(self):
        runtime = self.home / '.codex/workflow-hooks-kit'
        runtime.mkdir(parents=True)
        (runtime / 'hook-receipts').symlink_to(self.home / 'outside')

        pretool = self.event('PreToolUse', 'Bash', {'command': 'pwd'})
        denied = cli(CORE_SCRIPT, pretool, self.home)
        self.assertEqual(denied.returncode, 0)
        denied_output = json.loads(denied.stdout)['hookSpecificOutput']
        self.assertEqual(denied_output['permissionDecision'], 'deny')
        self.assertEqual(denied_output['permissionDecisionReason'],
                         'Hook receipt unavailable: OSError; operation denied.')
        self.assertEqual(denied.stderr, 'Native hook receipt unavailable: OSError.\n')

        existing_deny = cli(CORE_SCRIPT, self.event('PreToolUse', 'Write', {
            'file_path': str(self.home / 'outside.txt'), 'content': 'new'
        }), self.home)
        existing_reason = json.loads(existing_deny.stdout)['hookSpecificOutput']['permissionDecisionReason']
        self.assertEqual(existing_reason, 'קובץ היעד מחוץ לתיקיית העבודה; שורשים ביומן אינם מעניקים הרשאה.')
        self.assertNotEqual(existing_reason, denied_output['permissionDecisionReason'])

        chat = cli(CORE_SCRIPT, {'hook_event_name': 'UserPromptSubmit', 'session_id': 'receipt-session',
                                 'turn_id': 'receipt-turn', 'prompt': 'hello'}, self.home)
        self.assertEqual(chat.returncode, 0)
        self.assertEqual(json.loads(chat.stdout), {})
        self.assertEqual(chat.stderr, 'Native hook receipt unavailable: OSError.\n')

    def test_unsafe_receipt_key_denies_known_pretool(self):
        state = self.home / '.codex/workflow-hooks-kit/hook-receipts/tool-scope'
        state.parent.mkdir(parents=True)
        state.parent.chmod(0o700)
        state.mkdir(mode=0o700)
        (state / '.hook-receipt.key').symlink_to(self.home / 'missing-target')
        result = cli(CORE_SCRIPT, self.event('PreToolUse', 'Bash', {'command': 'pwd'}), self.home)
        output = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertEqual(output['permissionDecisionReason'],
                         'Hook receipt unavailable: OSError; operation denied.')
        self.assertEqual(result.stderr, 'Native hook receipt unavailable: OSError.\n')

    def test_missing_plugin_receipt_helper_fails_closed_for_known_pretool(self):
        result = cli(PLUGIN_SCRIPT, self.event('PreToolUse', 'Bash', {'command': 'pwd'}),
                     self.home, missing_helper=True)
        output = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertEqual(output['permissionDecisionReason'],
                         'Hook receipt unavailable: ModuleNotFoundError; operation denied.')
        self.assertEqual(result.stderr, 'Native hook receipt unavailable: ModuleNotFoundError.\n')

    def test_missing_and_conflicting_native_ids_fail_closed_for_known_pretool(self):
        missing = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': 'pwd'},
                   'cwd': str(self.project)}
        absent = cli(CORE_SCRIPT, missing, self.home)
        self.assertEqual(json.loads(absent.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('ValueError', json.loads(absent.stdout)['hookSpecificOutput']['permissionDecisionReason'])

        conflict = self.event('PreToolUse', 'Bash', {'command': 'pwd'}, prompt_id='other-turn')
        rejected = cli(CORE_SCRIPT, conflict, self.home)
        self.assertEqual(json.loads(rejected.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('ValueError', json.loads(rejected.stdout)['hookSpecificOutput']['permissionDecisionReason'])

    def test_handler_identity_and_source_bytes_change_receipt_version(self):
        source = self.home / 'handler.py'
        source.write_text('version one')
        first = native_receipt.handler_version('core-v1', (source,))
        same_components_other_handler = native_receipt.handler_version('plugin-v1', (source,))
        source.write_text('version two')
        changed_source = native_receipt.handler_version('core-v1', (source,))
        self.assertNotEqual(first, same_components_other_handler)
        self.assertNotEqual(first, changed_source)
        state = self.home / '.codex/workflow-hooks-kit/hook-receipts/test-handler'
        marker = native_receipt.create_native(
            state, {'hook_event_name': 'SessionStart', 'session_id': 'version-session'}, 'success', first
        )
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            hook_receipt.verify(state, marker, 'version-session', None, 'SessionStart',
                                changed_source, 'success')

    def test_system_message_is_signed_as_failure_without_changing_context_outcome(self):
        self.assertEqual(native_receipt.outcome_for({'systemMessage': 'handler issue'}), 'failure')
        self.assertEqual(native_receipt.outcome_for({'hookSpecificOutput': {
            'additionalContext': 'normal context'
        }}), 'success')

    def test_invalid_identity_is_rejected_before_receipt_files_are_created(self):
        state = self.home / '.codex/workflow-hooks-kit/hook-receipts/tool-scope'
        version = native_receipt.handler_version('tool-scope-codex-v1', core_components())
        for payload in (
            {'hook_event_name': 'PreToolUse', 'turn_id': 'only-turn'},
            {'hook_event_name': 'PreToolUse', 'session_id': 's', 'prompt_id': 'one', 'turn_id': 'two'},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                native_receipt.create_native(state, payload, 'success', version)
        self.assertFalse(state.exists())


if __name__ == '__main__':
    unittest.main()

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'claude-plugin/workflow-hooks-kit/scripts'
HOOK = SCRIPTS / 'session_workflow_hook.py'
sys.path.insert(0, str(SCRIPTS))
import hook_receipt
import native_receipt


WRAPPER = r'''
import json, sys
from pathlib import Path
script, home, mode = sys.argv[1:4]
home = Path(home)
Path.home = classmethod(lambda cls: home)
sys.path.insert(0, str(Path(script).parent))
import session_workflow_hook as hook
hook.STATE = home / '.codex/workflow-hooks-kit/state'
if mode == 'block':
    hook.run = lambda payload: {'decision': 'block', 'reason': 'existing stop block'}
elif mode == 'system-message':
    hook.run = lambda payload: {'systemMessage': 'existing diagnostic'}
if mode == 'direct':
    print(json.dumps(hook.run(json.load(sys.stdin)), ensure_ascii=False))
else:
    hook.main()
'''


def cli(payload, home, *, script=HOOK, mode='main'):
    return subprocess.run(
        [sys.executable, '-B', '-c', WRAPPER, str(script), str(home), mode],
        input=json.dumps(payload), text=True, capture_output=True, timeout=10,
    )


def receipt_files(state):
    return sorted(state.glob('batch-*/*.json'))


def components(script=HOOK):
    return (script, SCRIPTS / 'hook_receipt.py', SCRIPTS / 'native_receipt.py')


class WorkflowReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workflow-receipt-test-', dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / 'project'
        self.project.mkdir()

    def payload(self, event='UserPromptSubmit', **extra):
        return {
            'hook_event_name': event,
            'session_id': 'synthetic-workflow-session',
            'turn_id': 'synthetic-workflow-turn',
            'cwd': str(self.project),
            'prompt': 'hello',
            **extra,
        }

    def state(self):
        return self.home / '.codex/workflow-hooks-kit/hook-receipts/session-workflow'

    def verify(self, path, *, expected_outcome='skipped', expected_event='UserPromptSubmit'):
        receipt = json.loads(path.read_text())
        marker = f"{receipt['batch']}:{receipt['nonce']}"
        version = native_receipt.handler_version('workflow-codex-v1', components())
        verified = hook_receipt.verify(
            self.state(), marker, 'synthetic-workflow-session', 'synthetic-workflow-turn',
            expected_event, version, expected_outcome,
        )
        with self.assertRaises(FileNotFoundError):
            hook_receipt.verify(
                self.state(), marker, 'synthetic-workflow-session', 'synthetic-workflow-turn',
                expected_event, version, expected_outcome,
            )
        return receipt, verified

    def test_ordinary_prompt_and_stop_remain_empty_and_have_local_receipts(self):
        prompt = cli(self.payload(), self.home)
        self.assertEqual(prompt.returncode, 0, prompt.stderr)
        self.assertEqual(json.loads(prompt.stdout), {})
        entries = receipt_files(self.state())
        self.assertEqual(len(entries), 1)
        receipt, verified = self.verify(entries[0], expected_outcome='skipped')
        self.assertEqual(verified['outcome'], 'skipped')
        self.assertNotIn('additionalContext', json.loads(prompt.stdout))

        stop = cli(self.payload('Stop'), self.home)
        self.assertEqual(stop.returncode, 0, stop.stderr)
        self.assertEqual(json.loads(stop.stdout), {})
        stop_entries = receipt_files(self.state())
        self.assertEqual(len(stop_entries), 1)
        self.verify(stop_entries[0], expected_outcome='skipped', expected_event='Stop')

    def test_direct_run_stays_pure_without_receipt_state(self):
        result = cli(self.payload(), self.home, mode='direct')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertFalse(self.state().exists())

    def test_existing_stop_block_is_preserved_and_signed_as_failure(self):
        result = cli(self.payload('Stop'), self.home, mode='block')
        expected = {'decision': 'block', 'reason': 'existing stop block'}
        self.assertEqual(json.loads(result.stdout), expected)
        entries = receipt_files(self.state())
        self.assertEqual(len(entries), 1)
        receipt = json.loads(entries[0].read_text())
        marker = f"{receipt['batch']}:{receipt['nonce']}"
        version = native_receipt.handler_version('workflow-codex-v1', components())
        verified = hook_receipt.verify(
            self.state(), marker, 'synthetic-workflow-session', 'synthetic-workflow-turn',
            'Stop', version, 'failure',
        )
        self.assertEqual(verified['outcome'], 'failure')

    def test_system_message_is_signed_as_failure_without_output_rewrite(self):
        result = cli(self.payload(), self.home, mode='system-message')
        self.assertEqual(json.loads(result.stdout), {'systemMessage': 'existing diagnostic'})
        receipt = json.loads(receipt_files(self.state())[0].read_text())
        marker = f"{receipt['batch']}:{receipt['nonce']}"
        version = native_receipt.handler_version('workflow-codex-v1', components())
        verified = hook_receipt.verify(
            self.state(), marker, 'synthetic-workflow-session', 'synthetic-workflow-turn',
            'UserPromptSubmit', version, 'failure',
        )
        self.assertEqual(verified['outcome'], 'failure')

    def test_source_version_change_and_replay_are_rejected(self):
        result = cli(self.payload(), self.home)
        self.assertEqual(json.loads(result.stdout), {})
        entries = receipt_files(self.state())
        receipt = json.loads(entries[0].read_text())
        marker = f"{receipt['batch']}:{receipt['nonce']}"
        expected = native_receipt.handler_version('workflow-codex-v1', components())
        changed = self.home / 'session_workflow_hook.py'
        shutil.copyfile(HOOK, changed)
        changed.write_bytes(changed.read_bytes() + b'\n# synthetic version change\n')
        changed_version = native_receipt.handler_version(
            'workflow-codex-v1', components(changed)
        )
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            hook_receipt.verify(self.state(), marker, 'synthetic-workflow-session',
                                'synthetic-workflow-turn', 'UserPromptSubmit',
                                changed_version, 'skipped')
        hook_receipt.verify(self.state(), marker, 'synthetic-workflow-session',
                            'synthetic-workflow-turn', 'UserPromptSubmit', expected, 'skipped')
        with self.assertRaises(FileNotFoundError):
            hook_receipt.verify(self.state(), marker, 'synthetic-workflow-session',
                                'synthetic-workflow-turn', 'UserPromptSubmit', expected, 'skipped')

    def test_unsafe_receipt_path_warns_without_changing_hook_output(self):
        parent = self.home / '.codex/workflow-hooks-kit'
        parent.mkdir(parents=True)
        (parent / 'hook-receipts').symlink_to(self.home / 'outside')
        result = cli(self.payload(), self.home)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertEqual(result.stderr, 'Native hook receipt unavailable: OSError.\n')

    def test_missing_helper_warns_without_changing_hook_output(self):
        isolated = self.home / 'isolated'
        isolated.mkdir()
        shutil.copyfile(HOOK, isolated / HOOK.name)
        result = cli(self.payload(), self.home, script=isolated / HOOK.name)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertEqual(result.stderr, 'Native hook receipt unavailable: ModuleNotFoundError.\n')


if __name__ == '__main__':
    unittest.main()

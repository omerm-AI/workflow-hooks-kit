import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PromptHookTests(unittest.TestCase):
    def test_codex_native_turn_id_and_conflicting_aliases(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'codex-session',
                       'turn_id': 'codex-turn', 'prompt': 'Hello'}
            self.assertEqual(self.run_hook(state, payload), {})
            before = (state / 'mcp-receipts.json').read_bytes()
            payload['prompt_id'] = 'different'
            self.assertIn('systemMessage', self.run_hook(state, payload))
            self.assertEqual((state / 'mcp-receipts.json').read_bytes(), before)

    def run_hook(self, state, payload):
        run = subprocess.run([sys.executable, '-B', str(ROOT / 'learning/prompt_hook.py'),
                              '--state-dir', str(state)], input=json.dumps(payload),
                             text=True, capture_output=True, timeout=5)
        self.assertEqual(run.returncode, 0)
        return json.loads(run.stdout)

    def test_native_payload_stores_receipt_without_prompt_or_path(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'native-session',
                       'prompt_id': 'native-prompt', 'prompt': 'Hello', 'cwd': '/private/example'}
            self.assertEqual(self.run_hook(state, payload), {})
            evidence = (state / 'mcp-receipts.json').read_text()
            self.assertEqual(len(json.loads(evidence)['receipts']), 1)
            self.assertNotIn('Hello', evidence)
            self.assertNotIn('/private/example', evidence)
            self.assertEqual(self.run_hook(state, payload), {})
            self.assertEqual((state / 'mcp-receipts.json').read_text(), evidence)

    def test_agent_skip_and_missing_native_id_are_not_success_receipts(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'native-session',
                       'prompt_id': 'native-prompt', 'agent_id': 'worker', 'prompt': 'remember Fake rule.'}
            self.assertEqual(self.run_hook(state, payload), {})
            self.assertFalse((state / 'mcp-receipts.json').exists())
            del payload['agent_id']
            del payload['prompt_id']
            self.assertIn('systemMessage', self.run_hook(state, payload))
            self.assertFalse((state / 'mcp-receipts.json').exists())


    def test_bounded_diagnostic_records_native_shape_without_caller_values(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'fixture-session',
                       'turn_id': 'fixture-turn', 'prompt': 'fixture private prompt',
                       'cwd': '/private/fixture-path', 'private-key-as-key': 'secret-value'}
            self.assertEqual(self.run_hook(state, payload), {})
            raw = (state / 'last-prompt-hook.json').read_text()
            record = json.loads(raw)
            self.assertLessEqual(len(raw.encode()), 2048)
            self.assertEqual(record['outcome'], 'broker_returned')
            self.assertEqual(record['phase'], 'checkpoint')
            self.assertEqual(record['field_types']['turn_id'], 'str')
            self.assertEqual(record['unknown_key_count'], 1)
            expected = hashlib.sha256(json.dumps('fixture-turn', ensure_ascii=False,
                                                 sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(record['identity_hashes']['turn_id'], expected)
            for value in ('fixture-session', 'fixture-turn', 'fixture private prompt',
                          '/private/fixture-path', 'private-key-as-key', 'secret-value'):
                self.assertNotIn(value, raw)
            payload['agent_id'] = None
            self.assertIn('systemMessage', self.run_hook(state, payload))
            record = json.loads((state / 'last-prompt-hook.json').read_text())
            self.assertEqual(record['outcome'], 'rejected')
            self.assertEqual(record['error_type'], 'LearningError')
            self.assertEqual(record['field_types']['agent_id'], 'NoneType')
            self.assertTrue(record['agent_field_present'])
            self.assertEqual(len(list(state.glob('last-prompt-hook*'))), 1)

    def test_diagnostic_distinguishes_ignored_event_and_missing_id(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            self.assertEqual(self.run_hook(state, {'hook_event_name': 'Stop'}), {})
            record = json.loads((state / 'last-prompt-hook.json').read_text())
            self.assertEqual(record['outcome'], 'ignored_event')
            self.assertFalse((state / 'mcp-receipts.json').exists())
            self.assertIn('systemMessage', self.run_hook(state, {
                'hook_event_name': 'UserPromptSubmit', 'session_id': 'fixture-only'}))
            record = json.loads((state / 'last-prompt-hook.json').read_text())
            self.assertEqual(record['outcome'], 'rejected')
            self.assertEqual(record['phase'], 'checkpoint')
            self.assertEqual(record['error_type'], 'LearningError')
            self.assertFalse((state / 'mcp-receipts.json').exists())

    def test_diagnostic_failure_is_fail_open_and_does_not_follow_symlink(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            base = Path(directory)
            target = base / 'target'
            target.mkdir()
            state = base / 'state'
            state.symlink_to(target, target_is_directory=True)
            self.assertIn('systemMessage', self.run_hook(state, {
                'hook_event_name': 'UserPromptSubmit', 'session_id': 'fixture-session',
                'turn_id': 'fixture-turn', 'prompt': 'Hello'}))
            self.assertEqual(list(target.iterdir()), [])


    def test_material_context_stays_bounded(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            output = self.run_hook(Path(directory) / 'state', {
                'hook_event_name': 'UserPromptSubmit', 'session_id': 'fixture-session',
                'turn_id': 'fixture-material', 'prompt': 'Build a fixture example'})
            context = output['hookSpecificOutput']['additionalContext']
            self.assertLessEqual(len(context), 25)

    def test_malformed_and_oversized_input_have_metadata_only_failure(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            for raw, phase, error_type in (('{private-not-json', 'decode', 'JSONDecodeError'),
                                           ('x' * 32769, 'input', 'ValueError')):
                run = subprocess.run([sys.executable, '-B', str(ROOT / 'learning/prompt_hook.py'),
                                      '--state-dir', str(state)], input=raw, text=True,
                                     capture_output=True, timeout=5)
                self.assertEqual(run.returncode, 0)
                self.assertIn('systemMessage', json.loads(run.stdout))
                record_text = (state / 'last-prompt-hook.json').read_text()
                record = json.loads(record_text)
                self.assertEqual(record['phase'], phase)
                self.assertEqual(record['error_type'], error_type)
                self.assertNotIn('private-not-json', record_text)
                self.assertFalse((state / 'mcp-receipts.json').exists())

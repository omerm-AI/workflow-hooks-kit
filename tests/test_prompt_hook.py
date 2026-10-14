import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PromptHookTests(unittest.TestCase):
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

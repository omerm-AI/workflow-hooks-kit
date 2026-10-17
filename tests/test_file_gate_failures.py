import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'claude-plugin/workflow-hooks-kit/scripts'
sys.path.insert(0, str(SCRIPTS))
import tool_scope_hook as core
import session_workflow_hook as workflow


class FileGateFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='file-gate-failure-', dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / 'project'
        self.project.mkdir()
        self.old_state, self.old_claude_state = workflow.STATE, core.CLAUDE_STATE
        workflow.STATE = self.home / 'state'
        core.CLAUDE_STATE = self.home / 'claude-state'
        self.addCleanup(self.restore_state)

    def restore_state(self):
        workflow.STATE, core.CLAUDE_STATE = self.old_state, self.old_claude_state

    def payload(self, event, tool=None, tool_input=None, **extra):
        result = {
            'hook_event_name': event,
            'session_id': 'file-gate-session',
            'turn_id': 'file-gate-turn',
            'cwd': str(self.project),
        }
        if tool is not None:
            result.update(tool_name=tool, tool_input=tool_input or {})
        return {**result, **extra}

    def assert_denied_with_type_only_reason(self, result, error_type):
        output = result['hookSpecificOutput']
        self.assertEqual(output['permissionDecision'], 'deny')
        reason = output['permissionDecisionReason']
        self.assertIn(error_type, reason)
        self.assertLessEqual(len(reason), 300)
        self.assertNotIn('private fixture detail', reason)

    def test_valid_write_denies_when_ledger_create_or_lock_fails_in_both_runtimes(self):
        target = str(self.project / 'new.txt')
        write = self.payload('PreToolUse', 'Write', {'file_path': target, 'content': 'new'})
        failures = (
            ('ledger create', patch.object(core, '_ensure_ledger', side_effect=OSError('private fixture detail')), 'OSError'),
            ('ledger lock timeout', patch.object(core, '_ledger_lock', side_effect=TimeoutError('private fixture detail')), 'TimeoutError'),
        )
        for claude in (False, True):
            for label, failure, error_type in failures:
                with self.subTest(claude=claude, failure=label), failure:
                    result = core.run(write, claude=claude)
                    self.assert_denied_with_type_only_reason(result, error_type)

    def test_all_known_edit_tools_and_bash_deny_internal_pretool_errors(self):
        inputs = {
            'Edit': {'file_path': str(self.project / 'file.txt')},
            'Write': {'file_path': str(self.project / 'file.txt')},
            'apply_patch': {'command': '*** Begin Patch\n*** Add File: file.txt\n+text\n*** End Patch'},
            'NotebookEdit': {'notebook_path': str(self.project / 'file.ipynb')},
            'MultiEdit': {'file_path': str(self.project / 'file.txt')},
            'Bash': {'command': 'cat file.txt'},
        }
        for claude in (False, True):
            for tool, tool_input in inputs.items():
                with self.subTest(claude=claude, tool=tool), patch.object(
                    core, '_pre', side_effect=RuntimeError('private fixture detail')
                ):
                    result = core.run(self.payload('PreToolUse', tool, tool_input), claude=claude)
                    self.assert_denied_with_type_only_reason(result, 'RuntimeError')

    def test_existing_sentinel_and_delegation_exception_responses_are_preserved(self):
        cases = (
            ('Bash', {'command': "workflow-ledger plan '{}'"}, 'Ledger command intercepted; handler error: RuntimeError.'),
            ('Agent', {'description': 'delegate'}, 'Delegation gate unavailable: RuntimeError;'),
        )
        for tool, tool_input, expected in cases:
            with self.subTest(tool=tool), patch.object(
                core, '_pre', side_effect=RuntimeError('private fixture detail')
            ):
                result = core.run(self.payload('PreToolUse', tool, tool_input))
                self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')
                reason = result['hookSpecificOutput']['permissionDecisionReason']
                self.assertIn(expected, reason)
                self.assertNotIn('private fixture detail', reason)

    def test_normal_readonly_and_conversation_paths_remain_noops(self):
        self.assertEqual(core.run(self.payload('PreToolUse', 'Read', {'file_path': str(self.project / 'file.txt')})), {})
        self.assertEqual(core.run(self.payload('PreToolUse', 'Bash', {'command': 'pwd'})), {})
        self.assertEqual(core.run(self.payload('UserPromptSubmit', prompt='hello')), {})


if __name__ == '__main__':
    unittest.main()

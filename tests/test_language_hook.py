import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'claude-plugin/workflow-hooks-kit/scripts/response_language_hook.py'
CONFIG = ROOT / 'tools/configure_language.py'
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(HOOK.parent))
import configure_language as language_config
import hook_receipt


class LanguageHookTests(unittest.TestCase):
    def run_hook(self, payload, language='he', *extra):
        args = [sys.executable, '-B', str(HOOK)]
        if language is not None:
            args += ['--language', language]
        args += list(extra)
        result = subprocess.run(args, input=payload, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout or '{}')

    def test_neutral_prompt_gets_configured_hebrew_directive(self):
        result = self.run_hook(json.dumps({'hook_event_name': 'UserPromptSubmit', 'prompt': 'What time is it?'}))
        context = result['hookSpecificOutput']['additionalContext']
        self.assertIn('עברית', context)
        self.assertLessEqual(len(context), 120)
        self.assertIn('באנגלית', context)
        self.assertNotRegex(context, r'\[wf:[^]]+\]')

    def test_english_and_session_start_are_supported(self):
        for event in ('UserPromptSubmit', 'SessionStart'):
            result = self.run_hook(json.dumps({'hook_event_name': event}), 'en')
            self.assertIn('English', result['hookSpecificOutput']['additionalContext'])

    def test_disabled_unknown_nested_and_no_invocation_emit_nothing(self):
        payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'prompt': 'Hello'})
        self.assertEqual(self.run_hook(payload, None), {})
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            disabled_state = Path(directory) / 'state'
            self.assertEqual(self.run_hook(payload, None, '--state-dir', str(disabled_state)), {})
            self.assertFalse(disabled_state.exists())
        self.assertEqual(self.run_hook(json.dumps({'hook_event_name': 'Stop'})), {})
        self.assertEqual(self.run_hook(json.dumps({'hook_event_name': 'UserPromptSubmit', 'agent_id': 'nested'})), {})
        result = subprocess.run([sys.executable, '-B', str(HOOK)], input=payload,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout or '{}'), {})

    def test_bad_language_and_malformed_or_oversized_input_fail_open(self):
        for raw in ('{broken', 'x' * 32769, json.dumps({'hook_event_name': 'UserPromptSubmit', 'agent_id': []})):
            result = self.run_hook(raw)
            self.assertEqual(result, {})
        result = subprocess.run([sys.executable, '-B', str(HOOK), '--language', 'xx'], input='{}',
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout or '{}'), {})

    def test_signed_marker_verifies_event_session_turn_and_combined_version(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'session-real',
                       'prompt_id': 'turn-real', 'prompt': 'private prompt'}
            result = self.run_hook(json.dumps(payload), 'he', '--state-dir', str(state))
            context = result['hookSpecificOutput']['additionalContext']
            self.assertLessEqual(len(context), 120)
            marker_match = re.search(r'\[wf:([0-9a-f]{16}:[0-9a-f]{32})\]', context)
            self.assertIsNotNone(marker_match)
            marker = marker_match.group(1)
            version = hashlib.sha256(HOOK.read_bytes() + (HOOK.parent / 'hook_receipt.py').read_bytes()).hexdigest()
            base_expectations = {'expected_session_id': 'session-real', 'expected_turn_id': 'turn-real',
                                 'event': 'UserPromptSubmit', 'hook_version': version,
                                 'expected_outcome': 'success', 'consume': False}
            for identity in ({'expected_session_id': 'other'}, {'expected_turn_id': 'other'},
                             {'event': 'SessionStart'}, {'hook_version': 'wrong-version'}):
                with self.subTest(identity=identity), self.assertRaises(ValueError):
                    hook_receipt.verify(state, marker, **{**base_expectations, **identity})
            receipt = hook_receipt.verify(state, marker, 'session-real', 'turn-real',
                                          'UserPromptSubmit', version, 'success')
            self.assertEqual(receipt['outcome'], 'success')

    def test_session_start_signed_marker_accepts_missing_turn_as_null(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            result = self.run_hook(json.dumps({'hook_event_name': 'SessionStart', 'session_id': 'session-start'}),
                                   'en', '--state-dir', str(state))
            context = result['hookSpecificOutput']['additionalContext']
            self.assertLessEqual(len(context), 120)
            marker = re.search(r'\[wf:([0-9a-f]{16}:[0-9a-f]{32})\]', context).group(1)
            version = hashlib.sha256(HOOK.read_bytes() + (HOOK.parent / 'hook_receipt.py').read_bytes()).hexdigest()
            receipt = hook_receipt.verify(state, marker, 'session-start', None, 'SessionStart',
                                          version, 'success')
            self.assertIsNone(receipt['turnHash'])

    def test_receipt_failure_emits_directive_and_unavailable_message_without_marker(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            base = Path(directory)
            target = base / 'target'
            target.mkdir()
            state = base / 'state-link'
            state.symlink_to(target, target_is_directory=True)
            result = self.run_hook(json.dumps({'hook_event_name': 'UserPromptSubmit',
                                               'session_id': 'session', 'prompt_id': 'turn'}),
                                   'he', '--state-dir', str(state))
            self.assertIn('עברית', result['hookSpecificOutput']['additionalContext'])
            self.assertNotRegex(result['hookSpecificOutput']['additionalContext'], r'\[wf:[^]]+\]')
            self.assertIn('receipt unavailable', result['systemMessage'].lower())
            self.assertNotIn('success', json.dumps(result).lower())
            self.assertEqual(list(target.iterdir()), [])

    def test_optional_diagnostic_contains_only_hashes_and_event_metadata(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            prompt = 'private prompt text'
            self.run_hook(json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 'secret-session',
                                      'prompt': prompt}), 'he', '--state-dir', str(state))
            raw = (state / 'response-language.json').read_text()
            self.assertNotIn(prompt, raw)
            self.assertNotIn('secret-session', raw)
            data = json.loads(raw)
            self.assertEqual(data['event'], 'UserPromptSubmit')
            self.assertIn('session_id', data['identity_hashes'])
            self.assertIn('directive_hash', data)
            self.assertIn('hook_version_hash', data)


class ConfigureLanguageTests(unittest.TestCase):
    def run_config(self, home, *args):
        result = subprocess.run([sys.executable, '-B', str(CONFIG), '--home', str(home), *args],
                                text=True, capture_output=True, timeout=10)
        return result

    def test_install_is_idempotent_and_preserves_foreign_settings(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            claude = home / '.claude'
            claude.mkdir()
            settings = claude / 'settings.json'
            foreign = {'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo foreign'}]}]},
                       'permissions': {'allow': ['Read']}, 'custom': 7}
            original_bytes = json.dumps(foreign).encode()
            settings.write_bytes(original_bytes)
            for _ in range(2):
                result = self.run_config(home, '--language', 'he')
                self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(settings.read_text())
            self.assertEqual(data['permissions'], foreign['permissions'])
            self.assertEqual(data['custom'], 7)
            self.assertEqual(len(data['hooks']['SessionStart']), 2)
            self.assertEqual(len(data['hooks']['UserPromptSubmit']), 1)
            backups = list((claude / 'workflow-hooks-kit/backups').glob('*-settings.json'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original_bytes)
            self.assertTrue((claude / 'workflow-hooks-kit/bin/response_language_hook.py').is_file())
            installed_helper = claude / 'workflow-hooks-kit/bin/hook_receipt.py'
            self.assertEqual(installed_helper.read_bytes(), (HOOK.parent / 'hook_receipt.py').read_bytes())
            self.assertTrue(all('--state-dir' in group['hooks'][0]['command']
                                and str(claude / 'workflow-hooks-kit/language-receipts')
                                in group['hooks'][0]['command']
                                for event in ('SessionStart', 'UserPromptSubmit')
                                for group in data['hooks'][event] if 'workflow-hooks-kit/bin/' in group['hooks'][0]['command']))
            changed = self.run_config(home, '--language', 'en')
            self.assertEqual(changed.returncode, 0, changed.stderr)
            updated = json.loads(settings.read_text())
            self.assertEqual(len(updated['hooks']['SessionStart']), 2)
            self.assertEqual(len(updated['hooks']['UserPromptSubmit']), 1)
            owned = updated['hooks']['SessionStart'][1]['hooks'][0]['command']
            self.assertIn('--language en --state-dir', owned)

    def test_uninstall_after_foreign_edits_removes_only_owned_hooks(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            self.assertEqual(self.run_config(home, '--language', 'he').returncode, 0)
            settings = home / '.claude/settings.json'
            data = json.loads(settings.read_text())
            data['permissions'] = {'deny': ['Bash']}
            data['hooks']['UserPromptSubmit'].append({'hooks': [{'type': 'command', 'command': 'echo later'}]})
            settings.write_text(json.dumps(data))
            result = self.run_config(home, '--uninstall')
            self.assertEqual(result.returncode, 0, result.stderr)
            after = json.loads(settings.read_text())
            self.assertEqual(after['permissions'], {'deny': ['Bash']})
            self.assertEqual(after['hooks']['UserPromptSubmit'], [{'hooks': [{'type': 'command', 'command': 'echo later'}]}])
            self.assertNotIn('SessionStart', after['hooks'])

    def test_changed_owned_handler_refuses_before_runtime_update(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            installed = self.run_config(home, '--language', 'he')
            self.assertEqual(installed.returncode, 0, installed.stderr)
            claude = home / '.claude'
            settings = claude / 'settings.json'
            data = json.loads(settings.read_text())
            data['hooks']['UserPromptSubmit'][0]['hooks'][0]['command'] = 'echo edited by user'
            settings.write_text(json.dumps(data))
            runtime = claude / 'workflow-hooks-kit/bin/response_language_hook.py'
            runtime.write_bytes(b'previous approved runtime')
            receipt_path = claude / 'workflow-hooks-kit/response-language-receipt.json'
            receipt = json.loads(receipt_path.read_text())
            receipt['runtime_hash'] = hashlib.sha256(runtime.read_bytes()).hexdigest()
            receipt_path.write_text(json.dumps(receipt))
            before_config = settings.read_bytes()
            before_runtime = runtime.read_bytes()
            source = home / 'replacement-source.py'
            source.write_bytes(b'new runtime version')
            with patch.object(language_config, 'SOURCE', source):
                with self.assertRaises(ValueError):
                    language_config.configure(home, 'en', False)
            self.assertEqual(settings.read_bytes(), before_config)
            self.assertEqual(runtime.read_bytes(), before_runtime)

    def test_legacy_runtime_hash_receipt_remains_updatable(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            first = self.run_config(home, '--language', 'he')
            self.assertEqual(first.returncode, 0, first.stderr)
            claude = home / '.claude'
            receipt_path = claude / 'workflow-hooks-kit/response-language-receipt.json'
            receipt = json.loads(receipt_path.read_text())
            receipt.pop('runtime_hashes')
            (claude / 'workflow-hooks-kit/bin/hook_receipt.py').unlink()
            receipt_path.write_text(json.dumps(receipt))
            updated = self.run_config(home, '--language', 'en')
            self.assertEqual(updated.returncode, 0, updated.stderr)
            saved = json.loads(receipt_path.read_text())
            self.assertEqual(set(saved['runtime_hashes']), {
                'response_language_hook.py', 'hook_receipt.py'})

    def test_unowned_helper_collision_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            claude = home / '.claude'
            claude.mkdir()
            settings = claude / 'settings.json'
            original_settings = b'{"permissions":{"allow":["Read"]}}\n'
            settings.write_bytes(original_settings)
            foreign_helper = claude / 'workflow-hooks-kit/bin/hook_receipt.py'
            foreign_helper.parent.mkdir(parents=True)
            original_helper = b'# unrelated user helper\n'
            foreign_helper.write_bytes(original_helper)
            result = self.run_config(home, '--language', 'he')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(settings.read_bytes(), original_settings)
            self.assertEqual(foreign_helper.read_bytes(), original_helper)
            self.assertFalse((foreign_helper.parent / 'response_language_hook.py').exists())

    def test_runtime_copy_failure_leaves_settings_unchanged(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            claude = home / '.claude'
            claude.mkdir()
            settings = claude / 'settings.json'
            original = b'{"permissions":{"allow":["Read"]}}\n'
            settings.write_bytes(original)
            destination = claude / 'workflow-hooks-kit/bin/response_language_hook.py'
            destination.mkdir(parents=True)
            result = self.run_config(home, '--language', 'he')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(settings.read_bytes(), original)
            self.assertFalse((claude / 'workflow-hooks-kit/response-language-receipt.json').exists())

    def test_receipt_write_failure_rolls_back_and_retry_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            claude = home / '.claude'
            claude.mkdir()
            settings = claude / 'settings.json'
            original = b'{"permissions":{"allow":["Read"]}}\n'
            settings.write_bytes(original)
            receipt = claude / 'workflow-hooks-kit/response-language-receipt.json'
            real_write_json = language_config.write_json

            def fail_receipt(path, data):
                result = real_write_json(path, data)
                if path == receipt:
                    raise OSError('injected receipt write failure')
                return result

            with patch.object(language_config, 'write_json', side_effect=fail_receipt):
                with self.assertRaises(OSError):
                    language_config.configure(home, 'he', False)
            runtime = claude / 'workflow-hooks-kit/bin/response_language_hook.py'
            self.assertEqual(settings.read_bytes(), original)
            self.assertFalse(runtime.exists())
            self.assertFalse((claude / 'workflow-hooks-kit/bin/hook_receipt.py').exists())
            self.assertFalse(receipt.exists())
            backups = list((claude / 'workflow-hooks-kit/backups').glob('*-settings.json'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            retried = self.run_config(home, '--language', 'he')
            self.assertEqual(retried.returncode, 0, retried.stderr)
            installed = json.loads(settings.read_text())
            self.assertEqual(len(installed['hooks']['SessionStart']), 1)
            self.assertEqual(len(installed['hooks']['UserPromptSubmit']), 1)

    def test_symlink_config_and_nonregular_config_refuse(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            claude = home / '.claude'
            claude.mkdir()
            target = home / 'real.json'
            target.write_text('{}')
            settings = claude / 'settings.json'
            settings.symlink_to(target)
            result = self.run_config(home, '--language', 'he')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_text(), '{}')
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            claude = home / '.claude'
            claude.mkdir()
            (claude / 'settings.json').mkdir()
            result = self.run_config(home, '--language', 'he')
            self.assertNotEqual(result.returncode, 0)

    def test_oversized_config_refuses_without_mutation(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            home = Path(directory)
            claude = home / '.claude'
            claude.mkdir()
            settings = claude / 'settings.json'
            original = b' ' * 4_000_001
            settings.write_bytes(original)
            result = self.run_config(home, '--language', 'he')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(settings.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()

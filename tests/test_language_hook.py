import hashlib
import concurrent.futures
import json
import os
import re
import stat
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
import session_workflow_hook as workflow_hook


class LanguageHookTests(unittest.TestCase):
    def run_hook(self, payload, language='he', *extra):
        args = [sys.executable, '-B', str(HOOK)]
        if language is not None:
            args += ['--language', language]
        args += list(extra)
        result = subprocess.run(args, input=payload, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout or '{}')

    def _receipt_version(self):
        return hashlib.sha256(HOOK.read_bytes() + (HOOK.parent / 'hook_receipt.py').read_bytes()).hexdigest()

    def _assert_has_marker(self, result):
        context = result['hookSpecificOutput']['additionalContext']
        match = re.search(r'\[wf:([0-9a-f]{16}:[0-9a-f]{32})\]', context)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_session_bootstrap_skips_later_prompt_but_restart_reemits(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            start = self.run_hook(json.dumps({'hook_event_name': 'SessionStart', 'session_id': 'boot-session',
                                              'source': 'startup'}),
                                  'he', '--state-dir', str(state))
            marker = self._assert_has_marker(start)
            hook_receipt.verify(state, marker, 'boot-session', None, 'SessionStart',
                                self._receipt_version(), 'success')
            cache_path = next(state.glob('language-session-*.json'))
            cache = json.loads(cache_path.read_text())
            self.assertNotIn('boot-session', cache_path.read_text())
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(cache_path.stat().st_mode), 0o600)
            self.assertLessEqual(cache_path.stat().st_size, 512)
            self.assertEqual(cache['session_hash'], hashlib.sha256(b'boot-session').hexdigest())
            skipped = self.run_hook(json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 'boot-session',
                                                'prompt_id': 'prompt-1', 'prompt': 'Hello'}),
                                    'he', '--state-dir', str(state))
            self.assertEqual(skipped, {})
            skipped_path = next(path for path in state.glob('batch-*/**/*.json')
                                if json.loads(path.read_text())['outcome'] == 'skipped')
            skipped_marker = skipped_path.parent.name.removeprefix('batch-') + ':' + skipped_path.stem
            hook_receipt.verify(state, skipped_marker, 'boot-session', 'prompt-1', 'UserPromptSubmit',
                                self._receipt_version(), 'skipped')
            resumed = self.run_hook(json.dumps({'hook_event_name': 'SessionStart', 'session_id': 'boot-session',
                                                'source': 'compact'}),
                                     'he', '--state-dir', str(state))
            self._assert_has_marker(resumed)

    def test_skipped_receipt_failure_is_reported_without_context_and_retries(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            self._assert_has_marker(self.run_hook(json.dumps({
                'hook_event_name': 'SessionStart', 'session_id': 'receipt-retry',
            }), 'he', '--state-dir', str(state)))
            cache_path = next(state.glob('language-session-*.json'))
            cache_before = cache_path.read_bytes()
            key_path = state / '.hook-receipt.key'
            os.chmod(key_path, 0o644)
            failed = self.run_hook(json.dumps({
                'hook_event_name': 'UserPromptSubmit', 'session_id': 'receipt-retry',
                'prompt_id': 'failed-receipt', 'prompt': 'Hello',
            }), 'he', '--state-dir', str(state))
            self.assertIn('systemMessage', failed)
            self.assertIn('cached response-language receipt unavailable', failed['systemMessage'].lower())
            self.assertNotIn('hookSpecificOutput', failed)
            self.assertNotRegex(json.dumps(failed), r'\[wf:[^]]+\]')
            self.assertEqual(cache_path.read_bytes(), cache_before)
            os.chmod(key_path, 0o600)
            recovered = self.run_hook(json.dumps({
                'hook_event_name': 'UserPromptSubmit', 'session_id': 'receipt-retry',
                'prompt_id': 'recovered-receipt', 'prompt': 'Hello',
            }), 'he', '--state-dir', str(state))
            self.assertEqual(recovered, {})
            skipped_path = next(path for path in state.glob('batch-*/**/*.json')
                                if json.loads(path.read_text())['outcome'] == 'skipped')
            marker = skipped_path.parent.name.removeprefix('batch-') + ':' + skipped_path.stem
            hook_receipt.verify(state, marker, 'receipt-retry', 'recovered-receipt',
                                'UserPromptSubmit', self._receipt_version(), 'skipped')

    def test_old_session_gets_one_prompt_bootstrap_and_sessions_are_independent(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            def submit(session, prompt):
                return self.run_hook(json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': session,
                                                 'prompt_id': prompt, 'prompt': 'Hello'}),
                                     'he', '--state-dir', str(state))
            first_a = submit('old-a', 'a1')
            self._assert_has_marker(first_a)
            self.assertEqual(submit('old-a', 'a2'), {})
            first_b = submit('old-b', 'b1')
            self._assert_has_marker(first_b)
            self.assertEqual(submit('old-b', 'b2'), {})

    def test_language_or_version_change_refreshes_once(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            def submit(language, turn):
                return self.run_hook(json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 'refresh',
                                                 'prompt_id': turn, 'prompt': 'Hello'}),
                                     language, '--state-dir', str(state))
            self._assert_has_marker(submit('he', 'he-bootstrap'))
            self._assert_has_marker(submit('en', 'en-bootstrap'))
            self.assertEqual(submit('en', 'en-skip'), {})
            cache = next(state.glob('language-session-*.json'))
            data = json.loads(cache.read_text())
            data['version_hash'] = 'stale-version'
            cache.write_text(json.dumps(data))
            self._assert_has_marker(submit('en', 'version-refresh'))
            self.assertEqual(submit('en', 'version-skip'), {})

    def test_concurrent_prompts_emit_at_most_one_and_cache_symlink_never_fakes_skip(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            base = Path(directory)
            state = base / 'state'
            payloads = [json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 'concurrent',
                                    'prompt_id': f'turn-{index}', 'prompt': 'Hello'}) for index in range(8)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda p: self.run_hook(p, 'he', '--state-dir', str(state)), payloads))
            self.assertEqual(sum(bool(result) for result in results), 1)
            self.assertEqual(sum('hookSpecificOutput' in result for result in results), 1)

            other_state = base / 'other-state'
            other_state.mkdir(mode=0o700)
            session_hash = hashlib.sha256(b'cache-failure').hexdigest()
            target = base / 'foreign-cache'
            target_bytes = b'{"version_hash":"current"}'
            target.write_bytes(target_bytes)
            (other_state / f'language-session-{session_hash}.json').symlink_to(target)
            failure_payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 'cache-failure',
                                          'prompt_id': 'cache-failure-turn', 'prompt': 'Hello'})
            emitted = self.run_hook(failure_payload, 'he', '--state-dir', str(other_state))
            self._assert_has_marker(emitted)
            self.assertEqual(target.read_bytes(), target_bytes)

    def test_cache_lock_failure_and_missing_turn_never_suppress_directive(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            base = Path(directory)
            state = base / 'state'
            first_payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 'lock-session',
                                        'prompt_id': 'first', 'prompt': 'Hello'})
            self._assert_has_marker(self.run_hook(first_payload, 'he', '--state-dir', str(state)))
            lock_path = state / '.language-cache.lock'
            lock_path.unlink()
            lock_target = base / 'lock-target'
            lock_target.write_text('foreign')
            lock_path.symlink_to(lock_target)
            next_payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 'lock-session',
                                       'prompt_id': 'second', 'prompt': 'Hello'})
            emitted = self.run_hook(next_payload, 'he', '--state-dir', str(state))
            self.assertIn('ענה בעברית', emitted['hookSpecificOutput']['additionalContext'])
            self._assert_has_marker(emitted)

            missing_turn = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 'lock-session',
                                       'prompt': 'Hello'})
            emitted_missing = self.run_hook(missing_turn, 'he', '--state-dir', str(state))
            self.assertIn('ענה בעברית', emitted_missing['hookSpecificOutput']['additionalContext'])
            self.assertNotEqual(emitted_missing, {})
            missing_session = json.dumps({'hook_event_name': 'UserPromptSubmit', 'prompt_id': 'turn-3',
                                          'prompt': 'Hello'})
            emitted_no_session = self.run_hook(missing_session, 'he', '--state-dir', str(state))
            self.assertIn('ענה בעברית', emitted_no_session['hookSpecificOutput']['additionalContext'])
            self.assertNotEqual(emitted_no_session, {})

    def test_corrupt_cache_does_not_suppress_and_is_replaced_safely(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory) / 'state'
            state.mkdir(mode=0o700)
            session = 'corrupt-cache-session'
            cache = state / ('language-session-' + hashlib.sha256(session.encode()).hexdigest() + '.json')
            cache.write_text('{broken')
            os.chmod(cache, 0o600)
            payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': session,
                                  'prompt_id': 'turn-1', 'prompt': 'Hello'})
            emitted = self.run_hook(payload, 'he', '--state-dir', str(state))
            self._assert_has_marker(emitted)
            repaired = json.loads(cache.read_text())
            self.assertEqual(repaired['session_hash'], hashlib.sha256(session.encode()).hexdigest())
            self.assertNotIn(session, cache.read_text())

    def test_noninteger_schema_values_never_match_cache(self):
        for bad_schema in (True, 1.0):
            with self.subTest(schema=bad_schema), tempfile.TemporaryDirectory(dir=Path.home()) as directory:
                state = Path(directory) / 'state'
                state.mkdir(mode=0o700)
                session = f'bad-schema-{type(bad_schema).__name__}'
                version = self._receipt_version()
                cache = state / ('language-session-' + hashlib.sha256(session.encode()).hexdigest() + '.json')
                cache.write_text(json.dumps({
                    'schema': bad_schema,
                    'session_hash': hashlib.sha256(session.encode()).hexdigest(),
                    'language': 'he', 'version_hash': version,
                }))
                os.chmod(cache, 0o600)
                payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': session,
                                      'prompt_id': 'turn-1', 'prompt': 'Hello'})
                emitted = self.run_hook(payload, 'he', '--state-dir', str(state))
                self._assert_has_marker(emitted)
                repaired = json.loads(cache.read_text())
                self.assertIs(type(repaired['schema']), int)
                self.assertEqual(repaired['schema'], 1)

    def test_neutral_prompt_gets_configured_hebrew_directive(self):
        result = self.run_hook(json.dumps({'hook_event_name': 'UserPromptSubmit', 'prompt': 'What time is it?'}))
        context = result['hookSpecificOutput']['additionalContext']
        self.assertIn('עברית', context)
        self.assertIn('באנגלית', context)
        self.assertTrue(context.startswith('ענה בעברית;'))
        self.assertLessEqual(len(context), 43)
        self.assertNotRegex(context, r'\[wf:[^]]+\]')

    def test_english_and_session_start_are_supported(self):
        for event in ('UserPromptSubmit', 'SessionStart'):
            result = self.run_hook(json.dumps({'hook_event_name': event}), 'en')
            self.assertIn('Reply in English', result['hookSpecificOutput']['additionalContext'])
            self.assertLessEqual(len(result['hookSpecificOutput']['additionalContext']), 43)

    def test_stamped_language_context_fits_with_actual_workflow_substantial_context(self):
        # Exercise the workflow hook's real context builder; isolate only its ledger write.
        with patch.object(workflow_hook, 'start_task', return_value=None):
            workflow_result = workflow_hook._prompt({
                'hook_event_name': 'UserPromptSubmit',
                'prompt': 'Implement a system for Example.',
                'session_id': 'fixture-session', 'turn_id': 'fixture-turn', 'cwd': '/tmp',
            })
        workflow_context = workflow_result['hookSpecificOutput']['additionalContext']
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            result = self.run_hook(json.dumps({
                'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': 't',
                'prompt': 'What time is it?',
            }), 'he', '--state-dir', str(Path(directory) / 'state'))
            language_context = result['hookSpecificOutput']['additionalContext']
            self.assertRegex(language_context, r'\[wf:[0-9a-f]{16}:[0-9a-f]{32}\]')
            # The actual public workflow context plus stamped language context must stay <= 300.
            self.assertLessEqual(len(workflow_context) + len(language_context), 300)

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

    def test_omitted_state_dir_keeps_always_emit_fallback(self):
        payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'without-state',
                   'prompt_id': 'turn', 'prompt': 'Hello'}
        first = self.run_hook(json.dumps(payload), 'he')
        second = self.run_hook(json.dumps({**payload, 'prompt_id': 'turn-2'}), 'he')
        self.assertEqual(first['hookSpecificOutput']['additionalContext'],
                         second['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('[wf:', first['hookSpecificOutput']['additionalContext'])

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
            self.assertLessEqual(len(context), 98)
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
            self.assertLessEqual(len(context), 98)
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

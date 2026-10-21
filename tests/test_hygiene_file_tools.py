"""Acceptance tests for the explicitly limited native-file-tools hygiene mode."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'claude-plugin' / 'workflow-hooks-kit' / 'scripts'
spec = importlib.util.spec_from_file_location('file_tools_installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def run_core(home, payload, platform='codex'):
    wrapper = ('import json,sys; sys.path.insert(0,sys.argv[1]); import tool_scope_hook as c; '
               'print(json.dumps(c.run(json.load(sys.stdin),claude=sys.argv[2]=="claude")))')
    return subprocess.run([sys.executable, '-B', '-c', wrapper, str(SCRIPTS), platform],
        input=json.dumps(payload), text=True, capture_output=True, timeout=10,
        env={**os.environ, 'HOME': str(home)})


def result_json(result):
    if result.returncode != 0:
        raise AssertionError(f'core exited {result.returncode}: {result.stderr}')
    return json.loads(result.stdout)


def denied(result):
    return isinstance(result, dict) and result.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'


class HygieneFileToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hygiene-file-tools-', dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / 'project'
        self.project.mkdir()
        self.payload = {'session_id': 'file-tools-session', 'turn_id': 'file-tools-turn', 'cwd': str(self.project)}

    def event(self, tool, data=None, event='PreToolUse'):
        payload = {**self.payload, 'hook_event_name': event}
        if tool is not None:
            payload.update(tool_name=tool, tool_input=data or {})
        return payload

    def policy_path(self, home, platform='codex'):
        base = home / ('.codex' if platform == 'codex' else '.claude') / 'workflow-hooks-kit'
        return base / ('state/hygiene-policy.json' if platform == 'codex' else 'hygiene-policy.json')

    def set_mode(self, mode):
        path = self.policy_path(self.home)
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text(json.dumps({'schema': 1, 'mode': mode}), encoding='utf-8')
        path.chmod(0o600)

    def bash(self, command):
        return result_json(run_core(self.home, self.event('Bash', {'command': command})))

    def hygiene(self, action, body):
        return self.bash('workflow-hygiene ' + action + ' ' + shlex.quote(json.dumps(body)))

    def test_absent_policy_keeps_baseline_behavior(self):
        payloads = [self.event('Bash', {'command': 'pwd'}),
                    self.event('mcp__files__write_file', {'path': 'x', 'content': 'x'}),
                    self.event('functions.exec', {'cmd': 'touch x'})]
        for payload in payloads:
            self.assertEqual(result_json(run_core(self.home, payload)), {})
        self.assertFalse((self.project / 'x').exists())
        self.assertFalse((self.project / 'notes.txt').exists())
        self.assertFalse(self.policy_path(self.home).exists())

    def test_file_tools_mode_preserves_shell_and_unknown_tool_baseline(self):
        self.set_mode('file-tools')
        for payload in (self.event('Bash', {'command': 'pwd'}),
                        self.event('mcp__files__write_file', {'path': 'x', 'content': 'x'}),
                        self.event('functions.exec', {'cmd': 'touch x'})):
            self.assertEqual(result_json(run_core(self.home, payload)), {})
        self.assertFalse((self.project / 'x').exists())

    def test_strict_mode_denies_the_same_shell_and_unknown_tool_calls(self):
        self.set_mode('enforce')
        for payload in (self.event('Bash', {'command': 'pwd'}),
                        self.event('mcp__files__write_file', {'path': 'x', 'content': 'x'}),
                        self.event('functions.exec', {'cmd': 'touch x'})):
            result = result_json(run_core(self.home, payload))
            self.assertTrue(denied(result), result)
        self.assertFalse((self.project / 'x').exists())

    def test_file_tools_requires_plan_review_backup_and_post_edit_qa(self):
        self.set_mode('file-tools')
        target = self.project / 'notes.txt'
        original = b'original before-image\n'
        target.write_bytes(original)
        write = self.event('Write', {'file_path': str(target), 'content': 'updated\n'})
        denied_write = result_json(run_core(self.home, write))
        self.assertTrue(denied(denied_write), denied_write)
        self.assertEqual(target.read_bytes(), original)

        plan = {'definition_of_done': 'Update notes.txt', 'outputs': ['notes.txt'],
                'qa': {'check': 'Read notes.txt', 'expected': 'Contains updated text'}}
        planned = self.bash('workflow-ledger plan ' + shlex.quote(json.dumps(plan)))
        self.assertTrue(denied(planned), planned)
        self.assertIn('Plan saved', planned['hookSpecificOutput']['permissionDecisionReason'])
        still_denied = result_json(run_core(self.home, write))
        self.assertTrue(denied(still_denied), still_denied)

        inspected = self.hygiene('inspect', {'paths': ['notes.txt']})
        self.assertTrue(denied(inspected), inspected)
        reason = inspected['hookSpecificOutput']['permissionDecisionReason']
        observed = json.JSONDecoder().raw_decode(reason)[0]['inspected'][0]['sha256']
        before_review = {'entries': [{'path': 'notes.txt', 'decision': 'keep', 'sha256': observed,
            'reason': 'Requested fixture edit.', 'usage': 'Output required by this acceptance test.',
            'dependencies': 'Standalone fixture; no declared dependencies.',
            'concurrency': 'Single unittest process owns the temporary project.'}]}
        reviewed = self.hygiene('review', before_review)
        self.assertTrue(denied(reviewed), reviewed)
        self.assertIn('review accepted by code', reviewed['hookSpecificOutput']['permissionDecisionReason'])
        self.assertEqual(result_json(run_core(self.home, write)), {})

        # The test harness represents the host performing the approved native Write.
        target.write_bytes(b'updated\n')
        self.assertEqual(result_json(run_core(self.home, self.event('Write', write['tool_input'], 'PostToolUse'))), {})
        next_target = self.project / 'next.txt'
        next_write = self.event('Write', {'file_path': str(next_target), 'content': 'blocked'})
        blocked = result_json(run_core(self.home, next_write))
        self.assertTrue(denied(blocked), blocked)
        self.assertFalse(next_target.exists())
        stop = result_json(run_core(self.home, self.event(None, event='Stop')))
        self.assertEqual(stop.get('decision'), 'block', stop)

        updated_inspect = self.hygiene('inspect', {'paths': ['notes.txt']})
        updated_hash = json.JSONDecoder().raw_decode(
            updated_inspect['hookSpecificOutput']['permissionDecisionReason'])[0]['inspected'][0]['sha256']
        after_review = {'entries': [{'path': 'notes.txt', 'decision': 'keep', 'sha256': updated_hash,
            'reason': 'Requested output after edit.', 'usage': 'Verified updated fixture output.',
            'dependencies': 'Standalone fixture; no declared dependencies.',
            'concurrency': 'Single unittest process owns the temporary project.'}]}
        self.assertTrue(denied(self.hygiene('review', after_review)))
        qa = {'state': 'complete', 'qa': {'evidence': 'Updated bytes and exact before-image verified.',
              'verdict': 'pass', 'reviewer_id': 'lead'}}
        qa_result = self.bash('workflow-ledger qa ' + shlex.quote(json.dumps(qa)))
        self.assertTrue(denied(qa_result), qa_result)
        self.assertIn('QA saved', qa_result['hookSpecificOutput']['permissionDecisionReason'])
        self.assertEqual(result_json(run_core(self.home, self.event(None, event='Stop'))), {})
        backups = list((self.project / 'Old').rglob('notes.txt'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(hashlib.sha256(backups[0].read_bytes()).hexdigest(), hashlib.sha256(original).hexdigest())

    def test_installer_file_tools_policy_coexists_and_is_idempotent_for_both_hosts(self):
        for platform in ('codex', 'claude'):
            with self.subTest(platform=platform):
                home = self.home / platform
                base = home / ('.codex' if platform == 'codex' else '.claude')
                base.mkdir(parents=True)
                config_path = base / ('hooks.json' if platform == 'codex' else 'settings.json')
                foreign = {'type': 'command', 'command': 'foreign-observer'}
                config_path.write_text(json.dumps({'hooks': {'PreToolUse': [
                    {'matcher': 'Read', 'hooks': [foreign]}]}}), encoding='utf-8')
                installer.operate(home, platform, hygiene_file_tools=True)
                policy = self.policy_path(home, platform)
                self.assertEqual(json.loads(policy.read_text()), {'schema': 1, 'mode': 'file-tools'})
                config = json.loads(config_path.read_text())
                self.assertIn(foreign, config['hooks']['PreToolUse'][0]['hooks'])
                command = installer.command(home, platform)
                for event in installer.EVENTS:
                    owned = [h for g in config['hooks'][event] for h in g['hooks'] if h.get('command') == command]
                    self.assertEqual(len(owned), 1, (platform, event))
                config_before, policy_before = config_path.read_bytes(), policy.read_bytes()
                installer.operate(home, platform, hygiene_file_tools=True)
                self.assertEqual(config_path.read_bytes(), config_before)
                self.assertEqual(policy.read_bytes(), policy_before)

    def test_strict_to_file_tools_and_mutually_exclusive_modes_refuse_without_mutation(self):
        for platform in ('codex', 'claude'):
            with self.subTest(platform=platform):
                home = self.home / ('strict-' + platform)
                installer.operate(home, platform, hygiene_enforcement=True)
                policy = self.policy_path(home, platform)
                config = home / ('.codex/hooks.json' if platform == 'codex' else '.claude/settings.json')
                before = policy.read_bytes(), config.read_bytes()
                with self.assertRaises(ValueError):
                    installer.operate(home, platform, hygiene_file_tools=True)
                self.assertEqual((policy.read_bytes(), config.read_bytes()), before)

        api_home = self.home / 'api-conflict'
        with self.assertRaises(ValueError):
            installer.operate(api_home, 'codex', hygiene_enforcement=True, hygiene_file_tools=True)
        self.assertFalse(api_home.exists())
        cli_home = self.home / 'cli-conflict'
        cli = subprocess.run([sys.executable, str(ROOT / 'install.py'), '--platform', 'codex',
            '--home', str(cli_home), '--hygiene-enforcement', '--hygiene-file-tools'],
            text=True, capture_output=True, timeout=10)
        self.assertNotEqual(cli.returncode, 0)
        self.assertFalse(cli_home.exists())

    def test_dangling_policy_symlink_fails_closed_for_both_hosts(self):
        for platform in ('codex', 'claude'):
            home = self.home / ('dangling-' + platform)
            project = home / 'project'; project.mkdir(parents=True)
            policy = self.policy_path(home, platform)
            policy.parent.mkdir(parents=True, mode=0o700)
            policy.symlink_to(policy.parent / 'absent-target')
            payload = {'hook_event_name': 'PreToolUse', 'session_id': 'dangling-policy',
                       'turn_id': 'dangling-turn', 'cwd': str(project),
                       'tool_name': 'Read', 'tool_input': {'file_path': str(project / 'x')}}
            result = result_json(run_core(home, payload, platform))
            self.assertTrue(denied(result))
            self.assertIn('Hygiene validation unavailable', result['hookSpecificOutput']['permissionDecisionReason'])
            stopped = result_json(run_core(home, {**payload, 'hook_event_name': 'Stop'}, platform))
            self.assertEqual(stopped.get('decision'), 'block')
            self.assertIn('Hygiene validation unavailable', stopped.get('reason', ''))
            self.assertTrue(policy.is_symlink())
            self.assertFalse((project / 'x').exists())

    def test_malformed_file_tools_policy_fails_closed(self):
        for body in ({'schema': 1, 'mode': 'file-tools', 'extra': True},
                     {'schema': True, 'mode': 'file-tools'}, {'schema': 2, 'mode': 'file-tools'}):
            with self.subTest(policy=body):
                home = self.home / ('bad-' + str(len(list(self.home.iterdir()))))
                project = home / 'project'; project.mkdir(parents=True)
                state = home / '.codex/workflow-hooks-kit/state'; state.mkdir(parents=True, mode=0o700)
                (state / 'hygiene-policy.json').write_text(json.dumps(body), encoding='utf-8')
                payload = {'hook_event_name': 'PreToolUse', 'session_id': 'bad-policy', 'turn_id': 'bad-turn',
                           'cwd': str(project), 'tool_name': 'Read', 'tool_input': {'file_path': 'notes.txt'}}
                self.assertTrue(denied(result_json(run_core(home, payload))), body)


if __name__ == '__main__':
    unittest.main()

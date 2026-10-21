"""Acceptance tests for opt-in strict write-boundary coverage."""

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
CORE = SCRIPTS / 'tool_scope_hook.py'
PLUGIN = SCRIPTS / 'plugin_adapter.py'

spec = importlib.util.spec_from_file_location('hygiene_write_boundary_installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def run_core(home, payload):
    wrapper = (
        'import json,sys; sys.path.insert(0,sys.argv[1]); '
        'import tool_scope_hook as core; '
        'print(json.dumps(core.run(json.load(sys.stdin))))'
    )
    return subprocess.run(
        [sys.executable, '-B', '-c', wrapper, str(SCRIPTS)],
        input=json.dumps(payload), text=True, capture_output=True, timeout=10,
        env={**os.environ, 'HOME': str(home)},
    )


def result_json(result):
    if result.returncode != 0:
        raise AssertionError(f'core process exited {result.returncode}: {result.stderr}')
    return json.loads(result.stdout)


def denied(result):
    return (
        isinstance(result, dict)
        and result.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'
    )


class HygieneWriteBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hygiene-boundary-', dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / 'project'
        self.project.mkdir()
        self.state = self.home / '.codex' / 'workflow-hooks-kit' / 'state'
        self.payload = {
            'hook_event_name': 'PreToolUse',
            'session_id': 'boundary-session',
            'turn_id': 'boundary-turn',
            'cwd': str(self.project),
        }

    def enable_strict(self):
        self.state.mkdir(parents=True, mode=0o700)
        policy = self.state / 'hygiene-policy.json'
        policy.write_text(json.dumps({'schema': 1, 'mode': 'enforce'}), encoding='utf-8')
        policy.chmod(0o600)

    def event(self, tool, tool_input=None):
        return {**self.payload, 'tool_name': tool, 'tool_input': tool_input or {}}

    def test_strict_mode_denies_unknown_mcp_wrappers_and_mutators(self):
        self.enable_strict()
        unknown_tools = (
            'mcp__files__write_file',
            'mcp.foo.Read',
            'mcp__x__Write',
            'functions.exec',
            'write_stdin',
            'MysteryTool',
        )
        for tool in unknown_tools:
            with self.subTest(tool=tool):
                payload = self.event(tool, {'cmd': 'touch unknown-output.txt', 'file_path': 'unknown-output.txt'})
                result = result_json(run_core(self.home, payload))
                self.assertTrue(denied(result), result)
                self.assertFalse((self.project / 'unknown-output.txt').exists())

    def test_strict_mode_allows_native_read_tools_and_disabled_mode_keeps_unknown_noop(self):
        self.enable_strict()
        for tool in ('Read', 'Glob', 'Grep'):
            with self.subTest(tool=tool):
                result = result_json(run_core(self.home, self.event(tool, {'pattern': 'anything'})))
                self.assertEqual(result, {})

        disabled_home = self.home / 'disabled-home'
        disabled_home.mkdir()
        disabled_project = disabled_home / 'project'
        disabled_project.mkdir()
        payload = {
            **self.payload, 'cwd': str(disabled_project), 'tool_name': 'mcp__files__write_file',
            'tool_input': {'path': 'ignored.txt', 'content': 'baseline contract'},
        }
        self.assertEqual(result_json(run_core(disabled_home, payload)), {})
        self.assertFalse((disabled_home / '.codex/workflow-hooks-kit/state').exists())

    def test_shell_alias_writes_are_denied_and_supported_write_still_needs_preflight(self):
        self.enable_strict()
        for tool in ('functions.exec_command', 'functions.shell_command'):
            with self.subTest(tool=tool):
                payload = self.event(tool, {'cmd': 'printf unsafe > alias-output.txt'})
                result = result_json(run_core(self.home, payload))
                self.assertTrue(denied(result), result)
                self.assertFalse((self.project / 'alias-output.txt').exists())

        plan = {
            'definition_of_done': 'Create notes.txt',
            'outputs': ['notes.txt'],
            'qa': {'check': 'Read notes.txt', 'expected': 'Contains notes'},
        }
        command = 'workflow-ledger plan ' + shlex.quote(json.dumps(plan))
        plan_result = result_json(run_core(self.home, self.event('Bash', {'command': command})))
        self.assertTrue(denied(plan_result), plan_result)
        self.assertIn('Plan saved', plan_result['hookSpecificOutput']['permissionDecisionReason'])

        write = self.event('Write', {'file_path': str(self.project / 'notes.txt'), 'content': 'notes'})
        write_result = result_json(run_core(self.home, write))
        self.assertTrue(denied(write_result), write_result)
        self.assertIn('Hygiene:', write_result['hookSpecificOutput']['permissionDecisionReason'])
        self.assertFalse((self.project / 'notes.txt').exists())

    def test_installer_broad_matcher_survives_reinstall_and_legacy_upgrade(self):
        for platform in ('codex', 'claude'):
            with self.subTest(platform=platform):
                home = self.home / platform
                installer.operate(home, platform)
                installer.operate(home, platform)
                config_path = home / ('.codex/hooks.json' if platform == 'codex' else '.claude/settings.json')
                receipt_path = home / '.codex/workflow-hooks-kit/install-receipt.json' if platform == 'codex' else home / '.claude/workflow-hooks-kit/install-receipt.json'
                config = json.loads(config_path.read_text(encoding='utf-8'))
                for event in ('PreToolUse', 'PostToolUse'):
                    groups = config['hooks'][event]
                    self.assertEqual(len(groups), 1)
                    self.assertEqual(groups[0]['matcher'], '.*')
                    commands = [hook['command'] for group in groups for hook in group['hooks']]
                    self.assertEqual(commands, [installer.command(home, platform)])
                for event in ('UserPromptSubmit', 'Stop'):
                    self.assertNotIn('matcher', config['hooks'][event][0])

                legacy = next(iter(installer.LEGACY_MATCHERS))
                config['hooks']['PreToolUse'][0]['matcher'] = legacy
                config_path.write_text(json.dumps(config), encoding='utf-8')
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                receipt['owned']['PreToolUse']['matcher'] = legacy
                receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
                installer.operate(home, platform)
                upgraded = json.loads(config_path.read_text(encoding='utf-8'))['hooks']['PreToolUse']
                self.assertEqual(len(upgraded), 1)
                self.assertEqual(upgraded[0]['matcher'], '.*')
                self.assertEqual(upgraded[0]['hooks'][0]['command'], installer.command(home, platform))

    def test_core_and_plugin_cli_reject_malformed_oversized_and_nonobject_json(self):
        cases = (
            ('malformed', b'{bad-json'),
            ('oversized', b' ' * 1_000_001),
            ('nonobject', b'[]'),
        )
        for script in (CORE, PLUGIN):
            for label, raw in cases:
                with self.subTest(script=script.name, input=label):
                    result = subprocess.run(
                        [sys.executable, '-B', str(script)], input=raw, capture_output=True,
                        timeout=10, env={**os.environ, 'HOME': str(self.home)},
                    )
                    self.assertEqual(result.returncode, 2, result.stdout.decode(errors='replace'))

    def test_strict_mode_denies_ordinary_pwd_and_git_status(self):
        self.enable_strict()
        for command in ('pwd', 'git status'):
            with self.subTest(command=command):
                result = result_json(run_core(self.home, self.event('Bash', {'command': command})))
                self.assertTrue(denied(result), result)

    def test_hygiene_read_returns_bounded_text_and_hash_without_shell_execution(self):
        self.enable_strict()
        target = self.project / 'notes.txt'
        target.write_text('héllo world', encoding='utf-8')
        marker = self.project / 'shell-ran.txt'
        command = 'workflow-hygiene read ' + shlex.quote(json.dumps({'path': 'notes.txt', 'offset': 1, 'limit': 4}))
        result = result_json(run_core(self.home, self.event('Bash', {'command': command + f' ; touch {marker}'})))
        self.assertTrue(denied(result), result)
        self.assertFalse(marker.exists())

        result = result_json(run_core(self.home, self.event('Bash', {'command': command})))
        self.assertTrue(denied(result), result)
        body = json.loads(result['hookSpecificOutput']['permissionDecisionReason'])
        import hashlib
        self.assertEqual(body['text'], 'éllo')
        self.assertEqual(body['sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
        self.assertEqual(body['offset'], 1)

    def test_hygiene_read_rejects_bad_bounds_missing_outside_and_symlink(self):
        self.enable_strict()
        target = self.project / 'notes.txt'
        target.write_text('readable', encoding='utf-8')
        outside = self.home / 'outside.txt'
        outside.write_text('private', encoding='utf-8')
        (self.project / 'linked.txt').symlink_to(target)
        bodies = (
            {'path': 'notes.txt', 'offset': True},
            {'path': 'notes.txt', 'offset': -1},
            {'path': 'notes.txt', 'limit': 8001},
            {'path': 'missing.txt'},
            {'path': str(outside)},
            {'path': 'linked.txt'},
        )
        for body in bodies:
            with self.subTest(body=body):
                command = 'workflow-hygiene read ' + shlex.quote(json.dumps(body))
                result = result_json(run_core(self.home, self.event('Bash', {'command': command})))
                self.assertTrue(denied(result), result)

    def test_dotted_mcp_exec_command_is_not_normalized_into_native_shell(self):
        self.enable_strict()
        target = self.project / 'should-not-exist.txt'
        payload = self.event('mcp.foo.exec_command', {'cmd': f'touch {target}'})
        result = result_json(run_core(self.home, payload))
        self.assertTrue(denied(result), result)
        self.assertFalse(target.exists())

    def test_malformed_policy_fails_pretooluse_closed(self):
        self.enable_strict()
        (self.state / 'hygiene-policy.json').write_text('{"schema":1,"mode":"observe"}', encoding='utf-8')
        result = result_json(run_core(self.home, self.event('Read', {'file_path': 'notes.txt'})))
        self.assertTrue(denied(result), result)

    def test_missing_core_dependency_cli_exits_two(self):
        isolated = self.home / 'incomplete-runtime'
        isolated.mkdir()
        (isolated / 'tool_scope_hook.py').write_bytes(CORE.read_bytes())
        payload = self.event('Read', {'file_path': 'notes.txt'})
        result = subprocess.run(
            [sys.executable, '-B', str(isolated / 'tool_scope_hook.py')],
            input=json.dumps(payload), text=True, capture_output=True, timeout=10,
            env={**os.environ, 'HOME': str(self.home)},
        )
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_missing_native_receipt_denies_otherwise_allowed_pretooluse(self):
        isolated = self.home / 'runtime-without-receipt'
        isolated.mkdir()
        for source in SCRIPTS.glob('*.py'):
            if source.name != 'native_receipt.py':
                (isolated / source.name).write_bytes(source.read_bytes())
        payload = self.event('Read', {'file_path': 'notes.txt'})
        result = subprocess.run(
            [sys.executable, '-B', str(isolated / 'tool_scope_hook.py')],
            input=json.dumps(payload), text=True, capture_output=True, timeout=10,
            env={**os.environ, 'HOME': str(self.home)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(denied(json.loads(result.stdout)), result.stdout)

    def test_installed_command_uses_target_home_not_invoking_parent_home(self):
        target_home = self.home / 'installed-home'
        caller_home = self.home / 'different-caller-home'
        target_home.mkdir()
        caller_home.mkdir()
        installer.operate(target_home, 'codex')
        state = target_home / '.codex/workflow-hooks-kit/state'
        state.mkdir(parents=True, mode=0o700)
        (state / 'hygiene-policy.json').write_text(json.dumps({'schema': 1, 'mode': 'enforce'}), encoding='utf-8')
        (state / 'hygiene-policy.json').chmod(0o600)
        config = json.loads((target_home / '.codex/hooks.json').read_text(encoding='utf-8'))
        command = config['hooks']['PreToolUse'][0]['hooks'][0]['command']
        payload = {
            'hook_event_name': 'PreToolUse', 'session_id': 'isolated-home-session',
            'turn_id': 'isolated-home-turn', 'cwd': str(self.project),
            'tool_name': 'mcp__arbitrary__write', 'tool_input': {'path': 'attempt.txt'},
        }
        result = subprocess.run(
            shlex.split(command), input=json.dumps(payload), text=True, capture_output=True,
            timeout=10, env={**os.environ, 'HOME': str(caller_home)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(denied(json.loads(result.stdout)), result.stdout)
        self.assertTrue((target_home / '.codex/workflow-hooks-kit/hook-receipts/tool-scope').exists())
        self.assertFalse((caller_home / '.codex').exists())

    def test_installer_migrates_legacy_owned_hook_and_preserves_foreign_hook(self):
        home = self.home / 'legacy-install'
        installer.operate(home, 'claude')
        config_path = home / '.claude/settings.json'
        receipt_path = home / '.claude/workflow-hooks-kit/install-receipt.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        event = 'PreToolUse'
        group = config['hooks'][event][0]
        legacy_matcher = next(iter(installer.LEGACY_MATCHERS))
        prior_command = installer.command(home, 'claude').removeprefix('env HOME=' + shlex.quote(str(home)) + ' ')
        legacy_hook = {key: value for key, value in group['hooks'][0].items() if key != 'onFailure'}
        legacy_hook['command'] = prior_command
        foreign_hook = {'type': 'command', 'command': 'python3 foreign_hook.py', 'timeout': 7}
        group['matcher'] = legacy_matcher
        group['hooks'] = [legacy_hook, foreign_hook]
        config_path.write_text(json.dumps(config), encoding='utf-8')
        receipt['owned'][event] = {'hook': legacy_hook, 'matcher': legacy_matcher}
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')

        installer.operate(home, 'claude')
        migrated = json.loads(config_path.read_text(encoding='utf-8'))['hooks'][event]
        owned = [h for g in migrated for h in g['hooks'] if h.get('command') == installer.command(home, 'claude')]
        foreign = [h for g in migrated for h in g['hooks'] if h.get('command') == foreign_hook['command']]
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0].get('onFailure'), 'block')
        self.assertEqual(foreign, [foreign_hook])
        self.assertEqual(sum(g.get('matcher') == '.*' for g in migrated), 1)


if __name__ == '__main__':
    unittest.main()

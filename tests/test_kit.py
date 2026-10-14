import importlib.util
import json
from pathlib import Path
import shlex
import sys
import subprocess
import zipfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'claude-plugin/workflow-hooks-kit/scripts'
sys.path.insert(0, str(SCRIPTS))
import tool_scope_hook as core
import session_workflow_hook as workflow
import plugin_adapter
spec = importlib.util.spec_from_file_location('kit_install', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
spec = importlib.util.spec_from_file_location('kit_build', ROOT / 'tools/build_plugin.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class HomeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workflow-kit-test-', dir=Path.home())
        self.home = Path(self.temp.name)
        self.project = self.home / 'project'
        self.project.mkdir()
        self.old_state, self.old_claude = workflow.STATE, core.CLAUDE_STATE
        workflow.STATE = self.home / 'state'
        core.CLAUDE_STATE = self.home / 'claude-state'

    def tearDown(self):
        workflow.STATE, core.CLAUDE_STATE = self.old_state, self.old_claude
        self.temp.cleanup()

    def event(self, event, tool=None, data=None, **extra):
        result = {'hook_event_name': event, 'session_id': 'fixture-session', 'turn_id': 'fixture-turn', 'cwd': str(self.project)}
        if tool:
            result.update(tool_name=tool, tool_input=data or {})
        return {**result, **extra}

    def sentinel(self, action, value):
        return core.run(self.event('PreToolUse', 'Bash', {'command': 'workflow-ledger ' + action + ' ' + shlex.quote(json.dumps(value))}))

    @staticmethod
    def reason(result):
        return result.get('hookSpecificOutput', {}).get('permissionDecisionReason', '')


class RuntimeTests(HomeFixture):
    def test_plan_scope_stop_and_qa(self):
        write = self.event('PreToolUse', 'Write', {'file_path': str(self.project / 'notes.txt'), 'content': 'checked'})
        self.assertEqual(core.run(write)['hookSpecificOutput']['permissionDecision'], 'deny')
        plan = {'definition_of_done': 'Create requested file', 'outputs': ['notes.txt'], 'qa': {'check': 'Read output', 'expected': 'checked'}}
        self.assertIn('Plan saved', self.reason(self.sentinel('plan', plan)))
        self.assertEqual(core.run(write), {})
        outside = {**write, 'tool_input': {'file_path': str(self.home / 'outside.txt')}}
        self.assertEqual(core.run(outside)['hookSpecificOutput']['permissionDecision'], 'deny')
        (self.project / 'notes.txt').write_text('checked')
        core.run({**write, 'hook_event_name': 'PostToolUse'})
        stop = self.event('Stop')
        self.assertEqual(core.run(stop).get('decision'), 'block')
        self.assertNotEqual(core.run(stop).get('decision'), 'block')
        qa = {'state': 'complete', 'qa': {'evidence': 'Read output, contains checked', 'verdict': 'pass', 'reviewer_id': 'lead'}}
        self.assertIn('QA saved', self.reason(self.sentinel('qa', qa)))
        self.assertNotEqual(core.run(stop).get('decision'), 'block')
        ledger = workflow._read(workflow._ledger_path('fixture-session', 'fixture-turn'))
        self.assertEqual(ledger['state'], 'complete')

    def test_context_and_input_privacy(self):
        self.assertEqual(core.run(self.event('UserPromptSubmit', prompt='hello')), {})
        self.assertFalse(workflow.STATE.exists())
        prompt = 'Build a system for local testing'
        result = core.run(self.event('UserPromptSubmit', prompt=prompt))
        context = result['hookSpecificOutput']['additionalContext']
        self.assertLessEqual(len(context), 300)
        self.assertNotIn(prompt, ''.join(p.read_text() for p in workflow.STATE.glob('*.json')))

    def test_frozen_plan_and_invalid_identity(self):
        plan = {'definition_of_done': 'Create file', 'outputs': ['notes.txt'], 'qa': {'check': 'Read', 'expected': 'Text'}}
        self.sentinel('plan', plan)
        changed = {**plan, 'definition_of_done': 'Changed criteria'}
        self.assertIn('not accepted', self.reason(self.sentinel('plan', changed)))
        result = core.run(self.event('PreToolUse', 'Write', {'file_path': str(self.project/'notes.txt')}, session_id=''))
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_retry_ladder_is_local_validation(self):
        self.assertEqual(workflow.retry_action(['basic', 'advanced'], [], 'basic'), 'retry')
        attempts = [{'model': 'basic', 'verdict': 'fail'}] * 3
        self.assertEqual(workflow.retry_action(['basic', 'advanced'], attempts, 'basic'), 'escalate')
        self.assertEqual(workflow.retry_action(['basic'], attempts, 'basic'), 'return_user')


class InstallerTests(HomeFixture):
    def config(self, platform):
        return self.home / ('.codex/hooks.json' if platform == 'codex' else '.claude/settings.json')

    def test_install_reinstall_uninstall_preserves_original_and_later_edits(self):
        original = {'permissions': {'allow': ['Read']}, 'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo existing'}]}], 'Stop': []}}
        for platform in ('codex', 'claude'):
            path = self.config(platform)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(original))
            installer.operate(self.home, platform)
            installer.operate(self.home, platform)
            data = json.loads(path.read_text())
            for event in installer.EVENTS:
                self.assertEqual(sum(h.get('command') == installer.command(self.home, platform) for g in data['hooks'][event] for h in g['hooks']), 1)
            self.assertEqual(data['permissions'], original['permissions'])
            data['later-edit'] = 'keep'
            data['hooks']['Stop'][0]['hooks'][0]['timeout'] = 42
            path.write_text(json.dumps(data))
            installer.operate(self.home, platform, uninstall=True)
            after = json.loads(path.read_text())
            self.assertEqual(after['later-edit'], 'keep')
            self.assertEqual(after['hooks']['SessionStart'], original['hooks']['SessionStart'])
            self.assertEqual(after['hooks']['Stop'][0]['hooks'][0]['timeout'], 42)
            self.assertNotIn('PreToolUse', after['hooks'])
            self.assertTrue(any((path.parent/'workflow-hooks-kit/backups').glob('*'+path.name)))

    def test_original_exact_hooks_are_not_claimed(self):
        path = self.config('codex')
        path.parent.mkdir()
        original = {'hooks': {'Stop': [installer.entry(self.home, 'codex', 'Stop')]}}
        path.write_text(json.dumps(original))
        installer.operate(self.home, 'codex')
        installer.operate(self.home, 'codex', True)
        self.assertEqual(json.loads(path.read_text()), original)

    def test_later_matcher_edit_survives(self):
        installer.operate(self.home, 'codex')
        path = self.config('codex')
        data = json.loads(path.read_text())
        data['hooks']['PreToolUse'][0]['matcher'] = 'Write'
        path.write_text(json.dumps(data))
        installer.operate(self.home, 'codex', True)
        self.assertEqual(json.loads(path.read_text())['hooks']['PreToolUse'], data['hooks']['PreToolUse'])

    def test_symlinks_rejected_before_config_mutation(self):
        for name in ('bin', 'backups', 'install-receipt.json', 'WORK_STANDARDS.md'):
            with self.subTest(name=name):
                sandbox = self.home/name.replace('.', '_')
                path = sandbox/'.codex/hooks.json'
                kit = path.parent/'workflow-hooks-kit'
                kit.mkdir(parents=True)
                path.write_text('{"unchanged": true}')
                outside = sandbox/'redirect'
                if name in ('bin','backups'):
                    outside.mkdir()
                else:
                    outside.write_text('{}')
                (kit/name).symlink_to(outside)
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    installer.operate(sandbox, 'codex')
                self.assertEqual(path.read_bytes(), before)

    def test_copy_failure_leaves_configuration_unchanged(self):
        path = self.config('codex')
        path.parent.mkdir()
        path.write_text('{"unchanged": true}')
        with patch.object(installer.shutil, 'copy2', side_effect=OSError('fixture copy failure')):
            with self.assertRaises(OSError):
                installer.operate(self.home, 'codex')
        self.assertEqual(path.read_text(), '{"unchanged": true}')

    def test_plugin_dedup_uses_installer_command_and_core_bytes(self):
        installer.operate(self.home, 'claude')
        self.assertTrue(plugin_adapter.global_adapter_active(self.home))
        script = self.home/'.claude/workflow-hooks-kit/bin/tool_scope_hook.py'
        script.write_text(script.read_text()+'\n# changed fixture\n')
        self.assertFalse(plugin_adapter.global_adapter_active(self.home))

    def test_real_cli_and_installed_learning(self):
        args = [sys.executable, '-B', str(ROOT/'install.py'), '--platform', 'both', '--home', str(self.home)]
        for extra in ([], [], ['--uninstall']):
            result = subprocess.run(args+extra, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for platform in ('codex', 'claude'):
            self.assertEqual(json.loads(self.config(platform).read_text()), {})
            installed = self.home/('.codex' if platform == 'codex' else '.claude')/'workflow-hooks-kit/bin/learning_cli.py'
            self.assertEqual(installed.read_bytes(), (ROOT/'learning/cli.py').read_bytes())
            result = subprocess.run([sys.executable, '-B', str(installed), '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_optional_mcp_shared_store_runtime_and_reversible_ownership(self):
        shared = self.home / 'shared learning'
        for platform in (('codex', 'claude') if sys.version_info >= (3, 11) else ('claude',)):
            installer.operate(self.home, platform)
            target = self.home / ('.codex/config.toml' if platform == 'codex' else '.claude.json')
            self.assertFalse(target.exists())
            original = 'model = "fixture"' if platform == 'codex' else '{"fixture": true}'
            target.write_text(original)
            for _ in range(2):
                installer.operate(self.home, platform, learning_mcp=True, state_dir=shared)
            if platform == 'codex':
                import tomllib
                definition = tomllib.loads(target.read_text())['mcp_servers'][installer.MCP_NAME]
            else:
                definition = json.loads(target.read_text())['mcpServers'][installer.MCP_NAME]
            runtime = Path(definition['args'][1])
            self.assertEqual(runtime.read_bytes(), (ROOT / 'learning/mcp_server.py').read_bytes())
            self.assertEqual((runtime.parent / 'cli.py').read_bytes(), (ROOT / 'learning/cli.py').read_bytes())
            request = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05'}}) + '\n'
            request += json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}) + '\n'
            result = subprocess.run([definition['command'], *definition['args']], input=request, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('learning_status', result.stdout)
            installer.operate(self.home, platform, uninstall=True)
            if platform == 'codex':
                self.assertEqual(target.read_text(), original)
            else:
                self.assertEqual(json.loads(target.read_text()), json.loads(original))
            self.assertTrue(shared.exists())

    def test_mcp_collisions_and_changed_owned_definitions_preserved(self):
        for platform in (('codex', 'claude') if sys.version_info >= (3, 11) else ('claude',)):
            installer.operate(self.home, platform)
            target = self.home / ('.codex/config.toml' if platform == 'codex' else '.claude.json')
            collision = '[mcp_servers.workflow_learning]\ncommand = "foreign"\n' if platform == 'codex' else '{"mcpServers":{"workflow_learning":{"command":"foreign"}}}'
            target.write_text(collision)
            with self.assertRaises(ValueError):
                installer.operate(self.home, platform, learning_mcp=True)
            self.assertEqual(target.read_text(), collision)
            target.write_text('' if platform == 'codex' else '{}')
            installer.operate(self.home, platform, learning_mcp=True)
            edited = target.read_text().replace('mcp_server.py', 'edited_server.py')
            target.write_text(edited)
            with self.assertRaises(ValueError):
                installer.operate(self.home, platform, learning_mcp=True)
            installer.operate(self.home, platform, uninstall=True)
            self.assertEqual(target.read_text(), edited)

    def test_optional_plugin_configuration_and_adjacent_runtime(self):
        output = self.home / 'optional.plugin'
        builder.build(output, learning_mcp=True, state_dir=self.home / 'shared')
        with zipfile.ZipFile(output) as archive:
            definition = json.loads(archive.read('.mcp.json'))['mcpServers']['workflow_learning']
            self.assertEqual(definition['args'][1], '${CLAUDE_PLUGIN_ROOT}/learning/mcp_server.py')
            self.assertIn('learning/cli.py', archive.namelist())
            self.assertEqual(archive.read('learning/mcp_server.py'), (ROOT/'learning/mcp_server.py').read_bytes())
        with self.assertRaises(ValueError):
            builder.build(output, learning_mcp=True)

    def test_build_deterministic_and_python_syntax(self):
        first, second = self.home/'first.plugin', self.home/'second.plugin'
        builder.build(first)
        builder.build(second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            self.assertIn('learning/cli.py', archive.namelist())
            self.assertIn('learning/README.md', archive.namelist())
            self.assertIn('learning/mcp_server.py', archive.namelist())
            self.assertNotIn('.mcp.json', archive.namelist())
            self.assertFalse(any('test_cli' in name or 'state.json' in name for name in archive.namelist()))
        for path in ROOT.rglob('*.py'):
            if 'Old' not in path.parts:
                compile(path.read_text(), str(path), 'exec')


if __name__ == '__main__':
    unittest.main()

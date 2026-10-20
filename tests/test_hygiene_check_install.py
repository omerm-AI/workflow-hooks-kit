"""Installed-command acceptance, without model calls or native-client claims."""
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
spec = importlib.util.spec_from_file_location('safe_check_installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@unittest.skipUnless(sys.platform == 'darwin', 'Actual macOS backend acceptance')
class InstalledCheckAcceptance(unittest.TestCase):
    def test_both_actual_installed_commands_keep_checks_separate_from_qa(self):
        for platform in ('codex', 'claude'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory(prefix='installed-check-', dir=Path.home()) as temp:
                home = Path(temp).resolve()
                installer.operate(home, platform, hygiene_enforcement=True)
                config = home / ('.codex/hooks.json' if platform == 'codex' else '.claude/settings.json')
                groups = json.loads(config.read_text())['hooks']['PreToolUse']
                command = next(h['command'] for g in groups for h in g['hooks'] if 'tool_scope_hook.py' in h.get('command', ''))
                project = home / 'populated-project'
                project.mkdir()
                current = project / 'source.txt'
                current.write_text('current installed bytes\n')
                payload = {'cwd': str(project), 'session_id': 'safe-install-session', 'turn_id': 'safe-install-turn', 'prompt_id': 'safe-install-turn'}

                def invoke(event, data=None):
                    body = {**payload, 'hook_event_name': event, 'tool_name': 'Bash', 'tool_input': {'command': data or ''}}
                    child = subprocess.run(shlex.split(command), input=json.dumps(body), capture_output=True, text=True, timeout=9,
                                           env={**os.environ, 'HOME': str(Path.home()), 'PYTHONDONTWRITEBYTECODE': '1'})
                    self.assertEqual(child.returncode, 0, child.stderr)
                    return json.loads(child.stdout)

                plan = {'definition_of_done': 'Keep installed source and run a bounded check', 'outputs': ['source.txt'],
                        'qa': {'check': 'Source remains unchanged and check runs safely', 'expected': 'No mutation and independent QA still required'}}
                result = invoke('PreToolUse', 'workflow-ledger plan ' + shlex.quote(json.dumps(plan)))
                self.assertIn('Plan saved', str(result))
                code = "from pathlib import Path; print(Path('source.txt').read_text())"
                body = {'argv': [str(Path(sys.executable).resolve()), '-B', '-c', code], 'timeout': 3}
                result = invoke('PreToolUse', 'workflow-hygiene check ' + shlex.quote(json.dumps(body)))
                text = result['hookSpecificOutput']['permissionDecisionReason']
                parsed = json.JSONDecoder().raw_decode(text)[0]
                self.assertEqual(parsed['safe_check']['status'], 'passed', result)
                # A process exit zero is evidence, never a release of pending QA.
                self.assertEqual(invoke('Stop').get('decision'), 'block')
                body['argv'][-1] = "open('source.txt','w').write('wrong')"
                result = invoke('PreToolUse', 'workflow-hygiene check ' + shlex.quote(json.dumps(body)))
                parsed = json.JSONDecoder().raw_decode(result['hookSpecificOutput']['permissionDecisionReason'])[0]
                self.assertEqual(parsed['safe_check']['status'], 'failed', result)
                self.assertEqual(current.read_text(), 'current installed bytes\n')


if __name__ == '__main__':
    unittest.main()

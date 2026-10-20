"""Operator opt-in, alternate-home installation and safe policy preservation."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hygiene_install', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class HygieneInstallerTests(unittest.TestCase):
    def test_both_platforms_enable_only_on_explicit_opt_in_and_reinstall_is_stable(self):
        for platform in ('codex', 'claude'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                installer.operate(home, platform)
                kit = home / ('.codex' if platform == 'codex' else '.claude') / 'workflow-hooks-kit'
                policy = kit / ('state/hygiene-policy.json' if platform == 'codex' else 'hygiene-policy.json')
                self.assertFalse(policy.exists())
                installer.operate(home, platform, hygiene_enforcement=True)
                self.assertEqual(json.loads(policy.read_text()), {'schema': 1, 'mode': 'enforce'})
                before = policy.read_bytes()
                installer.operate(home, platform, hygiene_enforcement=True)
                self.assertEqual(policy.read_bytes(), before)
                for name in ('hygiene_guard.py', 'hygiene_adapter.py'):
                    self.assertEqual((kit / 'bin' / name).read_bytes(), (installer.SOURCE / 'scripts' / name).read_bytes())

    def test_unknown_operator_policy_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            installer.operate(home, 'codex')
            state = home / '.codex/workflow-hooks-kit/state'
            state.mkdir(mode=0o700)
            policy = state / 'hygiene-policy.json'
            policy.write_text('{"schema": 99, "mode": "operator-owned"}')
            before = policy.read_bytes()
            with self.assertRaises(ValueError):
                installer.operate(home, 'codex', hygiene_enforcement=True)
            self.assertEqual(policy.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()

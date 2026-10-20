"""A host sandbox that rejects nesting must never yield false check success."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'claude-plugin/workflow-hooks-kit/scripts'


@unittest.skipUnless(sys.platform == 'darwin', 'Actual macOS backend acceptance')
class NestedBackendAcceptance(unittest.TestCase):
    def test_inherited_seatbelt_refuses_before_untrusted_check(self):
        with tempfile.TemporaryDirectory(prefix='nested-backend-') as temp:
            root = Path(temp).resolve() / 'project'
            root.mkdir()
            code = ('import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
                    'import hygiene_check;print(json.dumps(hygiene_check.run(Path(sys.argv[2]),'
                    '{"argv":[sys.executable,"-B","-c","print(\'untrusted-check-ran\')"],"timeout":3})))')
            child = subprocess.run(['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)',
                                    sys.executable, '-B', '-c', code, str(SCRIPTS), str(root)],
                                   capture_output=True, text=True, timeout=8)
            self.assertEqual(child.returncode, 0, child.stderr)
            result = json.loads(child.stdout)
            self.assertEqual(result['status'], 'unsupported', result)
            self.assertNotIn('untrusted-check-ran', result['output'])
            self.assertIsNone(result['returncode'])
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()

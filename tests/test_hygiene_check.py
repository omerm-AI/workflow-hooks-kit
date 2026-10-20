"""Independent actual-kernel acceptance for bounded hygiene checks."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'claude-plugin/workflow-hooks-kit/scripts'


@unittest.skipUnless(sys.platform == 'darwin', 'Actual macOS backend acceptance')
class SafeCheckAcceptance(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('independent_hygiene_check', SCRIPTS / 'hygiene_check.py')
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.temp = tempfile.TemporaryDirectory(prefix='safe-check-acceptance-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'existing-project'
        self.root.mkdir()
        self.current = self.root / 'current.txt'
        self.current.write_text('preserved current bytes\n')
        self.outside = self.base / 'outside-secret.txt'
        self.outside.write_text('private-outside-canary\n')

    def invoke(self, code, timeout=3):
        result = self.runner.run(self.root, {'argv': [str(Path(sys.executable).resolve()), '-B', '-c', code], 'timeout': timeout})
        self.assertEqual(self.current.read_text(), 'preserved current bytes\n')
        self.assertEqual(self.outside.read_text(), 'private-outside-canary\n')
        return result

    def test_read_project_and_write_scratch(self):
        result = self.invoke("from pathlib import Path; import os; assert Path('current.txt').read_text() == 'preserved current bytes\\n'; Path(os.environ['TMPDIR'],'check.tmp').write_text('scratch'); print('read-and-scratch-ok')")
        self.assertEqual(result['status'], 'passed', result)
        self.assertIn('read-and-scratch-ok', str(result))

    def test_no_overwrite(self):
        self.assertEqual(self.invoke("open('current.txt','w').write('wrong')")['status'], 'failed')

    def test_no_create(self):
        self.assertEqual(self.invoke("open('new.txt','w').write('wrong')")['status'], 'failed')
        self.assertFalse((self.root / 'new.txt').exists())

    def test_no_delete(self):
        self.assertEqual(self.invoke("import os; os.unlink('current.txt')")['status'], 'failed')

    def test_no_rename(self):
        self.assertEqual(self.invoke("import os; os.rename('current.txt','renamed.txt')")['status'], 'failed')
        self.assertFalse((self.root / 'renamed.txt').exists())

    def test_outside_write_denied(self):
        self.assertEqual(self.invoke('open(' + repr(str(self.outside)) + ",'w').write('wrong')")['status'], 'failed')

    def test_symlink_escape_denied(self):
        (self.root / 'alias').symlink_to(self.outside)
        self.assertEqual(self.invoke("open('alias','w').write('wrong')")['status'], 'failed')

    def test_outside_secret_read_denied(self):
        result = self.invoke('print(open(' + repr(str(self.outside)) + ').read())')
        self.assertEqual(result['status'], 'failed', result)
        self.assertNotIn('private-outside-canary', str(result))

    def test_child_creation_denied(self):
        for code in ("import os; os.fork()", "import os; os.posix_spawn('/usr/bin/true',['true'],{})", "import subprocess; subprocess.run(['/usr/bin/true'], start_new_session=True)"):
            with self.subTest(code=code):
                self.assertEqual(self.invoke(code)['status'], 'failed')

    def test_network_denied(self):
        self.assertEqual(self.invoke("import socket; s=socket.socket(); s.connect(('127.0.0.1',9))")['status'], 'failed')

    def test_timeout_bounded(self):
        started = time.monotonic()
        result = self.invoke('while True: pass', timeout=1)
        self.assertEqual(result['status'], 'timed-out', result)
        self.assertLess(time.monotonic() - started, 5)

    def test_output_bounded(self):
        result = self.invoke("import os;\nwhile True: os.write(1,b'x'*4096)")
        self.assertEqual(result['status'], 'output-limit', result)
        self.assertLess(len(str(result)), 10000)

    def test_failed_exit_not_pass(self):
        result = self.invoke('raise SystemExit(7)')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['returncode'], 7)

    def test_malformed_refused_before_execution(self):
        for body in ({'argv': ['python3']}, {'argv': [str(Path(sys.executable).resolve())], 'timeout': True}, {'argv': [str(Path(sys.executable).resolve())], 'timeout': 30}, {'argv': [], 'timeout': 1}, {'argv': ['/usr/bin/true'], 'env': {'HOME': str(self.base)}}):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    self.runner.run(self.root, body)


if __name__ == '__main__':
    unittest.main()

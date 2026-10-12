import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'learning'))
import mcp_server as mcp


class LearningMcpTests(unittest.TestCase):
    def setUp(self):
        # Use the real home to avoid OS-level symlinked temporary roots.
        self.tmp = tempfile.TemporaryDirectory(prefix='learning-mcp-test-', dir=Path.home())
        self.base = Path(self.tmp.name)
        self.root = self.base / 'state'
        self.broker = mcp.Broker(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def checkpoint(self, **extra):
        return self.broker.call('prompt_checkpoint', {'session_id': 'session', 'turn_id': 'turn', **extra})

    def proposal(self, **extra):
        return self.broker.call('propose_rule', {'scope': 'quality', 'rule': 'Use readable evidence.', 'source_ref': 'test:one', **extra})

    def cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return mcp.cli.main(['--state-dir', str(self.root), *args])

    def process(self, requests, extra=()):
        data = '\n'.join(json.dumps(r) if isinstance(r, dict) else r for r in requests) + '\n'
        run = subprocess.run([sys.executable, '-B', str(ROOT/'learning/mcp_server.py'), '--state-dir', str(self.root), *extra],
                             input=data, text=True, capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        return [json.loads(line) for line in run.stdout.splitlines()]

    @staticmethod
    def initialize():
        return {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05'}}

    @staticmethod
    def request(name, args=None):
        return {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': name, 'arguments': args or {}}}

    def test_real_stdio_protocol_and_notification(self):
        result = self.process([self.initialize(), {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                               {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'},
                               self.request('prompt_checkpoint', {'session_id': 'old-session', 'turn_id': 'first', 'prompt': 'Hello'})])
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['result']['protocolVersion'], '2024-11-05')
        self.assertEqual({t['name'] for t in result[1]['result']['tools']}, {t['name'] for t in mcp.TOOLS})
        output = json.loads(result[2]['result']['content'][0]['text'])
        self.assertEqual(output['additional_context'], '')
        self.assertNotIn('Hello', (self.root/'mcp-receipts.json').read_text())

    def test_repeat_receipt_is_identical_and_does_not_store_prompt_or_paths(self):
        first = self.checkpoint(prompt='Hello private prompt', cwd='/untrusted/path')
        files = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        second = self.checkpoint(prompt='remember Store a different request.')
        self.assertEqual(first['receipt'], second['receipt'])
        self.assertTrue(second['duplicate'])
        self.assertEqual(files, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertNotIn('untrusted', (self.root/'mcp-receipts.json').read_text())
        self.assertFalse((self.root/'state.json').exists())

    def test_explicit_requests_pending_and_source_dedup_conflict(self):
        output = self.checkpoint(prompt='מעכשיו Keep controls visible.')
        self.assertEqual(output['proposal']['status'], 'pending')
        state = self.broker.store.load()
        self.assertEqual(state['preferences'][0]['scope'], 'unscoped')
        self.assertEqual(self.broker.call('read_scoped_policy', {'scope': 'unscoped'})['rules'], [])
        self.assertFalse((self.root/'standards').exists())
        self.proposal()
        self.assertTrue(self.proposal()['duplicate'])
        with self.assertRaises(mcp.cli.LearningError):
            self.proposal(rule='A conflicting instruction.')
        self.assertEqual(len(self.broker.store.load()['preferences']), 2)

    def test_agent_and_scheduled_spoofs_are_excluded(self):
        for extra in ({'agent_id': 'worker'}, {'agent_id': ''}, {'scheduled': True}, {'source': 'automation'}):
            self.assertTrue(self.checkpoint(prompt='remember Apply this globally.', **extra)['skipped'])
        self.assertFalse((self.root/'state.json').exists())
        self.assertFalse((self.root/'mcp-receipts.json').exists())

    def test_ids_traversal_secrets_unknown_arguments_rejected(self):
        bad = ({'session_id': '${session_id}'}, {'turn_id': '{{turn}}'}, {'turn_id': 'x'*161},
               {'prompt': 'remember api_key=private'}, {'prompt': 'remember bearer shorttoken'},
               {'prompt': 'remember ' + 'x'*201}, {'path': '/tmp/private'})
        for extra in bad:
            with self.subTest(extra=extra), self.assertRaises(mcp.cli.LearningError):
                self.checkpoint(**extra)
        for scope in ('../secret', '/tmp', 'source/archive'):
            with self.assertRaises(mcp.cli.LearningError):
                self.broker.call('read_scoped_policy', {'scope': scope})
        for rule in ('token=private', 'password=private', 'sk-abcdef'):
            with self.assertRaises(mcp.cli.LearningError):
                self.proposal(rule=rule)

    def test_new_process_sees_current_approved_policy_and_changed_fingerprint(self):
        before = self.checkpoint()['receipt']['policy_fingerprint']
        self.proposal()
        self.assertEqual(self.cli('approve', 'p0001', '--approved', '--approval', 'Reviewed wording'), 0)
        result = self.process([self.initialize(), self.request('read_scoped_policy', {'scope': 'quality'})])
        data = json.loads(result[1]['result']['content'][0]['text'])
        self.assertEqual(data['rules'][0]['rule'], 'Use readable evidence.')
        self.assertNotEqual(before, data['policy_fingerprint'])
        (self.root/'standards/quality.md').write_text('Changed outside approval')
        with self.assertRaises(mcp.cli.LearningError):
            self.broker.call('learning_status', {})

    def test_incomplete_approval_and_pending_projection_rejected(self):
        self.proposal()
        path = self.root/'standards/quality.md'
        path.parent.mkdir()
        path.write_text('# Header\n\n## Approved preference p0001\n\nUse readable evidence.\n\n'
                        'Approval: user-confirmed via explicit --approved flag (reviewed)\n')
        with self.assertRaises(mcp.cli.LearningError):
            self.broker.call('read_scoped_policy', {'scope': 'quality'})
        state = self.broker.store.load()
        state['preferences'][0]['status'] = 'approved'
        self.broker.store.save(state)
        with self.assertRaises(mcp.cli.LearningError):
            self.broker.call('read_scoped_policy', {'scope': 'quality'})

    def test_unsafe_files_fifo_symlinks_size_rejected(self):
        outside = self.base/'outside'
        outside.mkdir()
        link = self.base/'linked'
        link.symlink_to(outside)
        with self.assertRaises(mcp.cli.LearningError):
            mcp.Broker(link/'state')
        for kind in ('fifo', 'symlink', 'oversize'):
            path = self.root/'mcp-receipts.json'
            if kind == 'fifo':
                os.mkfifo(path)
            elif kind == 'symlink':
                path.symlink_to(outside/'private')
            else:
                path.write_bytes(b'x'*(mcp.cli.MAX_STATE+1))
            with self.assertRaises(mcp.cli.LearningError):
                self.checkpoint()
            path.unlink()

    def fill_receipts(self):
        for i in range(100):
            self.checkpoint(session_id='session-%d' % i, turn_id='turn-%d' % i, prompt='Private chat text')
        return (self.root/'mcp-receipts.json').read_bytes()

    def archive_path(self, raw):
        return self.root/'Old'/mcp.dt.datetime.now().strftime('%Y-%m')/('receipts-'+hashlib.sha256(raw).hexdigest()+'.json')

    def test_capacity_archives_exact_history_then_retains_newest_and_captures(self):
        before = self.fill_receipts()
        originals = json.loads(before)['receipts']
        result = self.checkpoint(session_id='new-session', turn_id='new-turn', prompt='remember Capture beyond capacity.')
        self.assertEqual(result['proposal']['status'], 'pending')
        archive = self.archive_path(before)
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual(len(json.loads(archive.read_bytes())['receipts']), 100)
        status = self.broker.call('learning_status', {})
        self.assertEqual(status['receipt_count'], 65)
        self.assertEqual(status['archived_batches'], 1)
        self.assertFalse(status['maintenance_required'])
        self.assertIn(mcp.digest('new-session'), self.broker.receipts()['receipts'])
        expected = set(key for key, _ in sorted(originals.items(), key=lambda item: item[1]['last_observed_at'])[-64:])
        self.assertEqual(set(self.broker.receipts()['receipts']) - {mcp.digest('new-session')}, expected)
        self.assertNotIn('Private chat text', archive.read_text())
        self.assertNotIn('Capture beyond capacity', archive.read_text())

    def test_archive_changed_bytes_and_symlink_refused_without_escape(self):
        before = self.fill_receipts()
        archive = self.archive_path(before)
        archive.parent.mkdir(parents=True)
        archive.write_text('Changed archive bytes')
        with self.assertRaises(mcp.cli.LearningError):
            self.checkpoint(session_id='blocked')
        self.assertEqual((self.root/'mcp-receipts.json').read_bytes(), before)
        self.assertEqual(archive.read_text(), 'Changed archive bytes')
        # A linked month cannot redirect archive creation outside the owned root.
        archive.unlink()
        archive.parent.rmdir()
        outside = self.base/'outside-archives'
        outside.mkdir()
        archive.parent.symlink_to(outside)
        with self.assertRaises(mcp.cli.LearningError):
            self.checkpoint(session_id='blocked')
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual((self.root/'mcp-receipts.json').read_bytes(), before)

    def test_interrupted_active_commit_retries_same_exact_archive_safely(self):
        before = self.fill_receipts()
        original_write = mcp.cli.atomic_write
        def interrupt_active(path, data):
            if path == self.broker.receipt_file:
                raise OSError('Interrupted active commit')
            return original_write(path, data)
        with patch.object(mcp.cli, 'atomic_write', side_effect=interrupt_active):
            with self.assertRaises(OSError):
                self.checkpoint(session_id='after-crash', prompt='remember Keep deduplication safe.')
        self.assertEqual(self.archive_path(before).read_bytes(), before)
        self.assertEqual((self.root/'mcp-receipts.json').read_bytes(), before)
        result = self.checkpoint(session_id='after-crash', prompt='remember Keep deduplication safe.')
        self.assertTrue(result['proposal']['duplicate'])
        self.assertEqual(len(self.broker.store.load()['preferences']), 1)
        self.assertEqual(len(self.broker.receipts()['receipts']), 65)
        self.assertEqual(len(list((self.root/'Old').rglob('receipts-*.json'))), 1)

    def test_malformed_and_large_lines_bounded_recover_to_next_request(self):
        responses = self.process(['{bad', 'x'*(mcp.MAX_LINE*3), '[]', self.initialize(),
                                  self.request('learning_status'), self.request('learning_status', {'path': '/private/input'})])
        self.assertEqual(len(responses), 6)
        self.assertEqual(responses[0]['error']['code'], -32700)
        self.assertEqual(responses[1]['error']['code'], -32700)
        self.assertEqual(responses[2]['error']['code'], -32600)
        self.assertFalse(responses[4]['result'].get('isError'))
        self.assertTrue(responses[5]['result']['isError'])
        self.assertNotIn('/private/input', json.dumps(responses))

    def test_one_session_continues_capture_after_101_turns_and_policy_refresh(self):
        first = self.checkpoint(turn_id='first')['receipt']
        for i in range(101):
            result = self.checkpoint(turn_id='turn-%d' % i, prompt='remember Use fixture rule %d.' % i)
            self.assertEqual(result['proposal']['status'], 'pending')
        status = self.broker.call('learning_status', {})
        self.assertEqual(status['receipt_count'], 1)
        self.assertEqual(status['pending'], 101)
        latest = self.broker.receipts()['receipts'][first['receipt_id']]
        self.assertEqual(latest['first_turn_hash'], first['turn_hash'])
        self.assertEqual(latest['observed_at'], first['observed_at'])
        self.assertEqual(self.cli('approve', 'p0001', '--approved', '--approval', 'Reviewed exact rule'), 0)
        refreshed = self.checkpoint(turn_id='turn-100')['receipt']
        self.assertNotEqual(refreshed['policy_fingerprint'], latest['policy_fingerprint'])
        self.assertEqual(len(self.broker.receipts()['receipts']), 1)
        self.checkpoint(turn_id='turn-1', prompt='remember Use fixture rule 1.')
        self.assertEqual(len(self.broker.store.load()['preferences']), 101)

    def test_hook_format_chat_material_duplicates_agents_and_errors(self):
        self.assertEqual(self.checkpoint(as_hook=True, prompt='Hello'), {})
        material = self.checkpoint(as_hook=True, turn_id='material', prompt='Build a test system')
        self.assertEqual(set(material), {'hookSpecificOutput'})
        hook = material['hookSpecificOutput']
        self.assertEqual(hook['hookEventName'], 'UserPromptSubmit')
        self.assertLessEqual(len(hook['additionalContext']), 40)
        self.assertIn('read_scoped_policy', hook['additionalContext'])
        before = (self.root/'mcp-receipts.json').read_bytes()
        self.assertEqual(material, self.checkpoint(as_hook=True, turn_id='material', prompt='Build a test system'))
        self.assertEqual(before, (self.root/'mcp-receipts.json').read_bytes())
        self.assertEqual(self.checkpoint(as_hook=True, prompt='Build something', agent_id='worker'), {})
        result = self.process([self.initialize(), self.request('prompt_checkpoint',
                              {'session_id': '${missing}', 'turn_id': 't', 'as_hook': True})])
        self.assertTrue(result[-1]['result']['isError'])
        self.assertEqual(json.loads(result[-1]['result']['content'][0]['text']), {})

    def test_concurrent_stdio_proposals_share_cli_transaction_lock(self):
        requests = [self.initialize(), self.request('propose_rule', {
            'scope': 'quality', 'rule': 'One exact shared proposal.', 'source_ref': 'concurrent:one'})]
        data = '\n'.join(json.dumps(r) for r in requests) + '\n'
        commands = [sys.executable, '-B', str(ROOT/'learning/mcp_server.py'), '--state-dir', str(self.root)]
        processes = [subprocess.Popen(commands, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(5)]
        for process in processes:
            process.stdin.write(data)
            process.stdin.close()
        for process in processes:
            self.assertEqual(process.wait(timeout=10), 0, process.stderr.read())
            responses = [json.loads(line) for line in process.stdout]
            self.assertFalse(responses[-1]['result'].get('isError'))
            process.stdout.close()
            process.stderr.close()
        self.assertEqual(len(self.broker.store.load()['preferences']), 1)

    def test_operator_root_whitelist_and_live_policy_changes(self):
        policy = self.base/'policy'
        (policy/'references').mkdir(parents=True)
        (policy/'references/quality.md').write_text('First operator policy.')
        (policy/'source').mkdir()
        (policy/'source/private.md').write_text('Private source archive.')
        args = ('--policy-root', str(policy))
        requests = [self.initialize(), self.request('read_scoped_policy', {'scope': 'quality'})]
        first = json.loads(self.process(requests, args)[1]['result']['content'][0]['text'])
        self.assertEqual(first['policy'], 'First operator policy.')
        (policy/'references/quality.md').write_text('Updated operator policy.')
        second = json.loads(self.process(requests, args)[1]['result']['content'][0]['text'])
        self.assertEqual(second['policy'], 'Updated operator policy.')
        self.assertNotEqual(first['policy_fingerprint'], second['policy_fingerprint'])
        broker = mcp.Broker(self.root, policy)
        self.assertEqual(broker.call('read_scoped_policy', {'scope': 'private'})['rules'], [])
        with self.assertRaises(FileNotFoundError):
            mcp.Broker(self.root, self.base/'missing-policy')
        self.assertFalse((self.base/'missing-policy').exists())
        (policy/'references/quality.md').unlink()
        (policy/'references/quality.md').symlink_to(policy/'source/private.md')
        with self.assertRaises(mcp.cli.LearningError):
            broker.call('read_scoped_policy', {'scope': 'quality'})


if __name__ == '__main__':
    unittest.main()

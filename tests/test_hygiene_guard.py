"""Independent acceptance tests for scripts/hygiene_guard.py."""

import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / 'scripts' / 'hygiene_guard.py'
if not GUARD_PATH.exists():
    GUARD_PATH = ROOT / 'claude-plugin' / 'workflow-hooks-kit' / 'scripts' / 'hygiene_guard.py'
if GUARD_PATH.exists():
    spec = importlib.util.spec_from_file_location('hygiene_guard', GUARD_PATH)
    guard = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = guard
    spec.loader.exec_module(guard)
else:
    guard = None

SCRIPTS = GUARD_PATH.parent
if SCRIPTS.exists():
    sys.path.insert(0, str(SCRIPTS))
    import hygiene_adapter
    import tool_scope_hook
else:
    hygiene_adapter = None
    tool_scope_hook = None


def digest(data):
    return hashlib.sha256(data).hexdigest()


class HygieneGuardAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hygiene-guard-', dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / 'project'
        self.project.mkdir()
        self.state = self.home / 'runtime-state'
        self.state.mkdir(mode=0o700)
        self.payload = {
            'cwd': str(self.project),
            'session_id': 'acceptance-session',
            'turn_id': 'acceptance-turn',
        }

    def require_guard(self):
        if guard is None:
            self.fail(f'hygiene guard implementation not found at {GUARD_PATH}')

    def require_adapter(self):
        self.require_guard()
        if hygiene_adapter is None or tool_scope_hook is None:
            self.fail(f'hygiene adapter/core scripts not found beside {GUARD_PATH}')

    def enable_hygiene(self):
        policy = self.state / 'hygiene-policy.json'
        policy.write_text(json.dumps({'schema': 1, 'mode': 'enforce'}), encoding='utf-8')
        policy.chmod(0o600)

    def adapt(self, payload, delegate=lambda: {}):
        return hygiene_adapter.run(tool_scope_hook, payload, self.state, delegate)

    def run_core_isolated(self, payload):
        code = (
            'import json,sys; sys.path.insert(0,sys.argv[1]); '
            'import tool_scope_hook as core; '
            'print(json.dumps(core.run(json.load(sys.stdin))))'
        )
        return subprocess.run(
            [sys.executable, '-B', '-c', code, str(SCRIPTS)],
            input=json.dumps(payload), text=True, capture_output=True, timeout=10,
            env={**os.environ, 'HOME': str(self.home)},
        )

    def enable_core_hygiene(self):
        state = self.home / '.codex' / 'workflow-hooks-kit' / 'state'
        state.mkdir(parents=True, mode=0o700)
        policy = state / 'hygiene-policy.json'
        policy.write_text(json.dumps({'schema': 1, 'mode': 'enforce'}), encoding='utf-8')
        policy.chmod(0o600)
        return state

    def adapter_preflight(self, path, content_hash=None, decision='keep', **extra):
        body = self.review_body(path, content_hash, decision, **extra)
        return guard.review(self.payload, self.state / 'hygiene', body)

    def review_body(self, path, content_hash, decision='keep', **extra):
        return {
            'entries': [{
                'path': str(path),
                'decision': decision,
                'reason': 'Acceptance fixture review.',
                'sha256': content_hash,
                'usage': 'Required working file for this fixture.',
                'dependencies': 'No known dependent files.',
                'concurrency': 'No concurrent writer in this isolated fixture.',
                **extra,
            }],
        }

    def preflight(self, path, content_hash=None, decision='keep', **extra):
        return guard.review(self.payload, self.state, self.review_body(path, content_hash, decision, **extra))

    def postreview(self, path, content_hash=None, decision='keep', **extra):
        return guard.review(self.payload, self.state, self.review_body(path, content_hash, decision, **extra))

    def find_manifest(self, original, purpose=None):
        for path in (self.project / 'Old').rglob('manifest.json'):
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('original') == original and (purpose is None or data.get('purpose') == purpose):
                return path, data
        self.fail(f'no archived manifest for {original!r} with purpose {purpose!r}')

    @staticmethod
    def denied(result):
        return (
            isinstance(result, dict)
            and (
                result.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'
                or result.get('decision') == 'block'
            )
        )

    def test_first_edit_is_denied_until_preflight_review_exists(self):
        self.require_guard()
        target = self.project / 'new.txt'
        result = guard.pre_edit(self.payload, self.state, [str(target)])
        self.assertTrue(self.denied(result), result)
        self.assertFalse(target.exists())

    def test_preflight_accepts_absent_target_then_allows_first_edit(self):
        self.require_guard()
        target = self.project / 'new.txt'
        self.assertFalse(self.denied(self.preflight(target, None)))
        self.assertEqual(guard.pre_edit(self.payload, self.state, [str(target)]), {})
        self.assertFalse(target.exists())

    def test_existing_target_is_backed_up_byte_for_byte_before_edit(self):
        self.require_guard()
        target = self.project / 'source.txt'
        original = b'\x00old bytes\xff\n'
        target.write_bytes(original)
        self.assertFalse(self.denied(self.preflight(target, digest(original))))
        self.assertEqual(guard.pre_edit(self.payload, self.state, [str(target)]), {})
        month = datetime.now(ZoneInfo('Asia/Jerusalem')).strftime('%Y-%m')
        backups = list((self.project / 'Old' / month).rglob('*'))
        self.assertTrue(backups, 'existing file should have a recoverable Old/YYYY-MM backup')
        self.assertIn(original, [p.read_bytes() for p in backups if p.is_file()])

    def test_next_edit_is_blocked_while_post_edit_review_is_pending(self):
        self.require_guard()
        target = self.project / 'source.txt'
        target.write_bytes(b'before')
        self.preflight(target, digest(b'before'))
        self.assertEqual(guard.pre_edit(self.payload, self.state, [str(target)]), {})
        result = guard.pre_edit(self.payload, self.state, [str(target)])
        self.assertTrue(self.denied(result), result)
        self.assertEqual(target.read_bytes(), b'before')

    def test_stop_is_blocked_while_review_is_pending_even_if_stop_hook_is_active(self):
        self.require_guard()
        target = self.project / 'source.txt'
        target.write_bytes(b'before')
        self.preflight(target, digest(b'before'))
        guard.pre_edit(self.payload, self.state, [str(target)])
        for active in (False, True):
            with self.subTest(stop_hook_active=active):
                result = guard.stop({**self.payload, 'stop_hook_active': active}, self.state)
                self.assertTrue(self.denied(result), result)

    def test_keep_postreview_permits_the_next_edit(self):
        self.require_guard()
        target = self.project / 'source.txt'
        target.write_bytes(b'before')
        self.preflight(target, digest(b'before'))
        guard.pre_edit(self.payload, self.state, [str(target)])
        target.write_bytes(b'after')
        self.assertFalse(self.denied(self.postreview(target, digest(b'after'))))
        self.assertEqual(guard.pre_edit(self.payload, self.state, [str(target)]), {})

    def test_reviewed_file_drift_invalidates_stop(self):
        self.require_guard()
        target = self.project / 'source.txt'
        target.write_bytes(b'before')
        self.preflight(target, digest(b'before'))
        guard.pre_edit(self.payload, self.state, [str(target)])
        target.write_bytes(b'after')
        self.postreview(target, digest(b'after'))
        target.write_bytes(b'unreviewed drift')
        self.assertTrue(self.denied(guard.stop(self.payload, self.state)))

    def test_corrupt_state_fails_closed_without_changing_target(self):
        self.require_guard()
        target = self.project / 'source.txt'
        target.write_bytes(b'before')
        self.preflight(target, digest(b'before'))
        guard.pre_edit(self.payload, self.state, [str(target)])
        state_files = [p for p in self.state.rglob('*') if p.is_file() and p.suffix != '.lock']
        self.assertTrue(state_files, 'guard should persist review state')
        state_files[0].write_bytes(b'{corrupt state')
        before = target.read_bytes()
        result = guard.pre_edit(self.payload, self.state, [str(target)])
        self.assertTrue(self.denied(result), result)
        self.assertEqual(target.read_bytes(), before)

    def test_symlink_target_is_refused(self):
        self.require_guard()
        referent = self.project / 'referent.txt'
        referent.write_bytes(b'keep me')
        target = self.project / 'alias.txt'
        target.symlink_to(referent)
        result = guard.pre_edit(self.payload, self.state, [str(target)])
        self.assertTrue(self.denied(result), result)
        self.assertEqual(referent.read_bytes(), b'keep me')

    def test_symlink_ancestor_is_refused(self):
        self.require_guard()
        outside = self.home / 'outside'
        outside.mkdir()
        target = outside / 'source.txt'
        target.write_bytes(b'keep me')
        alias = self.project / 'linked-dir'
        alias.symlink_to(outside, target_is_directory=True)
        result = guard.pre_edit(self.payload, self.state, [str(alias / 'source.txt')])
        self.assertTrue(self.denied(result), result)
        self.assertEqual(target.read_bytes(), b'keep me')

    def test_outside_project_path_is_refused_without_data_loss(self):
        self.require_guard()
        outside = self.home / 'outside.txt'
        original = b'outside project'
        outside.write_bytes(original)
        result = guard.pre_edit(self.payload, self.state, [str(outside)])
        self.assertTrue(self.denied(result), result)
        self.assertEqual(outside.read_bytes(), original)

    def test_archive_of_identical_unreferenced_media_duplicate_is_byte_exact(self):
        self.require_guard()
        source = self.project / 'photo.png'
        duplicate = self.project / 'photo-copy.png'
        data = b'\x89PNG\r\nfixture-image-bytes'
        source.write_bytes(data)
        duplicate.write_bytes(data)
        body = self.review_body(
            duplicate, digest(data), decision='archive',
            canonical=str(source), canonical_sha256=digest(data),
        )
        result = guard.review(self.payload, self.state, body)
        self.assertFalse(self.denied(result), result)
        self.assertTrue(source.exists())
        self.assertEqual(source.read_bytes(), data)
        self.assertFalse(duplicate.exists())
        archived = [
            p for p in (self.project / 'Old').rglob(duplicate.name)
            if p.is_file()
        ]
        self.assertTrue(archived, 'reviewed duplicate should have a recoverable archive copy')
        self.assertEqual([p.read_bytes() for p in archived], [data])

    def test_archive_refuses_case_only_alias_when_paths_are_the_same_file(self):
        self.require_guard()
        canonical = self.project / 'photo.png'
        candidate = self.project / 'PHOTO.PNG'
        data = b'one live image under two case aliases'
        canonical.write_bytes(data)
        if not candidate.exists() or not os.path.samefile(canonical, candidate):
            self.skipTest('filesystem treats case-only paths as distinct files')
        old = self.project / 'Old'
        before_old = sorted(str(path.relative_to(self.project)) for path in old.rglob('*')) if old.exists() else []
        body = self.review_body(
            candidate, digest(data), decision='archive',
            canonical=str(canonical), canonical_sha256=digest(data),
        )
        result = guard.review(self.payload, self.state, body)
        self.assertTrue(self.denied(result), result)
        self.assertTrue(canonical.exists())
        self.assertTrue(candidate.exists())
        self.assertTrue(os.path.samefile(canonical, candidate))
        self.assertEqual(canonical.read_bytes(), data)
        after_old = sorted(str(path.relative_to(self.project)) for path in old.rglob('*')) if old.exists() else []
        self.assertEqual(after_old, before_old, 'same-file alias must be refused before archival')

    def test_review_refuses_two_case_alias_entries_for_the_same_file(self):
        self.require_guard()
        canonical = self.project / 'photo.png'
        alias = self.project / 'PHOTO.PNG'
        data = b'one file cannot have two review identities'
        canonical.write_bytes(data)
        if not alias.exists() or not os.path.samefile(canonical, alias):
            self.skipTest('filesystem treats case-only paths as distinct files')
        entries = [
            self.review_body(canonical, digest(data))['entries'][0],
            self.review_body(alias, digest(data))['entries'][0],
        ]
        result = guard.review(self.payload, self.state, {'entries': entries})
        self.assertTrue(self.denied(result), result)
        self.assertTrue(canonical.exists())
        self.assertTrue(alias.exists())
        self.assertTrue(os.path.samefile(canonical, alias))
        self.assertEqual(canonical.read_bytes(), data)
        self.assertFalse((self.project / 'Old').exists())

    def test_asset_transfer_preserves_hash_and_recoverable_old_copy(self):
        self.require_guard()
        source = self.project / 'design' / 'logo.png'
        source.parent.mkdir()
        data = b'asset transfer bytes'
        source.write_bytes(data)
        result = self.preflight(source, digest(data), decision='asset')
        self.assertFalse(self.denied(result), result)
        destination = self.project / 'Assets' / 'design' / 'logo.png'
        self.assertFalse(source.exists())
        self.assertEqual(destination.read_bytes(), data)
        manifest_path, manifest = self.find_manifest('design/logo.png', 'asset-relocation')
        self.assertEqual(manifest['sha256'], digest(data))
        self.assertEqual(manifest['archive'], (manifest_path.parent / 'files' / 'design' / 'logo.png').relative_to(self.project).as_posix())
        self.assertEqual((self.project / manifest['archive']).read_bytes(), data)

    def test_asset_referenced_by_project_text_is_refused_without_moving_it(self):
        self.require_guard()
        source = self.project / 'design' / 'logo.png'
        source.parent.mkdir()
        data = b'referenced asset bytes'
        source.write_bytes(data)
        (self.project / 'README.md').write_text('Load design/logo.png for the page.\n', encoding='utf-8')
        result = self.preflight(source, digest(data), decision='asset')
        self.assertTrue(self.denied(result), result)
        self.assertEqual(source.read_bytes(), data)
        self.assertFalse((self.project / 'Assets' / 'design' / 'logo.png').exists())
        self.assertFalse((self.project / 'Old').exists())

    def test_restore_from_manifest_restores_absent_original_and_requires_review(self):
        self.require_guard()
        canonical = self.project / 'canonical.png'
        duplicate = self.project / 'duplicate.png'
        data = b'restore source bytes'
        canonical.write_bytes(data)
        duplicate.write_bytes(data)
        archive_result = self.preflight(
            duplicate, digest(data), decision='archive', canonical=str(canonical),
            canonical_sha256=digest(data),
        )
        self.assertFalse(self.denied(archive_result), archive_result)
        self.assertFalse(duplicate.exists())
        manifest_path, manifest = self.find_manifest('duplicate.png', 'reviewed-duplicate')
        manifest_rel = manifest_path.relative_to(self.project).as_posix()
        restore_result = guard.restore(self.payload, self.state, {'manifest': manifest_rel})
        self.assertEqual(restore_result, {})
        self.assertEqual(duplicate.read_bytes(), data)
        self.assertEqual((self.project / manifest['archive']).read_bytes(), data)
        self.assertTrue(self.denied(guard.stop(self.payload, self.state)))
        self.assertFalse(self.denied(self.postreview(duplicate, digest(data))))
        self.assertEqual(guard.stop(self.payload, self.state), {})

    def test_restore_refuses_existing_original_without_overwriting_it(self):
        self.require_guard()
        canonical = self.project / 'canonical.png'
        duplicate = self.project / 'duplicate.png'
        data = b'archived duplicate bytes'
        canonical.write_bytes(data)
        duplicate.write_bytes(data)
        self.preflight(
            duplicate, digest(data), decision='archive', canonical=str(canonical),
            canonical_sha256=digest(data),
        )
        manifest_path, manifest = self.find_manifest('duplicate.png', 'reviewed-duplicate')
        live = b'current replacement bytes'
        duplicate.write_bytes(live)
        result = guard.restore(self.payload, self.state, {
            'manifest': manifest_path.relative_to(self.project).as_posix(),
        })
        self.assertTrue(self.denied(result), result)
        self.assertEqual(duplicate.read_bytes(), live)
        self.assertEqual((self.project / manifest['archive']).read_bytes(), data)

    def test_uncertain_preflight_stays_pending_across_stop_and_next_edit(self):
        self.require_guard()
        target = self.project / 'uncertain.txt'
        target.write_bytes(b'uncertain usage')
        result = self.preflight(target, digest(b'uncertain usage'), decision='uncertain')
        self.assertTrue(self.denied(result), result)
        self.assertTrue(self.denied(guard.stop(self.payload, self.state)))
        next_edit = self.project / 'next.txt'
        self.assertTrue(self.denied(guard.pre_edit(self.payload, self.state, [str(next_edit)])))
        self.assertEqual(target.read_bytes(), b'uncertain usage')
        self.assertFalse(next_edit.exists())

    def test_pending_review_from_one_session_blocks_another_session_edit(self):
        self.require_guard()
        target = self.project / 'source.txt'
        target.write_bytes(b'pending bytes')
        self.preflight(target, digest(b'pending bytes'))
        self.assertEqual(guard.pre_edit(self.payload, self.state, [str(target)]), {})
        other_session = {**self.payload, 'session_id': 'different-session', 'turn_id': 'different-turn'}
        other_target = self.project / 'other.txt'
        result = guard.pre_edit(other_session, self.state, [str(other_target)])
        self.assertTrue(self.denied(result), result)
        self.assertFalse(other_target.exists())
        self.assertEqual(target.read_bytes(), b'pending bytes')

    def test_core_exec_command_alias_denies_chained_ledger_sentinel_before_shell(self):
        self.require_adapter()
        self.enable_core_hygiene()
        target = self.project / 'next.txt'
        payload = {
            **self.payload, 'hook_event_name': 'PreToolUse', 'tool_name': 'functions.exec_command',
            'tool_input': {'cmd': 'workflow-ledger start substantial; touch next.txt'},
        }
        result = self.run_core_isolated(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)
        self.assertTrue(self.denied(decision), decision)
        self.assertFalse(target.exists())
        state = self.home / '.codex' / 'workflow-hooks-kit' / 'state'
        self.assertEqual(list(state.glob('*.json')), [state / 'hygiene-policy.json'])

    def test_core_exec_command_alias_saves_compact_plan_and_intercepts_sentinel(self):
        self.require_adapter()
        self.enable_core_hygiene()
        plan = {
            'definition_of_done': 'Create the requested text file',
            'outputs': ['notes.txt'],
            'qa': {'check': 'Read notes.txt', 'expected': 'Contains the requested text'},
        }
        command = 'workflow-ledger plan ' + shlex.quote(json.dumps(plan))
        payload = {
            **self.payload, 'hook_event_name': 'PreToolUse', 'tool_name': 'functions.exec_command',
            'tool_input': {'cmd': command},
        }
        result = self.run_core_isolated(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)
        self.assertTrue(self.denied(decision), decision)
        reason = decision['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn('Plan saved', reason)
        state = self.home / '.codex' / 'workflow-hooks-kit' / 'state'
        ledgers = [
            path for path in state.glob('*.json')
            if path.name != 'hygiene-policy.json'
            and not path.name.endswith('.active.json')
            and json.loads(path.read_text(encoding='utf-8')).get('session_id') == self.payload['session_id']
        ]
        self.assertEqual(len(ledgers), 1, [str(path) for path in ledgers])
        saved = json.loads(ledgers[0].read_text(encoding='utf-8'))
        self.assertEqual(saved['task_kind'], 'small')
        self.assertEqual(saved['definition_of_done'], plan['definition_of_done'])
        self.assertEqual(saved['outputs'], plan['outputs'])
        self.assertEqual(saved['qa']['verdict'], 'pending')
        self.assertFalse((self.project / 'notes.txt').exists())

    def test_archive_refuses_nonidentical_duplicate_without_moving_either_file(self):
        self.require_guard()
        source = self.project / 'photo.png'
        duplicate = self.project / 'photo-copy.png'
        source.write_bytes(b'canonical image')
        duplicate.write_bytes(b'different image')
        result = self.preflight(
            duplicate, digest(b'different image'), decision='archive',
            canonical=str(source), canonical_sha256=digest(b'canonical image'),
        )
        self.assertTrue(self.denied(result), result)
        self.assertEqual(source.read_bytes(), b'canonical image')
        self.assertEqual(duplicate.read_bytes(), b'different image')

    def test_archive_refuses_source_or_configuration_files(self):
        self.require_guard()
        for name in ('module.py', 'settings.json', 'secrets.env'):
            with self.subTest(name=name):
                target = self.project / name
                data = b'preserve required source/configuration'
                target.write_bytes(data)
                result = self.preflight(target, digest(data), decision='archive')
                self.assertTrue(self.denied(result), result)
                self.assertEqual(target.read_bytes(), data)

    def test_archive_refuses_duplicate_referenced_by_project_text(self):
        self.require_guard()
        source = self.project / 'photo.png'
        duplicate = self.project / 'photo-copy.png'
        data = b'image bytes'
        source.write_bytes(data)
        duplicate.write_bytes(data)
        (self.project / 'README.md').write_text('Use photo-copy.png in the guide.\n', encoding='utf-8')
        result = self.preflight(
            duplicate, digest(data), decision='archive',
            canonical=str(source), canonical_sha256=digest(data),
        )
        self.assertTrue(self.denied(result), result)
        self.assertTrue(source.exists())
        self.assertTrue(duplicate.exists())

    def test_review_requires_entries_for_pending_paths_and_matching_hash(self):
        self.require_guard()
        target = self.project / 'source.txt'
        target.write_bytes(b'before')
        self.preflight(target, digest(b'before'))
        guard.pre_edit(self.payload, self.state, [str(target)])
        incomplete = guard.review(self.payload, self.state, {'entries': []})
        self.assertTrue(self.denied(incomplete), incomplete)
        wrong_hash = self.postreview(target, digest(b'wrong'))
        self.assertTrue(self.denied(wrong_hash), wrong_hash)
        self.assertTrue(self.denied(guard.stop(self.payload, self.state)))

    def test_opt_in_policy_denies_first_write_until_preflight(self):
        self.require_adapter()
        self.enable_hygiene()
        target = self.project / 'new.txt'
        result = self.adapt({
            **self.payload, 'hook_event_name': 'PreToolUse', 'tool_name': 'Write',
            'tool_input': {'file_path': str(target), 'content': 'new'},
        })
        self.assertTrue(self.denied(result), result)
        self.assertFalse(target.exists())

    def test_symlink_input_does_not_resolve_to_a_preflight_reviewed_canonical_path(self):
        self.require_adapter()
        self.enable_hygiene()
        canonical = self.project / 'canonical.txt'
        canonical.write_bytes(b'keep these bytes')
        alias = self.project / 'alias.txt'
        alias.symlink_to(canonical)
        self.assertFalse(self.denied(self.adapter_preflight(canonical, digest(b'keep these bytes'))))
        result = self.adapt({
            **self.payload, 'hook_event_name': 'PreToolUse', 'tool_name': 'Write',
            'tool_input': {'file_path': str(alias), 'content': 'replace'},
        })
        self.assertTrue(self.denied(result), result)
        self.assertTrue(alias.is_symlink())
        self.assertEqual(canonical.read_bytes(), b'keep these bytes')

    def test_risky_bash_is_blocked_without_calling_baseline(self):
        self.require_adapter()
        self.enable_hygiene()
        calls = []
        result = self.adapt({
            **self.payload, 'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
            'tool_input': {'command': 'echo unsafe > output.txt'},
        }, delegate=lambda: calls.append('called') or {})
        self.assertTrue(self.denied(result), result)
        self.assertEqual(calls, [])
        self.assertFalse((self.project / 'output.txt').exists())

    def test_native_shell_command_aliases_are_blocked_without_delegation(self):
        self.require_adapter()
        self.enable_hygiene()
        for tool in ('functions.exec_command', 'functions.shell_command'):
            with self.subTest(tool=tool):
                calls = []
                result = self.adapt({
                    **self.payload, 'hook_event_name': 'PreToolUse', 'tool_name': tool,
                    'tool_input': {'command': 'echo unsafe > output.txt'},
                }, delegate=lambda: calls.append('called') or {})
                self.assertTrue(self.denied(result), result)
                self.assertEqual(calls, [])
                self.assertFalse((self.project / 'output.txt').exists())

    def test_adapter_import_failure_denies_risky_native_operation(self):
        self.require_adapter()
        isolated_scripts = self.home / 'isolated-scripts'
        isolated_scripts.mkdir()
        for name in ('tool_scope_hook.py', 'session_workflow_hook.py', 'delegation_gate.py'):
            shutil.copy2(SCRIPTS / name, isolated_scripts / name)
        # Deliberately omit hygiene_adapter.py to exercise the core's real import error path.
        receipt_state = self.home / '.codex' / 'workflow-hooks-kit' / 'state'
        receipt_state.mkdir(parents=True, mode=0o700)
        policy = receipt_state / 'hygiene-policy.json'
        policy.write_text(json.dumps({'schema': 1, 'mode': 'enforce'}), encoding='utf-8')
        policy.chmod(0o600)
        code = (
            'import json,sys; sys.path.insert(0,sys.argv[1]); '
            'import tool_scope_hook as core; '
            'p={"cwd":sys.argv[2],"session_id":"s","turn_id":"t",'
            '"hook_event_name":"PreToolUse","tool_name":"Bash",'
            '"tool_input":{"command":"echo unsafe > output.txt"}}; '
            'print(json.dumps(core.run(p)))'
        )
        result = subprocess.run(
            [sys.executable, '-B', '-c', code, str(isolated_scripts), str(self.project)],
            env={**os.environ, 'HOME': str(self.home)}, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)
        self.assertTrue(self.denied(decision), decision)
        self.assertFalse((self.project / 'output.txt').exists())

    def test_review_sentinel_is_intercepted_and_executes_no_shell_command(self):
        self.require_adapter()
        self.enable_hygiene()
        target = self.project / 'source.txt'
        target.write_bytes(b'unchanged')
        self.assertFalse(self.denied(self.adapter_preflight(target, digest(b'unchanged'))))
        write_result = self.adapt({
            **self.payload, 'hook_event_name': 'PreToolUse', 'tool_name': 'Write',
            'tool_input': {'file_path': str(target), 'content': 'not actually written'},
        })
        self.assertEqual(write_result, {})
        body = self.review_body(target, digest(b'unchanged'))
        command = 'workflow-hygiene review ' + shlex.quote(json.dumps(body))
        calls = []
        result = self.adapt({
            **self.payload, 'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
            'tool_input': {'command': command},
        }, delegate=lambda: calls.append('called') or {})
        self.assertTrue(self.denied(result), result)
        self.assertIn('No shell command executed', result['hookSpecificOutput']['permissionDecisionReason'])
        self.assertEqual(calls, [])
        self.assertEqual(target.read_bytes(), b'unchanged')
        self.assertEqual(guard.stop(self.payload, self.state / 'hygiene'), {})

    def test_unrelated_conversation_delegates_without_hygiene_state_mutation(self):
        self.require_adapter()
        self.enable_hygiene()
        before = sorted(str(p.relative_to(self.state)) for p in self.state.rglob('*'))
        calls = []
        payload = {**self.payload, 'hook_event_name': 'UserPromptSubmit', 'prompt': 'hello'}
        result = self.adapt(payload, delegate=lambda: calls.append('called') or {'baseline': 'ok'})
        after = sorted(str(p.relative_to(self.state)) for p in self.state.rglob('*'))
        self.assertEqual(result, {'baseline': 'ok'})
        self.assertEqual(calls, ['called'])
        self.assertEqual(after, before)

    def test_missing_policy_preserves_existing_baseline_contract(self):
        self.require_adapter()
        calls = []
        baseline = {'baseline': 'preserved'}
        result = self.adapt({
            **self.payload, 'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
            'tool_input': {'command': 'echo unsafe > output.txt'},
        }, delegate=lambda: calls.append('called') or baseline)
        self.assertIs(result, baseline)
        self.assertEqual(calls, ['called'])
        self.assertFalse((self.state / 'hygiene').exists())


if __name__ == '__main__':
    unittest.main()

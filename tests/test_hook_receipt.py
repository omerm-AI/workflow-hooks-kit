import concurrent.futures
import hashlib
import hmac
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "claude-plugin/workflow-hooks-kit/scripts"
sys.path.insert(0, str(SCRIPT))
import hook_receipt


class HookReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir(mode=0o700)
        os.chmod(self.state, 0o700)
        self.payload = {"session_id": "session-A", "prompt_id": "turn-A", "event": "UserPromptSubmit",
                        "prompt": "must never be stored", "cwd": "/private/path", "extra": {"x": 1}}

    def tearDown(self):
        self.temp.cleanup()

    def create(self):
        return hook_receipt.create(self.state, self.payload, "success", "hook-v1")

    def receipt_path(self, marker, suffix="json"):
        batch_hex, nonce = marker.split(":", 1)
        return self.state / f"batch-{batch_hex}" / f"{nonce}.{suffix}"

    def verify(self, marker, **kw):
        args = {"expected_session_id": "session-A", "expected_turn_id": "turn-A",
                "event": "UserPromptSubmit", "hook_version": "hook-v1", "expected_outcome": "success"}
        args.update(kw)
        return hook_receipt.verify(self.state, marker, **args)

    def test_receipt_is_minimal_signed_and_consumed_once(self):
        marker, receipt = self.create()
        self.assertEqual(len(marker), 49)
        self.assertEqual(receipt["nonce"], marker.split(":")[1])
        self.assertEqual(set(receipt), {"schema", "timestampUTC", "event", "sessionHash", "turnHash",
                                        "nonce", "batch", "outcome", "versionHash", "signature"})
        raw = self.receipt_path(marker).read_text()
        for secret in ("session-A", "turn-A", "must never be stored", "/private/path", "extra"):
            self.assertNotIn(secret, raw)
        self.assertEqual(len(raw), len(raw.encode("ascii")))
        self.assertEqual(self.verify(marker)["event"], "UserPromptSubmit")
        self.assertTrue(self.receipt_path(marker, "used").is_file())
        with self.assertRaises((FileNotFoundError, ValueError)):
            self.verify(marker)

    def test_wrong_expectations_and_tampering_are_rejected_without_consumption(self):
        marker, _ = self.create()
        for field, value in (("expected_session_id", "other"), ("expected_turn_id", "other"),
                             ("event", "Stop"), ("hook_version", "hook-v2"),
                             ("expected_outcome", "failure")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(marker, **{field: value})
        path = self.receipt_path(marker)
        data = json.loads(path.read_text())
        data["outcome"] = "failure"
        path.write_text(json.dumps(data))
        os.chmod(path, 0o600)
        with self.assertRaises(ValueError):
            self.verify(marker)

    def test_conflicting_or_oversized_native_ids_are_rejected(self):
        bad = dict(self.payload, turn_id="different")
        with self.assertRaises(ValueError):
            hook_receipt.create(self.state, bad, "success", "v1")
        bad = dict(self.payload, prompt_id="x" * 257)
        with self.assertRaises(ValueError):
            hook_receipt.create(self.state, bad, "success", "v1")

    def test_session_start_allows_null_turn_without_synthesizing_identity(self):
        payload = {"session_id": "session-start", "event": "SessionStart"}
        marker, receipt = hook_receipt.create(self.state, payload, "success", "hook-v1")
        self.assertIsNone(receipt["turnHash"])
        verified = hook_receipt.verify(self.state, marker, "session-start", None,
                                       "SessionStart", "hook-v1", "success")
        self.assertIsNone(verified["turnHash"])

    def test_every_non_session_start_event_requires_a_real_turn(self):
        for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
            with self.subTest(event=event), self.assertRaisesRegex(ValueError, "missing turn"):
                hook_receipt.create(self.state, {"session_id": "s", "event": event}, "success", "v1")
        payload = {"session_id": "session-start", "event": "SessionStart"}
        marker, _ = hook_receipt.create(self.state, payload, "success", "hook-v1")
        with self.assertRaisesRegex(ValueError, "missing expected turn"):
            hook_receipt.verify(self.state, marker, "session-start", None,
                                "UserPromptSubmit", "hook-v1", "success")

    def test_symlink_fifo_oversize_and_insecure_state_are_rejected(self):
        link = Path(self.temp.name) / "link"
        link.symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(OSError):
            hook_receipt.create(link, self.payload, "success", "v1")
        fifo_state = Path(self.temp.name) / "fifo-state"
        fifo_state.mkdir(mode=0o700)
        os.mkfifo(fifo_state / ".hook-receipt.key")
        with self.assertRaises(OSError):
            hook_receipt.create(fifo_state, self.payload, "success", "v1")
        marker, _ = self.create()
        path = self.receipt_path(marker)
        path.write_bytes(b"{" + b" " * (hook_receipt.MAX_FILE_BYTES + 1))
        os.chmod(path, 0o600)
        with self.assertRaises(OSError):
            self.verify(marker)
        os.chmod(self.state, 0o755)
        with self.assertRaises(OSError):
            self.create()

    def test_symlink_receipt_and_fifo_receipt_are_rejected(self):
        marker, _ = self.create()
        path = self.receipt_path(marker)
        target = self.state / "target"
        target.write_text("x")
        os.chmod(target, 0o600)
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(OSError):
            self.verify(marker)
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(OSError):
            self.verify(marker)

    def test_more_than_101_creates_rotate_and_old_marker_remains_verifiable(self):
        markers = [self.create()[0] for _ in range(205)]
        self.assertEqual(len(set(markers)), 205)
        self.assertNotEqual(markers[0].split(":")[0], markers[100].split(":")[0])
        self.assertEqual(self.verify(markers[0])["nonce"], markers[0].split(":")[1])
        batch_dirs = sorted(self.state.glob("batch-*"))
        self.assertEqual(len(batch_dirs), 3)
        for batch in batch_dirs[:-1]:
            manifest = json.loads((batch / ".manifest.json").read_text())
            self.assertEqual(len(manifest), hook_receipt.MAX_BATCH_RECEIPTS)

    def test_rotation_failure_preserves_old_receipts_and_retry_completes(self):
        markers = [self.create()[0] for _ in range(hook_receipt.MAX_BATCH_RECEIPTS)]
        old_bytes = self.receipt_path(markers[0]).read_bytes()
        write_active = hook_receipt._write_active
        calls = 0

        def fail_once(state, number):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected crash")
            return write_active(state, number)

        with patch.object(hook_receipt, "_write_active", side_effect=fail_once):
            with self.assertRaises(OSError):
                self.create()
            self.assertEqual(self.receipt_path(markers[0]).read_bytes(), old_bytes)
            new_marker, _ = self.create()
        self.assertEqual(new_marker.split(":")[0], "0000000000000002")
        self.assertEqual(self.verify(markers[0])["nonce"], markers[0].split(":")[1])
        self.assertTrue((self.state / "batch-0000000000000001" / ".manifest.json").is_file())

    def test_stale_and_future_dated_valid_signatures_are_rejected(self):
        key = (self.state / ".hook-receipt.key")

        def rewrite_signed_timestamp(marker, timestamp):
            path = self.receipt_path(marker)
            data = json.loads(path.read_text())
            data.pop("signature")
            data["timestampUTC"] = timestamp
            data["signature"] = hmac.new(key.read_bytes(), hook_receipt._canonical(data), hashlib.sha256).hexdigest()
            path.write_text(json.dumps(data))
            os.chmod(path, 0o600)

        stale, _ = self.create()
        rewrite_signed_timestamp(stale, "2000-01-01T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "stale or future-dated"):
            self.verify(stale)
        future, _ = self.create()
        rewrite_signed_timestamp(future, "2999-01-01T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "stale or future-dated"):
            self.verify(future)

    def test_concurrent_creates_have_unique_markers(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: self.create(), range(24)))
        markers = [marker for marker, _ in results]
        self.assertEqual(len(markers), len(set(markers)))
        self.assertEqual(sum(len(list(batch.glob("*.json"))) for batch in self.state.glob("batch-*")), 24)


if __name__ == "__main__":
    unittest.main()

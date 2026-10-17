import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "claude-plugin/workflow-hooks-kit/scripts"
sys.path.insert(0, str(SCRIPTS))
import delegation_observer as observer
import hook_receipt


class DelegationObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir(mode=0o700)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def payload(**updates):
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Agent",
            "tool_use_id": "tool-use-secret-id",
            "session_id": "session-secret-id",
            "prompt_id": "prompt-secret-id",
            "tool_input": {
                "prompt": "PRIVATE PROMPT CONTENT",
                "description": "private description",
                "subagent_type": "general-purpose",
                "model": "requested-model",
            },
            "tool_response": {
                "status": "completed",
                "agentId": "agent-secret-id",
                "resolvedModel": "resolved-model",
                "modelsUsed": ["resolved-model"],
                "result": "PRIVATE RESULT CONTENT",
            },
        }
        payload.update(updates)
        return payload

    def test_completed_records_metadata_hashes_and_signed_receipt(self):
        result = observer.run(self.payload(), self.state)
        self.assertIn("task QA required", result["systemMessage"])
        self.assertLessEqual(len(result["systemMessage"]), 120)
        envelope = json.loads((self.state / observer.STATE_FILE).read_text())
        marker = envelope["receiptMarker"]
        observation = envelope["observation"]
        encoded = (self.state / observer.STATE_FILE).read_text()
        for private_value in ("PRIVATE PROMPT CONTENT", "private description",
                              "PRIVATE RESULT CONTENT", "session-secret-id",
                              "prompt-secret-id", "tool-use-secret-id", "agent-secret-id"):
            self.assertNotIn(private_value, encoded)
        self.assertEqual(observation["promptHash"], observer._hash("PRIVATE PROMPT CONTENT"))
        self.assertEqual(observation["sessionHash"], observer._hash("session-secret-id"))
        self.assertEqual(observation["toolUseHash"], observer._hash("tool-use-secret-id"))
        self.assertEqual(observation["agentIdHash"], observer._hash("agent-secret-id"))
        self.assertEqual(observation["status"], "completed")
        self.assertEqual((self.state / observer.STATE_FILE).stat().st_mode & 0o777, 0o600)
        self.assertLessEqual((self.state / observer.STATE_FILE).stat().st_size, observer.MAX_FILE)
        receipt = hook_receipt.verify(
            self.state, marker, "session-secret-id", "prompt-secret-id", "PostToolUse",
            observer._receipt_version(observation), "success")
        self.assertEqual(receipt["outcome"], "success")

    def test_async_launch_is_never_reported_as_completion(self):
        payload = self.payload()
        payload["tool_response"]["status"] = "async_launched"
        result = observer.run(payload, self.state)
        self.assertIn("completion unverified", result["systemMessage"])
        saved = json.loads((self.state / observer.STATE_FILE).read_text())["observation"]
        self.assertEqual(saved["status"], "async_launched")

    def test_codex_turn_identifier_is_supported_and_conflicts_rejected(self):
        payload = self.payload(prompt_id=None, turn_id="turn-secret-id")
        result = observer.run(payload, self.state)
        self.assertIn("task QA required", result["systemMessage"])
        self.assertEqual(json.loads((self.state / observer.STATE_FILE).read_text())
                         ["observation"]["turnHash"],
                         observer._hash("turn-secret-id"))
        before = (self.state / observer.STATE_FILE).read_bytes()
        bad = self.payload(turn_id="different-turn")
        skipped = observer.run(bad, self.state)
        self.assertIn("skipped", skipped["systemMessage"])
        self.assertEqual((self.state / observer.STATE_FILE).read_bytes(), before)

    def test_multiline_prompt_is_hashed_and_receipt_binds_model_and_status(self):
        payload = self.payload()
        payload["tool_input"]["prompt"] = "Line one\nLine two\twith tab"
        self.assertIn("task QA required", observer.run(payload, self.state)["systemMessage"])
        target = self.state / observer.STATE_FILE
        envelope = json.loads(target.read_text())
        observation = envelope["observation"]
        marker = envelope["receiptMarker"]
        self.assertEqual(observation["promptHash"], observer._hash("Line one\nLine two\twith tab"))
        version = observer._receipt_version(observation)
        hook_receipt.verify(self.state, marker, "session-secret-id", "prompt-secret-id",
                            "PostToolUse", version, "success", consume=False)
        observation["resolvedModel"] = "edited-model"
        target.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")))
        target.chmod(0o600)
        with self.assertRaises(ValueError):
            hook_receipt.verify(
                self.state, marker, "session-secret-id", "prompt-secret-id", "PostToolUse",
                observer._receipt_version(observation), "success", consume=False)

    def test_unknown_tool_event_and_missing_native_fields_do_not_record(self):
        self.assertEqual(observer.run({"hook_event_name": "PreToolUse", "tool_name": "Agent"}, self.state), {})
        self.assertEqual(observer.run({"hook_event_name": "PostToolUse", "tool_name": "Read"}, self.state), {})
        for changes in ({"tool_use_id": None}, {"session_id": None}, {"prompt_id": None}):
            with self.subTest(changes=changes):
                result = observer.run(self.payload(**changes), self.state)
                self.assertIn("skipped", result["systemMessage"])
        self.assertFalse((self.state / observer.STATE_FILE).exists())
        self.assertFalse((self.state / "batch-0000000000000001").exists())

    def test_unknown_status_oversized_model_list_and_malformed_cli_fail_open(self):
        for response in ({"status": "unknown", "agentId": "a"},
                         {"status": "completed", "agentId": "a", "modelsUsed": ["m"] * 17}):
            payload = self.payload(tool_response=response)
            self.assertIn("skipped", observer.run(payload, self.state)["systemMessage"])
        script = SCRIPTS / "delegation_observer.py"
        cli = subprocess.run([sys.executable, str(script), "--state-dir", str(self.state)],
                             input="{" + " " * (observer.MAX_INPUT + 1), text=True,
                             capture_output=True, timeout=5)
        self.assertEqual(cli.returncode, 0)
        self.assertIn("oversized", json.loads(cli.stdout)["systemMessage"])
        self.assertFalse((self.state / observer.STATE_FILE).exists())

    def test_symlink_state_file_and_symlink_state_directory_are_rejected(self):
        victim = Path(self.temp.name) / "victim"
        victim.write_text("preserve")
        (self.state / observer.STATE_FILE).symlink_to(victim)
        result = observer.run(self.payload(), self.state)
        self.assertIn("skipped", result["systemMessage"])
        self.assertEqual(victim.read_text(), "preserve")
        other = Path(self.temp.name) / "other"
        other.mkdir(mode=0o700)
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(other, target_is_directory=True)
        self.assertIn("skipped", observer.run(self.payload(), alias)["systemMessage"])
        self.assertEqual(list(other.iterdir()), [])

    def test_symlink_and_fifo_locks_are_rejected_without_recording(self):
        victim = Path(self.temp.name) / "lock-target"
        victim.write_text("preserve")
        (self.state / observer.LOCK_FILE).symlink_to(victim)
        result = observer.run(self.payload(), self.state)
        self.assertIn("skipped", result["systemMessage"])
        self.assertEqual(victim.read_text(), "preserve")
        (self.state / observer.LOCK_FILE).unlink()
        os.mkfifo(self.state / observer.LOCK_FILE, 0o600)
        result = observer.run(self.payload(), self.state)
        self.assertIn("skipped", result["systemMessage"])
        self.assertFalse((self.state / observer.STATE_FILE).exists())

    def test_oversized_existing_observation_is_not_replaced(self):
        target = self.state / observer.STATE_FILE
        original = b"x" * (observer.MAX_FILE + 1)
        target.write_bytes(original)
        target.chmod(0o600)
        result = observer.run(self.payload(), self.state)
        self.assertIn("skipped", result["systemMessage"])
        self.assertEqual(target.read_bytes(), original)

    def test_concurrent_observations_leave_one_bounded_owner_only_file(self):
        def record(index):
            payload = self.payload(tool_use_id=f"tool-use-{index}")
            return observer.run(payload, self.state)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(record, range(8)))
        self.assertTrue(all("task QA required" in item["systemMessage"] for item in results))
        target = self.state / observer.STATE_FILE
        observation = json.loads(target.read_text())["observation"]
        self.assertIn(observation["toolUseHash"], {observer._hash(f"tool-use-{i}") for i in range(8)})
        self.assertLessEqual(target.stat().st_size, observer.MAX_FILE)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(list(self.state.glob("latest-observation.json"))), 1)


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import cli


class LearningCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "private-state"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return cli.main(["--state-dir", str(self.root), *args])

    def test_preference_lifecycle_requires_explicit_flag_and_preserves_history(self):
        self.assertEqual(self.run_cli("propose", "--scope", "quality", "--rule", "Use a fixed check."), 0)
        self.assertFalse((self.root / "standards/quality.md").exists())
        self.assertEqual(self.run_cli("approve", "p0001", "--approval", "reviewed wording"), 2)
        self.assertEqual(self.run_cli("approve", "p0001", "--approved", "--approval", "reviewed wording"), 0)
        state = json.loads((self.root / "state.json").read_text())
        self.assertEqual([x["status"] for x in state["preferences"][0]["history"]], ["proposed", "approved"])
        standard = (self.root / "standards/quality.md").read_text()
        self.assertIn("Use a fixed check.", standard)
        output = io.StringIO()
        with contextlib.redirect_stdout(output): self.run_cli("read", "--scope", "quality")
        self.assertIn("Use a fixed check.", output.getvalue())

    def test_scope_traversal_controls_secrets_and_private_fields_rejected(self):
        for scope in ("../escape", "/tmp", "a/b", ".."):
            with self.subTest(scope=scope), self.assertRaises(cli.LearningError): cli.scope_name(scope)
        for value in ("hello\nworld", "api_key=abc123", "x" * 501):
            with self.subTest(value=value[:10]), self.assertRaises(cli.LearningError): cli.clean_text(value, "input")
        self.run_cli("propose", "--scope", "general", "--rule", "A bounded standard")
        state_path = self.root / "state.json"
        state = json.loads(state_path.read_text()); state["transcript"] = "private data"; state_path.write_text(json.dumps(state))
        self.assertEqual(self.run_cli("report"), 2)

    def test_approval_backup_and_scoped_projection(self):
        self.run_cli("propose", "--scope", "quality", "--rule", "Keep checks reproducible.")
        self.run_cli("approve", "p0001", "--approved", "--approval", "approved")
        self.run_cli("propose", "--scope", "quality", "--rule", "Keep evidence readable.")
        self.run_cli("approve", "p0002", "--approved", "--approval", "approved")
        self.run_cli("propose", "--scope", "writing", "--rule", "Use plain language.")
        self.run_cli("approve", "p0003", "--approved", "--approval", "approved")
        self.assertTrue((self.root / "standards/quality.md").is_file())
        self.assertTrue((self.root / "standards/writing.md").is_file())
        self.assertEqual(len(list((self.root / "backups").rglob("*.bak"))), 1)

    def test_failure_aggregation_caps_output_and_preserves_duplicate_evidence(self):
        for i in range(5):
            self.run_cli("failure", "--capability", "summarization", "--task", "brief", "--model", "sample-v1",
                         "--evidence", f"manual-{i}", "--outcome", "failure")
        self.assertEqual(self.run_cli("failure", "--capability", "summarization", "--task", "brief", "--model", "sample-v1",
                                      "--evidence", "manual-0", "--outcome", "failure"), 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out): self.run_cli("report")
        self.assertIn("5 failure outcome(s)", out.getvalue())
        self.assertLessEqual(len([line for line in out.getvalue().splitlines() if line.startswith("- ")]), 3)

    def test_maintenance_is_repeatable_and_detects_drift(self):
        self.run_cli("propose", "--scope", "quality", "--rule", "Keep checks reproducible.")
        self.run_cli("approve", "p0001", "--approved", "--approval", "approved")
        out1, out2 = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out1): self.assertEqual(self.run_cli("maintain"), 0)
        standard = (self.root / "standards/quality.md").read_bytes()
        with contextlib.redirect_stdout(out2): self.assertEqual(self.run_cli("maintain"), 0)
        self.assertEqual(out1.getvalue(), out2.getvalue())
        self.assertEqual(standard, (self.root / "standards/quality.md").read_bytes())
        self.assertEqual(json.loads((self.root / "state.json").read_text())["preferences"][0]["status"], "approved")
        (self.root / "standards/quality.md").write_text("manual edit")
        self.assertEqual(self.run_cli("maintain"), 2)

    def test_symlink_state_root_is_rejected_without_chmod_or_write(self):
        target = Path(self.tmp.name) / "target"
        target.mkdir(mode=0o755)
        os.chmod(target, 0o755)
        self.root.symlink_to(target, target_is_directory=True)
        self.assertEqual(self.run_cli("propose", "--scope", "quality", "--rule", "Stay local."), 2)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        self.assertEqual(list(target.iterdir()), [])

    def test_symlink_projection_parents_cannot_escape_state_root(self):
        self.run_cli("propose", "--scope", "quality", "--rule", "Stay local.")
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        external_standard = outside / "quality.md"
        external_standard.write_text("untrusted external file")
        (self.root / "standards").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_cli("approve", "p0001", "--approved", "--approval", "reviewed"), 2)
        self.assertEqual(external_standard.read_text(), "untrusted external file")
        self.assertEqual(len(list(outside.iterdir())), 1)
        state = json.loads((self.root / "state.json").read_text())
        self.assertEqual(state["preferences"][0]["status"], "pending")

    def test_symlink_backup_parent_cannot_escape_or_change_standard(self):
        self.run_cli("propose", "--scope", "quality", "--rule", "Stay local.")
        standard_dir = self.root / "standards"
        standard_dir.mkdir()
        standard = standard_dir / "quality.md"
        standard.write_text("# Existing approved standard\n")
        outside = Path(self.tmp.name) / "outside-backups"
        outside.mkdir()
        (self.root / "backups").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_cli("approve", "p0001", "--approved", "--approval", "reviewed"), 2)
        self.assertEqual(standard.read_text(), "# Existing approved standard\n")
        self.assertEqual(list(outside.iterdir()), [])

    def test_nonregular_and_oversized_projection_inputs_rejected(self):
        self.run_cli("propose", "--scope", "quality", "--rule", "Stay local.")
        (self.root / "standards").mkdir()
        fifo = self.root / "standards/quality.md"
        os.mkfifo(fifo)
        self.assertEqual(self.run_cli("approve", "p0001", "--approved", "--approval", "reviewed"), 2)
        fifo.unlink()
        fifo.write_bytes(b"x" * (cli.MAX_STATE + 1))
        self.assertEqual(self.run_cli("approve", "p0001", "--approved", "--approval", "reviewed"), 2)
        self.assertEqual(fifo.stat().st_size, cli.MAX_STATE + 1)
        self.assertEqual(json.loads((self.root / "state.json").read_text())["preferences"][0]["status"], "pending")

    def test_combined_projection_size_is_checked_before_backup(self):
        self.run_cli("propose", "--scope", "quality", "--rule", "Stay local.")
        standard_dir = self.root / "standards"
        standard_dir.mkdir()
        standard = standard_dir / "quality.md"
        standard.write_bytes(b"x" * cli.MAX_STATE)
        self.assertEqual(self.run_cli("approve", "p0001", "--approved", "--approval", "reviewed"), 2)
        self.assertEqual(standard.stat().st_size, cli.MAX_STATE)
        self.assertFalse((self.root / "backups").exists())
        self.assertEqual(json.loads((self.root / "state.json").read_text())["preferences"][0]["status"], "pending")

    def test_oversized_final_state_is_rejected_before_projection_or_backup(self):
        self.run_cli("propose", "--scope", "quality", "--rule", "Stay local.")
        state_path = self.root / "state.json"
        state = json.loads(state_path.read_text())
        state["changes"] = [{"date": "2026-01-01", "kind": "fixture", "scope": "general", "id": "x",
                              "padding": "x" * (cli.MAX_STATE - len(state_path.read_bytes()) - 180)}]
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        self.assertLessEqual(len(encoded.encode()), cli.MAX_STATE)
        state_path.write_text(encoded)
        before = state_path.read_bytes()
        self.assertEqual(self.run_cli("approve", "p0001", "--approved", "--approval", "reviewed"), 2)
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse((self.root / "standards/quality.md").exists())
        self.assertFalse((self.root / "backups").exists())

    def test_projection_is_rolled_back_when_state_commit_fails(self):
        self.run_cli("propose", "--scope", "quality", "--rule", "Stay local.")
        with mock.patch.object(cli.Store, "save", side_effect=OSError("simulated state write failure")):
            self.assertEqual(self.run_cli("approve", "p0001", "--approved", "--approval", "reviewed"), 2)
        self.assertFalse((self.root / "standards/quality.md").exists())
        self.assertEqual(json.loads((self.root / "state.json").read_text())["preferences"][0]["status"], "pending")

    def test_orphan_pending_projection_is_rejected_then_reconciled_by_retry(self):
        self.run_cli("propose", "--scope", "quality", "--rule", "Keep the accepted check explicit.")
        standards = self.root / "standards"
        standards.mkdir()
        path = standards / "quality.md"
        path.write_text("# Approved local standards: quality\n\n## Approved preference p0001\n\n"
                        "Keep the accepted check explicit.\n\n"
                        "Approval: user-confirmed via explicit --approved flag (reviewed exact scope)\n")
        original_projection = path.read_bytes()
        original_state = (self.root / "state.json").read_bytes()
        read_output = io.StringIO()
        with contextlib.redirect_stdout(read_output): self.assertEqual(self.run_cli("read", "--scope", "quality"), 2)
        self.assertEqual(read_output.getvalue(), "")
        self.assertEqual(self.run_cli("maintain"), 2)
        self.assertEqual(path.read_bytes(), original_projection)
        self.assertEqual((self.root / "state.json").read_bytes(), original_state)
        self.assertEqual(self.run_cli("approve", "p0001", "--approved", "--approval", "reviewed exact scope"), 0)
        read_output = io.StringIO()
        with contextlib.redirect_stdout(read_output): self.assertEqual(self.run_cli("read", "--scope", "quality"), 0)
        self.assertIn("Keep the accepted check explicit.", read_output.getvalue())
        self.assertEqual(self.run_cli("maintain"), 0)

    def test_maintenance_rejects_unknown_generated_scope_block(self):
        self.run_cli("propose", "--scope", "general", "--rule", "Keep it local.")
        standards = self.root / "standards"
        standards.mkdir()
        unknown = standards / "other.md"
        unknown.write_text("# Manual section\n\n## Approved preference p9999\n\nUnknown rule.\n\n"
                           "Approval: user-confirmed via explicit --approved flag (manual note)\n")
        before = unknown.read_bytes()
        self.assertEqual(self.run_cli("maintain"), 2)
        self.assertEqual(unknown.read_bytes(), before)

    def test_concurrent_outcomes_are_serialized_without_lost_updates(self):
        script = Path(cli.__file__)
        commands = []
        for i in range(6):
            commands.append([sys.executable, str(script), "--state-dir", str(self.root), "failure",
                             "--capability", "writing", "--task", "summary", "--model", "test-model",
                             "--evidence", f"concurrent-{i}", "--outcome", "success"])
        processes = [subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for command in commands]
        for process in processes:
            _out, err = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, err.decode())
        self.assertEqual(len(json.loads((self.root / "state.json").read_text())["failures"]), len(commands))


if __name__ == "__main__": unittest.main()

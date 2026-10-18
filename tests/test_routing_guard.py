import copy
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "claude-plugin/workflow-hooks-kit/scripts"))
import hook_receipt
import routing_guard
import tool_scope_hook


def policy():
    return {"schema": 2, "models": {
        "budget": {"native_id": "native-budget", "rank": 1, "capabilities": ["read", "edit"]},
        "premium": {"native_id": "native-premium", "rank": 5, "capabilities": ["read", "edit", "deep"]}},
        "profiles": {"build": {"requires": ["read", "edit"]}}}


def stage():
    return {"number": 1, "name": "Build output", "worker_id": "logical-worker", "worker_model": "auto:build",
            "worker_effort": "medium", "model_rationale": "Task requirements", "inputs": ["source"],
            "boundaries": ["No external writes"], "dependencies": [], "definition_of_done": "Create result",
            "outputs": ["result.txt"], "qa": {"check": "Read result", "expected": "Correct"}}


def _race_pre(state, policy_path, payload, project, barrier, queue):
    with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": project}):
        barrier.wait()
        queue.put(routing_guard.run(payload, policy_path=policy_path, state_dir=state, core=tool_scope_hook))


class RoutingGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"; self.project.mkdir()
        self.state = self.root / "state"; self.state.mkdir(mode=0o700)
        self.policy_path = self.root / "policy.json"
        self.write_policy()
        self.ledger = {"schema_version": 1, "task_kind": "substantial", "state": "in-progress", "stages": [stage()]}
        self.before = copy.deepcopy(self.ledger)
        self.core = tool_scope_hook
        self.old_claude_state = tool_scope_hook.CLAUDE_STATE
        self.old_workflow_state = tool_scope_hook.workflow.STATE
        tool_scope_hook.CLAUDE_STATE = self.state
        tool_scope_hook.workflow.STATE = self.state
        self.base = {"session_id": "session-1", "prompt_id": "prompt-1", "cwd": str(self.project)}
        plan_payload = {**self.base, "turn_id": "prompt-1", "_claude_runtime": True}
        tool_scope_hook._apply_api(plan_payload, self.state, str(self.project), "plan", {"stages": [stage()]})

    def tearDown(self):
        tool_scope_hook.CLAUDE_STATE = self.old_claude_state
        tool_scope_hook.workflow.STATE = self.old_workflow_state
        self.tmp.cleanup()

    def write_policy(self, value=None):
        self.policy_path.write_text(json.dumps(value or policy()))
        self.policy_path.chmod(0o600)

    def ups(self, prompt="build task"):
        return routing_guard.run({**self.base, "hook_event_name": "UserPromptSubmit", "user_prompt": prompt},
                                 policy_path=self.policy_path, state_dir=self.state)

    def pre(self, **fields):
        data = {"description": "Build output", "prompt": "original request", **fields}
        payload = {**self.base, "hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "tool-1", "tool_input": data}
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)}):
            return routing_guard.run(payload, policy_path=self.policy_path, state_dir=self.state, core=self.core)

    def test_auto_route_rewrites_packet_accepts_native_optionals_and_post_verifies(self):
        self.ups()
        result = self.pre(name="worker", run_in_background=False, isolation="worktree")
        rewritten = result["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(rewritten["model"], "budget")
        self.assertEqual(rewritten["effort"], "medium")
        self.assertEqual(rewritten["name"], "worker")
        self.assertIn("WORKFLOW_STAGE_REQUEST_V1", rewritten["prompt"])
        post = {**self.base, "hook_event_name": "PostToolUse", "tool_name": "Agent", "tool_use_id": "tool-1",
                "tool_input": rewritten, "tool_response": {"status": "completed", "agentId": "agent-1", "resolvedModel": "native-budget"}}
        observed = routing_guard.run(post, policy_path=self.policy_path, state_dir=self.state)
        self.assertIn("semantic QA", observed["systemMessage"])
        repeated_post = routing_guard.run(post, policy_path=self.policy_path, state_dir=self.state)
        self.assertIn("routing observation failed", repeated_post["systemMessage"])
        self.assertIn("[wf:", repeated_post["systemMessage"])
        replay = self.pre()
        self.assertIn("permissionDecision", replay["hookSpecificOutput"])
        self.assertEqual(self.ledger, self.before)

    def test_explicit_native_override_is_preserved_and_mismatch_is_recorded(self):
        self.ups("WORKFLOW_MODEL=premium\nDo task")
        result = self.pre()
        rewritten = result["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(rewritten["model"], "premium")
        post = {**self.base, "hook_event_name": "PostToolUse", "tool_name": "Agent", "tool_use_id": "tool-1",
                "tool_input": rewritten, "tool_response": {"status": "completed", "agentId": "agent-1", "resolvedModel": "other"}}
        observed = routing_guard.run(post, policy_path=self.policy_path, state_dir=self.state)
        self.assertIn("mismatch", observed["systemMessage"])
        result_file = self.state / ("result-" + __import__("hashlib").sha256(b"session-1").hexdigest() + ".json")
        self.assertFalse(json.loads(result_file.read_text())["model_match"])

    def test_human_override_may_select_lower_capability_and_gap_is_recorded(self):
        self.policy_path.write_text(json.dumps({**policy(), "profiles": {"build": {"requires": ["read", "edit", "deep"]}}}))
        self.policy_path.chmod(0o600)
        self.ups("WORKFLOW_MODEL=budget\nPlease build")
        result = self.pre()
        pending = routing_guard._read(self.state, routing_guard._pending_name("session-1"))
        self.assertEqual(result["hookSpecificOutput"]["updatedInput"]["model"], "budget")
        self.assertEqual(pending["route"]["missing_capabilities"], ["deep"])

    def test_no_ups_tampered_context_and_no_plan_are_signed_denials(self):
        denied = self.pre()
        reason = denied["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("[wf:", reason)
        marker = reason.rsplit("[wf:", 1)[1].split("]", 1)[0]
        hook_receipt.verify(self.state, marker, "session-1", "prompt-1", "PreToolUse",
                            routing_guard._stamp(routing_guard._policy(self.policy_path)[1]), "failure")
        self.ups(); ctx = next(self.state.glob("context-*.json"))
        data = json.loads(ctx.read_text()); data["cwd"] = "/tmp/elsewhere"; ctx.write_text(json.dumps(data)); ctx.chmod(0o600)
        self.assertIn("permissionDecision", self.pre()["hookSpecificOutput"])
        self.ups(); self.core.workflow._ledger_path("session-1", "prompt-1").unlink()
        self.assertIn("permissionDecision", self.pre()["hookSpecificOutput"])

    def test_duplicate_policy_json_is_rejected(self):
        self.policy_path.write_text('{"schema":2,"schema":2,"models":{},"profiles":{}}'); self.policy_path.chmod(0o600)
        self.ups()
        denied = self.pre()
        self.assertIn("permissionDecision", denied["hookSpecificOutput"])

    def test_bad_stage_selector_model_or_frozen_effort_denies(self):
        self.ups()
        self.assertIn("permissionDecision", self.pre(description="[workflow-stage:1] Wrong stage")["hookSpecificOutput"])
        self.assertIn("permissionDecision", self.pre(effort="high")["hookSpecificOutput"])
        self.assertEqual(self.ledger, self.before)

    def test_post_identity_mismatch_is_signed_failure_and_dod_is_packet_bound(self):
        stored = self.core.workflow._read(self.core.workflow._ledger_path("session-1", "prompt-1"))
        self.ups()
        result = self.pre()
        rewritten = result["hookSpecificOutput"]["updatedInput"]
        self.assertIn("Create result", rewritten["prompt"])
        bad_post = {**self.base, "hook_event_name": "PostToolUse", "tool_name": "Agent", "tool_use_id": "different-tool",
                    "tool_input": rewritten, "tool_response": {"status": "completed", "agentId": "agent-1", "resolvedModel": "native-budget"}}
        failed = routing_guard.run(bad_post, policy_path=self.policy_path, state_dir=self.state)
        self.assertIn("[wf:", failed["systemMessage"])
        marker = failed["systemMessage"].split("[wf:", 1)[1].split("]", 1)[0]
        hook_receipt.verify(self.state, marker, "session-1", "prompt-1", "PostToolUse",
                            routing_guard._stamp(routing_guard._policy(self.policy_path)[1]), "failure")
        self.assertEqual(self.core.workflow._read(self.core.workflow._ledger_path("session-1", "prompt-1")), stored)

    def test_multiprocess_same_tool_dispatch_has_single_winner(self):
        self.ups()
        payload = {**self.base, "hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "race-tool",
                   "tool_input": {"description": "Build output", "prompt": "original"}}
        ctx = multiprocessing.get_context("fork")
        barrier, queue = ctx.Barrier(2), ctx.Queue()
        processes = [ctx.Process(target=_race_pre, args=(str(self.state), str(self.policy_path), payload,
                                                         str(self.project), barrier, queue)) for _ in range(2)]
        for proc in processes: proc.start()
        results = [queue.get(timeout=10) for _ in processes]
        for proc in processes:
            proc.join(timeout=10)
            self.assertEqual(proc.exitcode, 0)
        winners = [result for result in results if "updatedInput" in result.get("hookSpecificOutput", {})]
        self.assertEqual(len(winners), 1)

    def test_new_native_prompt_supersedes_old_unconsumed_dispatch(self):
        self.ups()
        first = self.pre()
        self.assertIn("updatedInput", first["hookSpecificOutput"])
        next_base = {**self.base, "prompt_id": "prompt-2"}
        self.assertIn("recorded", routing_guard.run({**next_base, "event": "UserPromptSubmit", "user_prompt": "next"},
                                                       policy_path=self.policy_path, state_dir=self.state)["systemMessage"])
        plan_payload = {**next_base, "turn_id": "prompt-2", "_claude_runtime": True}
        self.core._apply_api(plan_payload, self.state, str(self.project), "plan", {"stages": [stage()]})
        new_agent = {**next_base, "cwd": str(self.project), "event": "PreToolUse", "tool_name": "Agent", "tool_use_id": "tool-2",
                     "tool_input": {"description": "Build output", "prompt": "original"}}
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)}):
            second = routing_guard.run(new_agent, policy_path=self.policy_path, state_dir=self.state, core=self.core)
        self.assertIn("updatedInput", second["hookSpecificOutput"])
        old_post = {**self.base, "event": "PostToolUse", "tool_name": "Agent", "tool_use_id": "tool-1",
                    "tool_input": first["hookSpecificOutput"]["updatedInput"],
                    "tool_response": {"status": "completed", "agentId": "old-agent", "resolvedModel": "native-budget"}}
        stale = routing_guard.run(old_post, policy_path=self.policy_path, state_dir=self.state)
        self.assertIn("routing observation failed", stale["systemMessage"])


if __name__ == "__main__": unittest.main()

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-plugin/workflow-hooks-kit/scripts"))
import routing_policy


def policy():
    return {
        "schema": 2,
        "models": {
            "budget": {"native_id": "native-budget-v1", "rank": 1, "capabilities": ["read", "edit"]},
            "premium": {"native_id": "native-premium-v1", "rank": 9,
                        "capabilities": ["read", "edit", "reason"]},
        },
        "profiles": {"implementation": {"requires": ["read", "edit"]},
                     "analysis": {"requires": ["reason"]}},
    }


def stage():
    return {"number": 1, "name": "build", "worker_id": "worker-a", "worker_model": "auto:implementation",
            "worker_effort": "medium", "model_rationale": "Declared bounded implementation",
            "inputs": ["source"], "boundaries": ["read-only outside project"], "dependencies": [],
            "definition_of_done": "Return output", "outputs": ["result.json"],
            "qa": {"check": "Inspect result", "expected": "Correct"}}


class RoutingPolicyTests(unittest.TestCase):
    def test_selects_lowest_rank_adequate_and_preserves_stage_criteria(self):
        original = stage()
        before = copy.deepcopy(original)
        effective, binding = routing_policy.select_route(original, policy())
        self.assertEqual(effective["worker_model"], "budget")
        self.assertEqual(binding["selected_alias"], "budget")
        self.assertEqual(binding["expected_native_model"], "native-budget-v1")
        self.assertEqual(binding["missing_capabilities"], ())
        self.assertFalse(binding["override"])
        self.assertEqual({k: v for k, v in effective.items() if k != "worker_model"},
                         {k: v for k, v in before.items() if k != "worker_model"})
        self.assertEqual(original, before)
        with self.assertRaises(TypeError):
            binding["selected_alias"] = "premium"

    def test_explicit_override_is_honored_and_capability_gap_is_disclosed(self):
        effective, binding = routing_policy.select_route(stage(), policy(), "budget")
        self.assertEqual(effective["worker_model"], "budget")
        self.assertTrue(binding["override"])
        self.assertEqual(binding["missing_capabilities"], ())
        effective, binding = routing_policy.select_route(stage(), policy(), "premium")
        self.assertEqual(effective["worker_model"], "premium")
        self.assertEqual(binding["missing_capabilities"], ())

    def test_no_adequate_model_fails_and_override_can_report_gap(self):
        p = policy()
        p["profiles"]["implementation"]["requires"] = ["impossible"]
        with self.assertRaisesRegex(ValueError, "No policy model"):
            routing_policy.select_route(stage(), p)
        effective, binding = routing_policy.select_route(stage(), p, "budget")
        self.assertEqual(effective["worker_model"], "budget")
        self.assertEqual(binding["missing_capabilities"], ("impossible",))

    def test_invalid_policy_shapes_and_values_fail_closed(self):
        cases = []
        p = policy(); p["schema"] = True; cases.append(p)
        p = policy(); p["models"]["budget"]["rank"] = True; cases.append(p)
        p = policy(); p["models"]["budget"]["capabilities"] = ["read", "read"]; cases.append(p)
        p = policy(); p["profiles"]["implementation"]["requires"] = ["edit", "edit"]; cases.append(p)
        p = policy(); p["unknown"] = True; cases.append(p)
        p = policy(); p["models"]["budget"]["unknown"] = 1; cases.append(p)
        p = policy(); p["profiles"]["implementation"]["requires"] = ["needs space"]; cases.append(p)
        p = policy(); p["models"]["budget"]["native_id"] = "bad\nid"; cases.append(p)
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    routing_policy.select_route(stage(), candidate)

    def test_oversized_policy_and_stage_and_unknown_override_fail(self):
        p = policy()
        p["models"]["budget"]["capabilities"] = ["x" * 250 + str(i) for i in range(64)]
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            routing_policy.select_route(stage(), p)
        oversized = stage(); oversized["definition_of_done"] = "x" * 33_000
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            routing_policy.select_route(oversized, policy())
        with self.assertRaisesRegex(ValueError, "override"):
            routing_policy.select_route(stage(), policy(), "missing")

    def test_policy_and_source_hashes_are_stable_and_sensitive(self):
        _, binding = routing_policy.select_route(stage(), policy())
        _, same = routing_policy.select_route(stage(), policy())
        self.assertEqual(binding["policy_hash"], same["policy_hash"])
        self.assertEqual(binding["source_stage_hash"], same["source_stage_hash"])
        changed = stage(); changed["definition_of_done"] += " now"
        _, altered = routing_policy.select_route(changed, policy())
        self.assertNotEqual(binding["source_stage_hash"], altered["source_stage_hash"])


if __name__ == "__main__":
    unittest.main()

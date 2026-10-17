import copy
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "claude-plugin/workflow-hooks-kit/scripts"))
import delegation_binding as binding
import tool_scope_hook


def stage(number=1):
    return {
        "number": number,
        "name": f"stage-{number}",
        "worker_id": "logical-worker-alpha",
        "worker_model": "haiku",
        "worker_effort": "low",
        "model_rationale": "Small bounded implementation task.",
        "inputs": ["approved source files"],
        "boundaries": ["No model calls", "No legacy edits"],
        "dependencies": [],
        "definition_of_done": "Return the validated stage packet.",
        "outputs": ["result.json"],
        "qa": {"check": "Compare the canonical packet.", "expected": "Exact match."},
    }


def ledger(stages=None):
    return {
        "schema_version": 1,
        "task_kind": "substantial",
        "state": "in-progress",
        "stages": stages if stages is not None else [stage()],
    }


def request(for_stage=None, **overrides):
    selected = for_stage or stage()
    data = {
        "description": f"[workflow-stage:{selected['number']}] {selected['name']}",
        "prompt": binding.build_prompt(selected),
        "model": selected["worker_model"],
        "subagent_type": "general-purpose",
    }
    data.update(overrides)
    return data


class DelegationBindingTests(unittest.TestCase):
    def test_binds_exact_canonical_stage_and_resolved_model(self):
        result = binding.validate_request(ledger(), request(), {"haiku": "claude-haiku-5-5"})
        self.assertEqual(set(result), {
            "schema", "stage_number", "worker_id", "requested_model", "resolved_model",
            "stage_hash", "prompt_hash",
        })
        self.assertEqual(dict(result), {
            "schema": 1,
            "stage_number": 1,
            "worker_id": "logical-worker-alpha",
            "requested_model": "haiku",
            "resolved_model": "claude-haiku-5-5",
            "stage_hash": hashlib.sha256(
                binding._canonical_json(binding._packet(binding._frozen_stage(stage(), 1)))
            ).hexdigest(),
            "prompt_hash": hashlib.sha256(binding.build_prompt(stage()).encode("utf-8")).hexdigest(),
        })
        with self.assertRaises(TypeError):
            result["worker_id"] = "changed"

    def test_newline_and_unicode_are_valid_but_prompt_must_be_exact(self):
        candidate = stage()
        candidate["definition_of_done"] = "תוצאה מדויקת\nבשורה הבאה"
        packet = binding.build_prompt(candidate)
        result = binding.validate_request(
            ledger([candidate]),
            request(candidate, prompt=packet),
            {"haiku": "claude-haiku-5-5"},
        )
        self.assertEqual(result["stage_number"], 1)

    def test_mutable_qa_evidence_does_not_change_prompt_or_stage_hash(self):
        original = ledger()
        updated = copy.deepcopy(original)
        updated["stages"][0]["qa"].update(
            evidence="later verification", verdict="pass", reviewer_id="reviewer"
        )
        prompt = binding.build_prompt(original["stages"][0])
        self.assertEqual(prompt, binding.build_prompt(updated["stages"][0]))
        tool_input = request(prompt=prompt)
        before = binding.validate_request(original, tool_input, {"haiku": "claude-haiku-5-5"})
        after = binding.validate_request(updated, tool_input, {"haiku": "claude-haiku-5-5"})
        self.assertEqual(before["stage_hash"], after["stage_hash"])
        self.assertEqual(before["prompt_hash"], after["prompt_hash"])

    def test_runtime_pending_qa_attempts_and_assertions_bind_to_prepared_stage(self):
        runtime = stage()
        runtime["attempts"] = [{"model": "haiku", "verdict": "fail", "reason": "retry"}]
        runtime["qa"].update(evidence="pending", verdict="pending", reviewer_id="pending")
        runtime["qa"]["assertions"] = [{"path": "result.json", "expected_text": ""}]
        saved = ledger([runtime])

        # Exercise the same immutable projection used by the existing ledger core.
        prepared = tool_scope_hook._prepared_plan_body(saved)
        prepared_stage = prepared["stages"][0]
        prompt = binding.build_prompt(prepared_stage)
        result = binding.validate_request(saved, request(runtime, prompt=prompt), {
            "haiku": "claude-haiku-5-5"
        })
        self.assertEqual(result["stage_number"], 1)
        self.assertIn('"assertions":[{"expected_text":"","path":"result.json"}]', prompt)

        updated = copy.deepcopy(saved)
        updated["stages"][0]["attempts"].append({"model": "haiku", "verdict": "pending"})
        updated["stages"][0]["qa"].update(
            evidence="new evidence", verdict="fail", reviewer_id="new reviewer"
        )
        self.assertEqual(prompt, binding.build_prompt(updated["stages"][0]))
        self.assertEqual(
            result["stage_hash"],
            binding.validate_request(updated, request(runtime, prompt=prompt), {
                "haiku": "claude-haiku-5-5"
            })["stage_hash"],
        )

    def test_assertions_are_frozen_and_must_match_declared_relative_outputs(self):
        original = stage()
        original["qa"]["assertions"] = [{"path": "result.json", "expected_text": "approved"}]
        prompt = binding.build_prompt(original)
        changed = copy.deepcopy(original)
        changed["qa"]["assertions"][0]["expected_text"] = "rewritten"
        self.assertNotEqual(prompt, binding.build_prompt(changed))
        with self.assertRaisesRegex(ValueError, "exactly match"):
            binding.validate_request(ledger([changed]), request(original, prompt=prompt), {
                "haiku": "claude-haiku-5-5"
            })
        for bad_path in ("../result.json", "/tmp/result.json", "other.json"):
            invalid = copy.deepcopy(original)
            invalid["qa"]["assertions"][0]["path"] = bad_path
            with self.subTest(path=bad_path), self.assertRaises(ValueError):
                binding.build_prompt(invalid)

    def test_duplicate_names_empty_outputs_and_unchecked_description_are_rejected(self):
        duplicate = stage(2)
        duplicate["name"] = stage()["name"]
        with self.assertRaisesRegex(ValueError, "names must be unique"):
            binding.validate_request(ledger([stage(), duplicate]), request(), {
                "haiku": "claude-haiku-5-5"
            })
        empty = stage()
        empty["outputs"] = []
        with self.assertRaisesRegex(ValueError, "at least one"):
            binding.build_prompt(empty)
        unchecked = request(description="[workflow-stage:1] stage-1 plus unchecked instructions")
        with self.assertRaisesRegex(ValueError, "exactly identify"):
            binding.validate_request(ledger(), unchecked, {"haiku": "claude-haiku-5-5"})

    def test_attempt_metadata_is_bounded_but_not_interpreted_as_retry_policy(self):
        runtime = stage()
        runtime["attempts"] = [{"model": "haiku", "verdict": "fail"}] * (binding.MAX_ATTEMPTS + 1)
        with self.assertRaisesRegex(ValueError, "bounded list"):
            binding.build_prompt(runtime)
        runtime["attempts"] = [{"model": "haiku", "verdict": "fail"}] * 4
        self.assertTrue(binding.build_prompt(runtime))

    def test_does_not_mutate_input_mappings(self):
        plan, tool_input, models = ledger(), request(), {"haiku": "claude-haiku-5-5"}
        before = copy.deepcopy((plan, tool_input, models))
        binding.validate_request(plan, tool_input, models)
        self.assertEqual((plan, tool_input, models), before)

    def test_wrong_stage_worker_and_model_are_rejected(self):
        plan = ledger([stage(1), stage(2)])
        cases = (
            request(description="[workflow-stage:2] stage-2"),
            request(worker_id="different-worker"),
            request(model="sonnet"),
            request(description="wrong stage"),
            request(description="[workflow-stage:3] absent"),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    binding.validate_request(plan, candidate, {"haiku": "claude-haiku-5-5"})

    def test_requested_alias_requires_explicit_native_resolution(self):
        with self.assertRaisesRegex(ValueError, "no trusted native resolution"):
            binding.validate_request(ledger(), request(), {})
        with self.assertRaises(ValueError):
            binding.validate_request(ledger(), request(model="claude-legacy"), {
                "haiku": "claude-haiku-5-5", "claude-legacy": "claude-legacy"
            })

    def test_missing_extra_or_tampered_request_fields_are_rejected(self):
        candidates = []
        missing = request()
        del missing["model"]
        candidates.append(missing)
        extra = request()
        extra["append"] = "unverified suffix"
        candidates.append(extra)
        for field, value in (("prompt", binding.build_prompt(stage()) + "\nextra"),
                             ("prompt", "prefix\n" + binding.build_prompt(stage())),
                             ("prompt", binding.build_prompt(stage()).replace(
                                 '{"protocol":', '{"protocol":"duplicate", "protocol":', 1)),
                             ("description", "[workflow-stage:01] stage-1")):
            candidates.append(request(**{field: value}))
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    binding.validate_request(ledger(), candidate, {"haiku": "claude-haiku-5-5"})

    def test_frozen_criteria_cannot_be_rewritten_after_prompt_creation(self):
        original_plan = ledger()
        submitted = request()
        changed_plan = copy.deepcopy(original_plan)
        changed_plan["stages"][0]["qa"]["expected"] = "rewritten acceptance"
        with self.assertRaisesRegex(ValueError, "exactly match"):
            binding.validate_request(changed_plan, submitted, {"haiku": "claude-haiku-5-5"})

    def test_specialist_subagent_config_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "general-purpose"):
            binding.validate_request(ledger(), request(subagent_type="researcher"), {
                "haiku": "claude-haiku-5-5"
            })

    def test_missing_or_out_of_order_stages_are_rejected(self):
        for candidate in (ledger([]), ledger([stage(2)]), ledger([stage(1), stage(1)])):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    binding.validate_request(candidate, request(), {"haiku": "claude-haiku-5-5"})

    def test_ledger_identity_schema_state_and_types_fail_closed(self):
        mutations = (
            lambda data: data.pop("schema_version"),
            lambda data: data.update(schema_version=True),
            lambda data: data.update(schema_version=1.0),
            lambda data: data.update(task_kind="small"),
            lambda data: data.update(state="complete"),
            lambda data: data["stages"][0].update(number=True),
            lambda data: data["stages"][0].update(outputs=["x", 4]),
            lambda data: data["stages"][0]["qa"].update(expected=""),
            lambda data: data["stages"][0].update(unrecognized="extra"),
        )
        for mutate in mutations:
            candidate = ledger()
            mutate(candidate)
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    binding.validate_request(candidate, request(), {"haiku": "claude-haiku-5-5"})

    def test_boolean_and_float_stage_numbers_are_not_integers(self):
        for number in (True, 1.0):
            candidate = stage()
            candidate["number"] = number
            with self.subTest(number=number):
                with self.assertRaises(ValueError):
                    binding.build_prompt(candidate)

    def test_oversized_prompt_and_model_map_values_are_rejected(self):
        with self.assertRaises(ValueError):
            binding.validate_request(ledger(), request(prompt="x" * (binding.MAX_PACKET_BYTES + 1)), {
                "haiku": "claude-haiku-5-5"
            })
        with self.assertRaises(ValueError):
            binding.validate_request(ledger(), request(), {"haiku": " "})


if __name__ == "__main__":
    unittest.main()

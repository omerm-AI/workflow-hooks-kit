"""Mechanical binding between a frozen workflow stage and a Claude Agent request.

This module validates request routing and criteria delivery only. It does not
authenticate the native caller, verify execution, or judge completed work.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = 1
MAX_STAGES = 20
MAX_PACKET_BYTES = 32_768
MAX_STRING_BYTES = 8_192
MAX_LIST_ITEMS = 64
MAX_LIST_ITEM_BYTES = 2_048
MAX_DESCRIPTION_BYTES = 512
MAX_ATTEMPTS = 64
MAX_ATTEMPT_BYTES = 4_096
MAX_ASSERTIONS = 8
MAX_ASSERTION_BYTES = 16_384
_STAGE_FIELDS = frozenset({
    "number", "name", "worker_id", "worker_model", "worker_effort",
    "model_rationale", "inputs", "boundaries", "dependencies",
    "definition_of_done", "outputs", "qa",
})
_QA_FIELDS = frozenset({"check", "expected", "evidence", "verdict", "reviewer_id", "assertions"})
_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
_DESCRIPTION = re.compile(r"^\[workflow-stage:([1-9][0-9]*)\] ")


def _fail(message: str) -> None:
    raise ValueError(message)


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8", "strict"))
    except UnicodeError:
        _fail("Text must be valid UTF-8.")


def _text(value: Any, field: str, *, limit: int = MAX_STRING_BYTES) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        _fail(f"{field} must be nonblank text without NUL.")
    if _utf8_size(value) > limit:
        _fail(f"{field} exceeds the text limit.")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if type(value) is not list or len(value) > MAX_LIST_ITEMS:
        _fail(f"{field} must be a bounded string list.")
    result = []
    for item in value:
        result.append(_text(item, field, limit=MAX_LIST_ITEM_BYTES))
    return result


def _outputs(value: Any) -> list[str]:
    outputs = _string_list(value, "outputs")
    if not outputs:
        _fail("Outputs must contain at least one declared output.")
    return outputs


def _relative_output_key(raw: str) -> str | None:
    if not raw.strip() or "\x00" in raw or Path(raw).is_absolute() or ".." in raw.split("/"):
        return None
    key = Path(raw).as_posix()
    return key if key != "." else None


def _assertions(value: Any, outputs: list[str]) -> list[dict[str, str]]:
    if type(value) is not list or len(value) > MAX_ASSERTIONS:
        _fail("QA assertions must contain at most eight literal file checks.")
    output_keys = {_relative_output_key(output) for output in outputs}
    checked: list[dict[str, str]] = []
    for assertion in value:
        if type(assertion) is not dict or set(assertion) != {"path", "expected_text"}:
            _fail("Each QA assertion must contain exactly path and expected_text.")
        path = _text(assertion["path"], "assertion.path", limit=MAX_LIST_ITEM_BYTES)
        if (Path(path).is_absolute() or "\x00" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))):
            _fail("Assertion path must be a safe relative file path.")
        if path not in output_keys:
            _fail("Assertion path must match a declared relative output.")
        expected = assertion["expected_text"]
        if not isinstance(expected, str) or _utf8_size(expected) > MAX_ASSERTION_BYTES:
            _fail("Assertion expected_text must be valid UTF-8 of at most 16 KiB.")
        checked.append({"path": path, "expected_text": expected})
    return checked


def _validate_attempts(value: Any) -> None:
    """Bound mutable attempt metadata without interpreting retry policy."""
    if type(value) is not list or len(value) > MAX_ATTEMPTS:
        _fail("Stage attempts must be a bounded list of objects.")
    total = 0
    for attempt in value:
        if type(attempt) is not dict or len(attempt) > 16:
            _fail("Each stage attempt must be a bounded object.")
        try:
            encoded = json.dumps(attempt, ensure_ascii=False, allow_nan=False,
                                 sort_keys=True, separators=(",", ":")).encode("utf-8", "strict")
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("Stage attempt metadata must be bounded JSON.") from exc
        if len(encoded) > MAX_ATTEMPT_BYTES:
            _fail("A stage attempt exceeds the metadata limit.")
        total += len(encoded)
        if total > MAX_PACKET_BYTES:
            _fail("Stage attempts exceed the aggregate metadata limit.")


def _canonical_json(value: Any) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":"))
        raw = encoded.encode("utf-8", "strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Frozen stage cannot be encoded canonically.") from exc
    if len(raw) > MAX_PACKET_BYTES:
        _fail("Canonical stage packet exceeds 32 KiB.")
    return raw


def _frozen_stage(stage: Any, number: int) -> dict[str, Any]:
    if (type(stage) is not dict or not _STAGE_FIELDS <= set(stage)
            or set(stage) - (_STAGE_FIELDS | {"attempts"})):
        _fail("Stage fields do not match the supported frozen schema.")
    if "attempts" in stage:
        _validate_attempts(stage["attempts"])
    if type(stage["number"]) is not int or stage["number"] != number:
        _fail("Stage numbers must be consecutive integers.")

    frozen: dict[str, Any] = {"number": number}
    for field in ("name", "worker_id", "worker_model", "worker_effort", "model_rationale",
                  "definition_of_done"):
        frozen[field] = _text(stage[field], field)
    if frozen["worker_effort"] not in _EFFORTS:
        _fail("Stage worker effort is unsupported.")
    for field in ("inputs", "boundaries", "dependencies"):
        frozen[field] = _string_list(stage[field], field)
    frozen["outputs"] = _outputs(stage["outputs"])

    qa = stage["qa"]
    if type(qa) is not dict or not {"check", "expected"} <= set(qa) or set(qa) - _QA_FIELDS:
        _fail("Stage QA fields do not match the supported frozen schema.")
    frozen["qa"] = {
        "check": _text(qa["check"], "qa.check"),
        "expected": _text(qa["expected"], "qa.expected"),
    }
    if "assertions" in qa:
        frozen["qa"]["assertions"] = _assertions(qa["assertions"], frozen["outputs"])
    return frozen


def _packet(frozen: dict[str, Any]) -> dict[str, Any]:
    return {"protocol": "workflow-stage-request-v1", "stage": frozen}


def build_prompt(stage: Mapping[str, Any]) -> str:
    """Return the exact bounded JSON protocol packet for one frozen stage."""
    if not isinstance(stage, dict) and not isinstance(stage, MappingProxyType):
        _fail("Stage must be a mapping.")
    number = stage.get("number")
    if type(number) is not int or number < 1 or number > MAX_STAGES:
        _fail("Stage number is outside the supported range.")
    frozen = _frozen_stage(dict(stage), number)
    raw = _canonical_json(_packet(frozen))
    prompt = "WORKFLOW_STAGE_REQUEST_V1\n" + raw.decode("utf-8")
    if _utf8_size(prompt) > MAX_PACKET_BYTES:
        _fail("Canonical request prompt exceeds 32 KiB.")
    return prompt


def validate_request(ledger: Mapping[str, Any], tool_input: Mapping[str, Any],
                     allowed_models: Mapping[str, str]) -> MappingProxyType:
    """Validate a Claude Agent request against one active frozen ledger stage."""
    if not isinstance(ledger, dict) or not isinstance(tool_input, dict) or not isinstance(allowed_models, dict):
        _fail("Ledger, tool input, and model map must be plain mappings.")
    if type(ledger.get("schema_version")) is not int or ledger.get("schema_version") != SCHEMA_VERSION:
        _fail("Ledger schema is unsupported.")
    if ledger.get("task_kind") != "substantial" or ledger.get("state") != "in-progress":
        _fail("An active substantial plan is required.")
    stages = ledger.get("stages")
    if type(stages) is not list or not stages or len(stages) > MAX_STAGES:
        _fail("Ledger stages are missing or outside the supported range.")
    frozen_stages = [_frozen_stage(stage, index) for index, stage in enumerate(stages, 1)]
    stage_numbers = [stage["number"] for stage in frozen_stages]
    if len(set(stage_numbers)) != len(stage_numbers):
        _fail("Duplicate stages are not supported.")
    names = [stage["name"] for stage in frozen_stages]
    if len(set(names)) != len(names):
        _fail("Stage names must be unique.")

    required_input = {"description", "prompt", "model", "subagent_type"}
    if set(tool_input) != required_input:
        _fail("Agent request fields do not match the supported native schema.")
    description = _text(tool_input["description"], "description", limit=MAX_DESCRIPTION_BYTES)
    match = _DESCRIPTION.match(description)
    if match is None:
        _fail("Description must begin with [workflow-stage:N] .")
    requested_stage = int(match.group(1))
    if requested_stage > len(frozen_stages):
        _fail("Description selects a stage absent from this ledger.")
    frozen = frozen_stages[requested_stage - 1]
    if description != f"[workflow-stage:{requested_stage}] {frozen['name']}":
        _fail("Description must exactly identify the selected frozen stage.")

    if tool_input["subagent_type"] != "general-purpose":
        _fail("Only the general-purpose Claude subagent type is supported.")
    requested_model = _text(tool_input["model"], "model", limit=256)
    if requested_model != frozen["worker_model"]:
        _fail("Requested model does not match the frozen worker model.")
    if requested_model not in allowed_models:
        _fail("Requested model alias has no trusted native resolution.")
    resolved_model = _text(allowed_models[requested_model], "resolved model", limit=256)
    expected_prompt = build_prompt(frozen)
    prompt = tool_input["prompt"]
    if not isinstance(prompt, str) or _utf8_size(prompt) > MAX_PACKET_BYTES:
        _fail("Prompt must be bounded valid UTF-8 text.")
    if prompt != expected_prompt:
        _fail("Prompt does not exactly match the canonical frozen-stage packet.")

    frozen_bytes = _canonical_json(_packet(frozen))
    result = {
        "schema": SCHEMA_VERSION,
        "stage_number": requested_stage,
        "worker_id": frozen["worker_id"],
        "requested_model": requested_model,
        "resolved_model": resolved_model,
        "stage_hash": hashlib.sha256(frozen_bytes).hexdigest(),
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8", "strict")).hexdigest(),
    }
    return MappingProxyType(result)

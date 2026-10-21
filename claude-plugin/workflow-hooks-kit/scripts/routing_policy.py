"""Pure, bounded selection of a declared route from a trusted policy."""
from __future__ import annotations

import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

MAX_POLICY_BYTES = 16_384
MAX_MODELS = 32
MAX_PROFILES = 32
MAX_CAPABILITIES = 64
MAX_LABEL_BYTES = 256
MAX_STAGE_BYTES = 32_768
_PRINTABLE_ASCII = re.compile(r"^[!-~]+$")


def _label(value: Any, field: str) -> str:
    if (not isinstance(value, str) or not value or len(value.encode("utf-8", "strict")) > MAX_LABEL_BYTES
            or not value.isascii() or _PRINTABLE_ASCII.fullmatch(value) is None):
        raise ValueError(f"{field} must be bounded printable ASCII.")
    return value


def _unique_strings(value: Any, field: str) -> list[str]:
    if type(value) is not list or not value or len(value) > MAX_CAPABILITIES:
        raise ValueError(f"{field} must be a nonempty bounded list.")
    values = [_label(item, field) for item in value]
    if len(set(values)) != len(values):
        raise ValueError(f"{field} must contain unique values.")
    return values


def validate_policy(policy: Any) -> tuple[dict[str, Any], bytes]:
    """Validate and canonicalize schema-2 policy without modifying its input."""
    if type(policy) is not dict or set(policy) != {"schema", "models", "profiles"}:
        raise ValueError("Policy must contain exactly schema, models, and profiles.")
    if type(policy["schema"]) is not int or policy["schema"] != 2:
        raise ValueError("Policy schema must be integer 2.")
    models, profiles = policy["models"], policy["profiles"]
    if type(models) is not dict or not 1 <= len(models) <= MAX_MODELS:
        raise ValueError("Policy models must contain 1 to 32 aliases.")
    if type(profiles) is not dict or not 1 <= len(profiles) <= MAX_PROFILES:
        raise ValueError("Policy profiles must contain 1 to 32 profiles.")
    checked_models: dict[str, dict[str, Any]] = {}
    for raw_alias, entry in models.items():
        alias = _label(raw_alias, "Model alias")
        if type(entry) is not dict or set(entry) != {"native_id", "rank", "capabilities"}:
            raise ValueError("Each model must contain exactly native_id, rank, and capabilities.")
        native_id = _label(entry["native_id"], "Native model ID")
        rank = entry["rank"]
        if type(rank) is not int or rank < 0:
            raise ValueError("Model rank must be a nonnegative integer.")
        checked_models[alias] = {"native_id": native_id, "rank": rank,
                                 "capabilities": _unique_strings(entry["capabilities"], "Model capabilities")}
    checked_profiles: dict[str, dict[str, list[str]]] = {}
    for raw_name, entry in profiles.items():
        name = _label(raw_name, "Profile name")
        if type(entry) is not dict or set(entry) != {"requires"}:
            raise ValueError("Each profile must contain exactly requires.")
        checked_profiles[name] = {"requires": _unique_strings(entry["requires"], "Profile requirements")}
    canonical = {"schema": 2, "models": checked_models, "profiles": checked_profiles}
    try:
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                             allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Policy cannot be encoded canonically.") from exc
    if len(encoded) > MAX_POLICY_BYTES:
        raise ValueError("Policy exceeds 16 KiB.")
    return canonical, encoded


def select_route(stage: Mapping[str, Any], policy: Any, override_alias: str | None = None):
    """Return an effective copied stage and immutable route binding.

    An explicit trusted alias is honored even when it misses profile
    capabilities; those gaps are disclosed in the binding.
    """
    if not isinstance(stage, Mapping):
        raise ValueError("Stage must be a mapping.")
    try:
        source_bytes = json.dumps(dict(stage), ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False).encode("utf-8", "strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Stage must be bounded JSON data.") from exc
    if len(source_bytes) > MAX_STAGE_BYTES:
        raise ValueError("Stage exceeds 32 KiB.")
    if not isinstance(stage.get("worker_model"), str) or not stage["worker_model"].startswith("auto:"):
        raise ValueError("Stage worker_model must name an auto:<profile> route.")
    profile = _label(stage["worker_model"][5:], "Profile name")
    checked, encoded_policy = validate_policy(policy)
    if profile not in checked["profiles"]:
        raise ValueError("Requested routing profile is absent from policy.")
    required = checked["profiles"][profile]["requires"]
    if override_alias is not None:
        selected = _label(override_alias, "Override alias")
        if selected not in checked["models"]:
            raise ValueError("Explicit model override is absent from policy.")
        override_used = True
    else:
        adequate = [(entry["rank"], alias) for alias, entry in checked["models"].items()
                    if set(required).issubset(entry["capabilities"])]
        if not adequate:
            raise ValueError("No policy model satisfies the profile capabilities.")
        _rank, selected = min(adequate)
        override_used = False
    entry = checked["models"][selected]
    missing = tuple(sorted(set(required) - set(entry["capabilities"])))
    effective = json.loads(json.dumps(dict(stage), ensure_ascii=False, allow_nan=False))
    effective["worker_model"] = selected
    binding = {"profile": profile, "selected_alias": selected,
               "expected_native_model": entry["native_id"],
               "policy_hash": hashlib.sha256(encoded_policy).hexdigest(),
               "source_stage_hash": hashlib.sha256(source_bytes).hexdigest(),
               "override": override_used, "missing_capabilities": missing}
    return effective, MappingProxyType(binding)

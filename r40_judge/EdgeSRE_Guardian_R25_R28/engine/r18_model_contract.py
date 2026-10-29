"""R18 compact Nemotron decision contract. No network operation in this module."""
from __future__ import annotations

import hashlib
import json

from r12_provider_parser import ProviderParseError, parse_nebius_response
from r16_lab import safety_gate

MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
MAX_COMPLETION_TOKENS = 2048
MAX_BODY_BYTES = 7900
MAX_FINAL_BYTES = 700
MAX_EXPLANATION_CHARS = 160
FORBIDDEN_KEYS = {"hidden_required", "expected", "family", "case_id", "seed",
                  "r16_reference", "old_baseline", "correct_answer"}


def _forbidden_nested_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in FORBIDDEN_KEYS or _forbidden_nested_key(item)
                   for key, item in value.items())
    return isinstance(value, list) and any(_forbidden_nested_key(item) for item in value)


def build_request(observation: dict) -> tuple[bytes, dict]:
    allowed = {"health_http", "checkout_http", "metrics", "logs", "configuration",
               "available_actions", "repair_feedback"}
    required = allowed - {"repair_feedback"}
    if not isinstance(observation, dict) or set(observation) - allowed or not required <= set(observation):
        raise ValueError("OBSERVATION_FIELDS_INVALID")
    if _forbidden_nested_key(observation):
        raise ValueError("HIDDEN_OR_BASELINE_FIELD_FORBIDDEN")
    payload = {
        "model": MODEL, "temperature": 0, "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "stream": False, "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": (
                "Diagnose an isolated HTTP service from the supplied observations only. "
                "Return exactly one compact JSON object with diagnosis, action, args, reason. "
                "Diagnosis and reason: each at most 160 characters; no preamble or code fence. "
                "Use HTTP, logs, metrics, current settings and failure feedback. "
                "An unchanged target after an allowed change can mean too small a value or a wrong cause; "
                "do not treat either as certain without evidence. A cleared target with failing HTTP suggests another cause. "
                "Do not repeat any failed action/value pair. Choose exactly one allowed action and value, "
                "or abstain with args {} if evidence or safe actions are insufficient. "
                "Setting actions use args {\"value\":integer}. Do not request files, commands, credentials, "
                "external network access or hidden answers. Keep reasoning brief and finish the final JSON.")},
            {"role": "user", "content": json.dumps(observation, sort_keys=True,
                                                   separators=(",", ":"), ensure_ascii=True)},
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if not 0 < len(raw) <= MAX_BODY_BYTES:
        raise ValueError("REQUEST_BODY_SIZE_CAP")
    return raw, {"body_bytes": len(raw), "body_sha256": hashlib.sha256(raw).hexdigest(),
                 "max_completion_tokens": MAX_COMPLETION_TOKENS, "model": MODEL,
                 "response_format": "json_object"}


def parse_and_gate(raw: bytes, observation: dict, prior: list[dict], audit: dict) -> tuple[dict, dict]:
    """Reasoning is evidence only; a complete final JSON and Safety Gate are required."""
    try:
        envelope = json.loads(raw)
        message = envelope["choices"][0]["message"]
        if isinstance(message, dict):
            for field in ("reasoning", "reasoning_content"):
                value = message.get(field)
                audit[field + "_present"] = isinstance(value, str) and bool(value)
                audit[field + "_chars"] = len(value) if isinstance(value, str) else 0
            audit["final_content_present"] = isinstance(message.get("content"), str) and bool(message["content"].strip())
    except (ValueError, KeyError, IndexError, TypeError):
        pass
    decision, provider = parse_nebius_response(raw, MODEL, audit)
    content = audit.get("content")
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FINAL_BYTES or content.lstrip().startswith("```"):
        audit["parse_error"] = "FINAL_JSON_NOT_COMPACT"
        raise ProviderParseError("FINAL_JSON_NOT_COMPACT")
    if any(not isinstance(decision.get(key), str) or len(decision[key]) > MAX_EXPLANATION_CHARS
           for key in ("diagnosis", "reason")):
        audit["parse_error"] = "EXPLANATION_TOO_LONG"
        raise ProviderParseError("EXPLANATION_TOO_LONG")
    safety_gate(decision, observation, prior)
    return decision, provider

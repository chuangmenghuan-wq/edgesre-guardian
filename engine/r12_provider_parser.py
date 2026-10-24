"""Bounded Nebius chat-response parser. Parsing alone never authorizes an action."""
from __future__ import annotations

import hashlib
import json
from typing import Any


class ProviderParseError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(audit: dict, code: str) -> None:
    audit["parse_error"] = code
    raise ProviderParseError(code)


def _decision_json(value: str, audit: dict) -> dict:
    candidate = value.strip()
    if candidate.startswith("```"):
        lines = candidate.split("\n", 1)
        if len(lines) != 2 or lines[0].lower() not in ("```", "```json") or not lines[1].endswith("```"):
            _fail(audit, "INVALID_JSON_FENCE")
        candidate = lines[1][:-3].strip()
    try:
        decision = json.loads(candidate)
    except (ValueError, TypeError):
        _fail(audit, "DECISION_JSON_INVALID")
    if not isinstance(decision, dict):
        _fail(audit, "DECISION_NOT_OBJECT")
    return decision


def parse_nebius_response(raw: bytes, expected_model: str, audit: dict) -> tuple[dict, dict]:
    """Read a complete non-streaming response; keep unknown fields as evidence.

    Reasoning text is never executable. Tool calls are only accepted as a single
    explicit propose_repair function call. The caller must still apply Safety Gate.
    """
    audit["response_bytes"] = len(raw)
    audit["response_sha256"] = hashlib.sha256(raw).hexdigest()
    if not raw or len(raw) > 100_000:
        _fail(audit, "RESPONSE_SIZE_INVALID")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        _fail(audit, "RESPONSE_JSON_INVALID")
    audit["json_top_level_type"] = type(data).__name__
    if not isinstance(data, dict):
        _fail(audit, "RESPONSE_NOT_OBJECT")
    if "error" in data:
        audit["provider_error"] = data["error"]
        _fail(audit, "PROVIDER_ERROR_ENVELOPE")
    audit["response_model"] = data.get("model")
    audit["response_id"] = data.get("id")
    audit["usage"] = data.get("usage")
    if data.get("model") != expected_model:
        _fail(audit, "PROVIDER_MODEL_MISMATCH")
    if not isinstance(data.get("id"), str) or not data["id"].strip():
        _fail(audit, "MISSING_PROVIDER_RESPONSE_ID")
    if not isinstance(data.get("usage"), dict):
        _fail(audit, "MISSING_PROVIDER_USAGE")
    if any(type(data["usage"].get(field)) is not int or data["usage"][field] < 0
           for field in ("prompt_tokens", "completion_tokens", "total_tokens")):
        _fail(audit, "PROVIDER_USAGE_INVALID")
    choices = data.get("choices")
    audit["choices_count"] = len(choices) if isinstance(choices, list) else None
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        _fail(audit, "CHOICES_SHAPE_INVALID")
    choice = choices[0]
    finish = choice.get("finish_reason")
    audit["finish_reason"] = finish
    if finish == "length":
        _fail(audit, "TRUNCATED_MODEL_OUTPUT")
    if finish not in ("stop", "tool_calls"):
        _fail(audit, "FINISH_REASON_UNSAFE")
    message = choice.get("message")
    if not isinstance(message, dict):
        _fail(audit, "MESSAGE_SHAPE_INVALID")
    content: Any = message.get("content")
    if isinstance(content, list):
        if not all(isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str) for part in content):
            _fail(audit, "CONTENT_PARTS_UNSUPPORTED")
        content = "".join(part["text"] for part in content)
    audit["content"] = content if isinstance(content, str) else None
    reasoning = message.get("reasoning_content")
    audit["reasoning_content_present"] = bool(reasoning)
    audit["reasoning_content_type"] = type(reasoning).__name__ if reasoning is not None else None
    calls = message.get("tool_calls")
    audit["tool_calls_count"] = len(calls) if isinstance(calls, list) else (0 if calls is None else None)
    if isinstance(content, str) and content.strip():
        if calls:
            _fail(audit, "AMBIGUOUS_CONTENT_AND_TOOL_CALLS")
        decision = _decision_json(content, audit)
        audit["decision_source"] = "message.content"
    elif isinstance(calls, list) and len(calls) == 1:
        if finish != "tool_calls":
            _fail(audit, "TOOL_FINISH_MISMATCH")
        call = calls[0]
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or function.get("name") != "propose_repair" or not isinstance(function.get("arguments"), str):
            _fail(audit, "TOOL_CALL_UNSUPPORTED")
        decision = _decision_json(function["arguments"], audit)
        audit["decision_source"] = "tool_calls.propose_repair"
    else:
        _fail(audit, "NO_FINAL_DECISION")
    audit["provider_id"] = data["id"]
    return decision, {"provider": "nebius_token_factory", "model": expected_model,
                      "id": data["id"], "usage": data["usage"], "real_nebius_inference": True}

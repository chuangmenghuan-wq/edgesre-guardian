"""R32 one-choice Nemotron contract: no fragile candidate index."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

R28_ENGINE = Path(__file__).resolve().parents[1] / "EdgeSRE_Guardian_R25_R28" / "engine"
sys.path.insert(0, str(R28_ENGINE))
from r26_model_contract import MODEL, _options, _memory  # noqa: E402
from r12_provider_parser import ProviderParseError, parse_nebius_response  # noqa: E402
from r16_lab import safety_gate  # noqa: E402
from r18_model_contract import _forbidden_nested_key  # noqa: E402

MAX_BODY_BYTES = 7900
MAX_COMPLETION_TOKENS = 3072
MAX_FINAL_BYTES = 1500
REASONING_EFFORT = "low"


def obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def supported_options(observation: dict) -> list[dict]:
    return [x for x in _options(observation) if x["signal"] or x["log_match"]]


def schema_for(observation: dict) -> dict:
    options = supported_options(observation)
    actions = sorted({x["action"] for x in options} | {"abstain"})
    values = sorted({x["value"] for x in options})
    metrics = sorted(set(observation["metrics"]) | {"checkout_http"})
    text = {"type": "string", "maxLength": 100}
    return obj({
        "hypotheses": {"type": "array", "items": text, "minItems": 1, "maxItems": 2},
        "action": {"type": "string", "enum": actions},
        "value": {"type": ["integer", "null"], "enum": values + [None]},
        "reason": text,
        "predict_metric": {"type": "string", "enum": metrics},
        "predict_direction": {"type": "string", "enum": ["decrease", "increase", "recover", "unknown"]},
        "if_failed": text,
    })


SYSTEM = (
    "You are a cautious SRE planner. Reply with one short JSON object only. "
    "Use only listed evidence-supported action/value pairs and observed metric names. "
    "Compare supported choices, then return exactly one action and its value. "
    "Value is a JSON integer, or null only for abstain. Do not repeat a failed pair. "
    "Current HTTP/logs/metrics outrank earlier guesses. If a change partly helps but HTTP still fails, "
    "use feedback to test the next cause. Abstain when no supported safe repair remains, "
    "including after the largest allowed value has failed. "
    "Keep hypotheses, reasons and if_failed brief. No prose, markdown, commands, or invented metrics."
)


def build_request(observation: dict) -> tuple[bytes, dict]:
    fields = {"health_http", "checkout_http", "metrics", "logs", "configuration",
              "available_actions", "repair_feedback"}
    if (not isinstance(observation, dict) or set(observation) - fields or
        not fields - {"repair_feedback"} <= set(observation) or
        _forbidden_nested_key(observation)):
        raise ValueError("OBSERVATION_INVALID_OR_HIDDEN")
    grouped = {}
    for option in supported_options(observation):
        group = grouped.setdefault(option["action"], {"values": [], "signal": option["signal"],
                                                      "log_match": option["log_match"]})
        group["values"].append(option["value"])
    state = {k: observation[k] for k in ("health_http", "checkout_http", "metrics", "logs", "configuration")}
    state["options"] = grouped
    state["memory"] = _memory(observation)
    state["remaining_attempts"] = observation.get("repair_feedback", {}).get("remaining_attempts_including_this_one", 4)
    body = {"model": MODEL, "temperature": 0, "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "reasoning_effort": REASONING_EFFORT, "stream": False,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "edgesre_r32_single_choice", "strict": True, "schema": schema_for(observation)}},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps(state, sort_keys=True, separators=(",", ":"))}]}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError("REQUEST_BODY_SIZE_CAP")
    return raw, {"body_bytes": len(raw), "body_sha256": hashlib.sha256(raw).hexdigest(),
                 "model": MODEL, "reasoning_effort": REASONING_EFFORT,
                 "max_completion_tokens": MAX_COMPLETION_TOKENS,
                 "response_format": "json_schema", "option_count": sum(len(x["values"]) for x in grouped.values())}


def fail(audit: dict, code: str):
    audit["parse_error"] = code
    raise ProviderParseError(code)


def parse_and_gate(raw: bytes, observation: dict, prior: list[dict], audit: dict) -> tuple[dict, dict]:
    plan, provider = parse_nebius_response(raw, MODEL, audit)
    content = audit.get("content")
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FINAL_BYTES:
        fail(audit, "FINAL_JSON_SIZE_INVALID")
    schema = schema_for(observation)
    if not isinstance(plan, dict) or set(plan) != set(schema["properties"]):
        fail(audit, "PLAN_SCHEMA_INVALID")
    if (not isinstance(plan["hypotheses"], list) or not 1 <= len(plan["hypotheses"]) <= 2 or
        any(not isinstance(x, str) or not 1 <= len(x) <= 100 for x in plan["hypotheses"])):
        fail(audit, "HYPOTHESES_INVALID")
    allowed = {(x["action"], x["value"]) for x in supported_options(observation)} | {("abstain", None)}
    if (not isinstance(plan["action"], str) or type(plan["value"]) not in (int, type(None)) or
        (plan["action"], plan["value"]) not in allowed or
        not isinstance(plan["reason"], str) or not 1 <= len(plan["reason"]) <= 100):
        fail(audit, "CHOICE_INVALID")
    if (not isinstance(plan["predict_metric"], str) or
        plan["predict_metric"] not in set(observation["metrics"]) | {"checkout_http"} or
        not isinstance(plan["predict_direction"], str) or
        plan["predict_direction"] not in {"decrease", "increase", "recover", "unknown"} or
        not isinstance(plan["if_failed"], str) or len(plan["if_failed"]) > 100):
        fail(audit, "PREDICTION_INVALID")
    if plan["action"] != "abstain":
        match = next(x for x in supported_options(observation) if (x["action"], x["value"]) == (plan["action"], plan["value"]))
        if not match["signal"] and not match["log_match"]:
            fail(audit, "ACTION_UNSUPPORTED_BY_OBSERVATION")
    decision = {"diagnosis": plan["hypotheses"][0], "action": plan["action"],
                "args": {} if plan["action"] == "abstain" else {"value": plan["value"]},
                "reason": plan["reason"]}
    safety_gate(decision, observation, prior)
    provider["validated_plan"] = {"hypotheses": [{"cause": x} for x in plan["hypotheses"]],
                                  "chosen": {"action": plan["action"], "value": plan["value"], "reason": plan["reason"]},
                                  "prediction": {"metric": plan["predict_metric"],
                                                 "direction": plan["predict_direction"]},
                                  "if_failed": plan["if_failed"]}
    audit["selected_action"] = plan["action"]
    audit["selected_value"] = plan["value"]
    return decision, provider

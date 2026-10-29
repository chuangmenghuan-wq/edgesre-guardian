"""Bounded model planning contract. A validated plan yields one R16-gated action.

The model ranks candidates; this module only removes invalid choices and checks
that a complete final decision exists. No model text is executed as a command.
"""
from __future__ import annotations

import hashlib
import json

from r12_provider_parser import ProviderParseError, parse_nebius_response
from r16_lab import FIELDS, safety_gate
from r18_model_contract import MODEL, _forbidden_nested_key

MAX_BODY_BYTES = 7900
MAX_FINAL_BYTES = 1100
MAX_COMPLETION_TOKENS = 2048
METRIC_FOR_ACTION = {
    "set_db_pool_size": ("db_pool_waiters", "database acquire"),
    "set_upstream_timeout_ms": ("upstream_p95_ms", "upstream response deadline"),
    "set_retry_limit": ("retry_attempts_per_request", "retries amplified"),
    "set_queue_consumers": ("oldest_queue_item_ms", "queue age"),
    "set_worker_limit": ("queue_depth", "workers saturated"),
    "set_request_timeout_ms": ("request_timeout_count", "request deadline"),
}


def _fail(audit: dict, code: str) -> None:
    audit["parse_error"] = code
    raise ProviderParseError(code)


def _options(observation: dict) -> list[dict]:
    failed = {(x.get("action"), x.get("args", {}).get("value")) for x in
              observation.get("repair_feedback", {}).get("previous_attempts", [])}
    metrics = observation["metrics"]
    logs = " | ".join(observation["logs"]).lower()
    options = []
    for action, (field, direction) in FIELDS.items():
        metric, clue = METRIC_FOR_ACTION[action]
        value = metrics.get(metric)
        signal = (value > (500 if metric == "upstream_p95_ms" else 200 if metric == "oldest_queue_item_ms"
                           else 1 if metric == "retry_attempts_per_request" else 0)) if isinstance(value, (int, float)) else False
        for candidate in observation["available_actions"][action]:
            if ((direction == "up" and candidate <= observation["configuration"][field]) or
                (direction == "down" and candidate >= observation["configuration"][field]) or
                (action, candidate) in failed):
                continue
            options.append({"action": action, "value": candidate,
                            "signal": bool(signal), "log_match": clue in logs})
    return options


def _memory(observation: dict) -> list[dict]:
    rows = observation.get("repair_feedback", {}).get("previous_attempts", [])
    compact = []
    for row in rows:
        item = {"action": row.get("action"), "value": row.get("args", {}).get("value")}
        for source, target in (("assessment", "assessment"), ("target_before", "target_before"),
                               ("target_after_action", "target_after"), ("http_after_action", "http_after"),
                               ("step_rolled_back", "rolled_back"), ("hypotheses", "hypotheses"),
                               ("prediction", "prediction"), ("prediction_match", "prediction_match"),
                               ("if_failed", "if_failed")):
            if source in row:
                item[target] = row[source]
        compact.append(item)
    return compact


def build_request(observation: dict) -> tuple[bytes, dict]:
    allowed = {"health_http", "checkout_http", "metrics", "logs", "configuration",
               "available_actions", "repair_feedback"}
    if (not isinstance(observation, dict) or set(observation) - allowed or
            not allowed - {"repair_feedback"} <= set(observation) or
            _forbidden_nested_key(observation)):
        raise ValueError("OBSERVATION_FIELDS_INVALID_OR_HIDDEN")
    options = _options(observation)
    grouped = {}
    for option in options:
        group = grouped.setdefault(option["action"], {"values": [], "signal": option["signal"],
                                                      "log_match": option["log_match"]})
        group["values"].append(option["value"])
    state = {k: observation[k] for k in ("health_http", "checkout_http", "metrics", "logs", "configuration")}
    state["options"] = grouped
    state["memory"] = _memory(observation)
    state["remaining_attempts"] = observation.get("repair_feedback", {}).get("remaining_attempts_including_this_one", 4)
    system = (
        "Bounded SRE planner. Current HTTP/logs/metrics outrank memory. Compare up to 3 listed actions; "
        "abstain if evidence or safe options are insufficient. Failed value unchanged: magnitude or cause "
        "uncertain. Improved target but bad HTTP: consider another bottleneck. Never repeat a failed pair. "
        "Return only compact JSON: hypotheses=[{cause,support,counter}] (1-2), "
        "candidates=[{action,value,fit,gain,risk,info,cost,why}] (1-3), selected=index, "
        "prediction={metric,direction}, if_failed=next diagnostic step. Abstain value=null. "
        "Scores 0..2; text <=100 chars. metric is a current metric or checkout_http; direction "
        "decrease/increase/recover/unknown. No commands, tools, hidden answers or long reasoning."
    )
    body = {"model": MODEL, "temperature": 0, "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "stream": False, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(state, sort_keys=True, separators=(",", ":"))}]}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError("REQUEST_BODY_SIZE_CAP")
    return raw, {"model": MODEL, "body_bytes": len(raw),
                 "body_sha256": hashlib.sha256(raw).hexdigest(),
                 "max_completion_tokens": MAX_COMPLETION_TOKENS,
                 "response_format": "json_object", "option_count": len(options)}


def parse_and_gate(raw: bytes, observation: dict, prior: list[dict], audit: dict) -> tuple[dict, dict]:
    plan, provider = parse_nebius_response(raw, MODEL, audit)
    content = audit.get("content")
    if (not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FINAL_BYTES or
            content.lstrip().startswith("```")):
        _fail(audit, "FINAL_JSON_SIZE_INVALID")
    if not isinstance(plan, dict) or set(plan) != {"hypotheses", "candidates", "selected", "prediction", "if_failed"}:
        _fail(audit, "PLAN_SCHEMA_INVALID")
    hypotheses, candidates = plan["hypotheses"], plan["candidates"]
    if not isinstance(hypotheses, list) or not 1 <= len(hypotheses) <= 2:
        _fail(audit, "HYPOTHESES_INVALID")
    for hypothesis in hypotheses:
        if (not isinstance(hypothesis, dict) or set(hypothesis) != {"cause", "support", "counter"} or
                any(not isinstance(v, str) or len(v) > 100 for v in hypothesis.values()) or
                not hypothesis["cause"]):
            _fail(audit, "HYPOTHESIS_INVALID")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
        _fail(audit, "CANDIDATES_INVALID")
    allowed = {(x["action"], x["value"]) for x in _options(observation)} | {("abstain", None)}
    pairs = set()
    for candidate in candidates:
        if (not isinstance(candidate, dict) or
                set(candidate) != {"action", "value", "fit", "gain", "risk", "info", "cost", "why"} or
                not isinstance(candidate["action"], str) or
                type(candidate["value"]) not in (int, type(None)) or
                (candidate["action"], candidate["value"]) not in allowed or
                any(type(candidate[k]) is not int or not 0 <= candidate[k] <= 2
                    for k in ("fit", "gain", "risk", "info", "cost")) or
                not isinstance(candidate["why"], str) or not 1 <= len(candidate["why"]) <= 100):
            _fail(audit, "CANDIDATE_INVALID")
        pair = (candidate["action"], candidate["value"])
        if pair in pairs:
            _fail(audit, "DUPLICATE_CANDIDATE")
        pairs.add(pair)
    selected = plan["selected"]
    if type(selected) is not int or not 0 <= selected < len(candidates):
        _fail(audit, "SELECTION_INVALID")
    prediction = plan["prediction"]
    if (not isinstance(prediction, dict) or set(prediction) != {"metric", "direction"} or
            prediction["metric"] not in set(observation["metrics"]) | {"checkout_http"} or
            prediction["direction"] not in {"decrease", "increase", "recover", "unknown"} or
            not isinstance(plan["if_failed"], str) or len(plan["if_failed"]) > 100):
        _fail(audit, "PREDICTION_INVALID")
    pick = candidates[selected]
    if pick["action"] != "abstain":
        option = next(x for x in _options(observation)
                      if (x["action"], x["value"]) == (pick["action"], pick["value"]))
        if not option["signal"] and not option["log_match"]:
            _fail(audit, "ACTION_UNSUPPORTED_BY_OBSERVATION")
    decision = {"diagnosis": hypotheses[0]["cause"], "action": pick["action"],
                "args": {} if pick["action"] == "abstain" else {"value": pick["value"]},
                "reason": pick["why"]}
    safety_gate(decision, observation, prior)
    provider["validated_plan"] = plan
    audit["selected_action"] = pick["action"]
    audit["selected_value"] = pick["value"]
    return decision, provider

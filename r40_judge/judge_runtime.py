"""Public development scenario. Every decision here is an OFFLINE policy choice."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "EdgeSRE_Guardian_R34"))
sys.path.insert(0, str(HERE / "EdgeSRE_Guardian_R25_R28" / "engine"))

from contract import MODEL, build_request, schema_for  # noqa: E402
from public_integrity import verify_chain  # noqa: E402
from r16_lab import run_case  # noqa: E402

DEV_CASE = {
    "id": "D01_PUBLIC_DEVELOPMENT",
    "family": "db_pool_exhaustion",
    "expected": "repairable",
    "hidden_required": {"db_pool_size": 10},
    "initial": {"worker_limit": 4, "request_timeout_ms": 90, "db_pool_size": 4,
                "upstream_timeout_ms": 150, "retry_limit": 3, "queue_consumers": 4},
    "catalog": {"set_worker_limit": [6, 10], "set_request_timeout_ms": [160, 320],
                "set_db_pool_size": [8, 12], "set_upstream_timeout_ms": [260, 500],
                "set_retry_limit": [2, 1], "set_queue_consumers": [6, 10], "abstain": []},
    "max_attempts": 3,
}

DEV_CASES = {
    DEV_CASE["id"]: DEV_CASE,
    "D02_PUBLIC_UNREPAIRABLE": {**DEV_CASE,
        "id": "D02_PUBLIC_UNREPAIRABLE", "expected": "unrepairable",
        "hidden_required": {"db_pool_size": 20}},
    "D03_PUBLIC_COMPOUND": {**DEV_CASE,
        "id": "D03_PUBLIC_COMPOUND", "family": "compound_pool_retry",
        "hidden_required": {"db_pool_size": 10, "retry_limit": 1},
        "max_attempts": 4},
}


def offline_development_policy(observation: dict) -> tuple[dict, dict]:
    """A named fixture strategy; never described as a Nemotron decision."""
    prior = observation.get("repair_feedback", {}).get("previous_attempts", [])
    used = {(x["action"], x["args"].get("value")) for x in prior}
    possible = [v for v in observation["available_actions"]["set_db_pool_size"]
                if ("set_db_pool_size", v) not in used and v > observation["configuration"]["db_pool_size"]]
    retry = [v for v in observation["available_actions"]["set_retry_limit"]
             if ("set_retry_limit", v) not in used and v < observation["configuration"]["retry_limit"]]
    if observation["metrics"]["db_pool_waiters"] and possible:
        decision = {"diagnosis": "Public development fixture: database acquire wait",
                    "action": "set_db_pool_size", "args": {"value": possible[0]},
                    "reason": "Fixture policy tries the next unused allowlisted pool size"}
    elif observation["metrics"]["retry_attempts_per_request"] > 1 and retry:
        decision = {"diagnosis": "Public development fixture: retry amplification",
                    "action": "set_retry_limit", "args": {"value": min(retry)},
                    "reason": "Fixture policy chooses the lowest allowlisted retry limit"}
    else:
        decision = {"diagnosis": "No supported fixture action remains", "action": "abstain",
                    "args": {}, "reason": "Stop without another change"}
    return decision, {"provider": "offline_deterministic_development_policy",
                      "real_nebius_inference": False, "model": "NOT_RUN"}


def run_public_development_case(case_id: str = "D01_PUBLIC_DEVELOPMENT") -> dict:
    if case_id not in DEV_CASES:
        raise ValueError("PUBLIC_CASE_ID_INVALID")
    incident = run_case(copy.deepcopy(DEV_CASES[case_id]), offline_development_policy)
    if not verify_chain(incident["events"]):
        raise RuntimeError("EVENT_CHAIN_INVALID")
    return {"schema": "edgesre_r39_public_dev_run_1", "mode": "OFFLINE_POLICY_FRESH_LOCAL_HTTP",
            "model": "NOT_RUN", "case_id": case_id, "incident": incident,
            "private_blind_score": "NOT_APPLICABLE"}


def contract_preview() -> dict:
    """Show the exact frozen R34 request contract against public sample telemetry."""
    observation = {"health_http": 200, "checkout_http": 503,
                   "metrics": {"checkout_error_rate": .78, "queue_depth": 0,
                               "request_timeout_count": 0, "db_pool_waiters": 22,
                               "upstream_p95_ms": 95, "retry_attempts_per_request": 1,
                               "oldest_queue_item_ms": 20},
                   "logs": ["database acquire wait exceeded"],
                   "configuration": DEV_CASE["initial"],
                   "available_actions": DEV_CASE["catalog"]}
    body, meta = build_request(observation)
    schema = schema_for(observation)
    return {"schema": "edgesre_r38_contract_preview_1", "model": MODEL,
            "mode": "NO_PROVIDER_CALL", "r34_contract_sha256": hashlib.sha256(
                (HERE / "EdgeSRE_Guardian_R34" / "contract.py").read_bytes()).hexdigest(),
            "request_body_sha256": meta["body_sha256"], "request_body_bytes": len(body),
            "max_completion_tokens": meta["max_completion_tokens"],
            "response_format": meta["response_format"],
            "available_prediction_metrics": schema["properties"]["predict_metric"]["enum"],
            "available_action_names": schema["properties"]["action"]["enum"],
            "live_calls_exposed_by_this_build": 0}


if __name__ == "__main__":
    print(json.dumps(run_public_development_case(DEV_CASE["id"]), sort_keys=True))

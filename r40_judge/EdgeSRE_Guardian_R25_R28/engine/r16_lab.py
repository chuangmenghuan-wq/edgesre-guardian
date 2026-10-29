"""R16 isolated HTTP fault lab. Hidden case data never enters a decision callback.

Only a temporary JSON configuration is writable. No OS services or production
endpoints are touched. A callback may be a model adapter or an offline policy;
the returned provider metadata records which one it actually was.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from public_integrity import verify_chain

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "r16_frozen_cases.json"
FIELDS = {
    "set_worker_limit": ("worker_limit", "up"),
    "set_request_timeout_ms": ("request_timeout_ms", "up"),
    "set_db_pool_size": ("db_pool_size", "up"),
    "set_upstream_timeout_ms": ("upstream_timeout_ms", "up"),
    "set_retry_limit": ("retry_limit", "down"),
    "set_queue_consumers": ("queue_consumers", "up"),
}
FAULTS = {
    "worker_exhaustion": ("worker_limit",),
    "request_timeout": ("request_timeout_ms",),
    "db_pool_exhaustion": ("db_pool_size",),
    "upstream_timeout": ("upstream_timeout_ms",),
    "retry_storm": ("retry_limit",),
    "queue_overload": ("queue_consumers",),
    "compound_pool_retry": ("db_pool_size", "retry_limit"),
    "compound_queue_upstream": ("queue_consumers", "upstream_timeout_ms"),
}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def load_cases(path: Path = FROZEN) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    cases = manifest["cases"]
    if len(cases) != 10 or len({c["id"] for c in cases}) != 10:
        raise ValueError("FROZEN_CASE_COUNT_OR_ID")
    for case in cases:
        validate_case(case)
    return cases, hashlib.sha256(raw).hexdigest()


def validate_case(case: dict) -> None:
    if case.get("family") not in FAULTS or case.get("expected") not in ("repairable", "unrepairable"):
        raise ValueError("INVALID_CASE_FAMILY")
    required = case.get("hidden_required")
    if not isinstance(required, dict) or set(required) != set(FAULTS[case["family"]]):
        raise ValueError("INVALID_HIDDEN_REQUIREMENTS")
    initial = case.get("initial")
    catalog = case.get("catalog")
    if not isinstance(initial, dict) or set(initial) != {x[0] for x in FIELDS.values()}:
        raise ValueError("INVALID_INITIAL")
    if not isinstance(catalog, dict) or set(catalog) != set(FIELDS) | {"abstain"} or catalog["abstain"] != []:
        raise ValueError("INVALID_CATALOG")
    if any(type(v) is not int or v < 1 for v in list(required.values()) + list(initial.values())):
        raise ValueError("INVALID_NUMERIC_VALUE")
    for action, values in catalog.items():
        if action == "abstain":
            continue
        if not isinstance(values, list) or not values or len(values) != len(set(values)) or any(type(v) is not int or v < 1 for v in values):
            raise ValueError("INVALID_CANDIDATES")
    if type(case.get("max_attempts")) is not int or not 1 <= case["max_attempts"] <= 6:
        raise ValueError("INVALID_ATTEMPT_BUDGET")


def safety_gate(decision: dict, observation: dict, prior: list[dict]) -> tuple[str, dict]:
    if not isinstance(decision, dict) or set(decision) != {"diagnosis", "action", "args", "reason"}:
        raise ValueError("INVALID_DECISION_SCHEMA")
    if any(not isinstance(decision[k], str) or not 1 <= len(decision[k]) <= 500 for k in ("diagnosis", "action", "reason")):
        raise ValueError("INVALID_DECISION_TEXT")
    action, args = decision["action"], decision["args"]
    catalog = observation["available_actions"]
    if action not in catalog or not isinstance(args, dict):
        raise ValueError("ACTION_NOT_ALLOWLISTED")
    if action == "abstain":
        if args:
            raise ValueError("ABSTAIN_ARGS_FORBIDDEN")
        return action, args
    if set(args) != {"value"} or type(args["value"]) is not int or args["value"] not in catalog[action]:
        raise ValueError("VALUE_NOT_ALLOWLISTED")
    field, direction = FIELDS[action]
    current = observation["configuration"][field]
    if (direction == "up" and args["value"] <= current) or (direction == "down" and args["value"] >= current):
        raise ValueError("NON_PROGRESSING_ACTION")
    if any(p["action"] == action and p["args"] == args for p in prior):
        raise ValueError("REPEATED_FAILED_ACTION")
    return action, args


def symptom_score(metrics: dict) -> int:
    """Public telemetry only; never inspect hidden thresholds for progress."""
    return sum((metrics["queue_depth"] > 0, metrics["request_timeout_count"] > 0,
                metrics["db_pool_waiters"] > 0, metrics["upstream_p95_ms"] > 500,
                metrics["retry_attempts_per_request"] > 1, metrics["oldest_queue_item_ms"] > 200))


def run_case(case: dict, provider: Callable[[dict], tuple[dict, dict]] | None = None) -> dict:
    validate_case(case)
    original = copy.deepcopy(case["initial"])
    hidden = case["hidden_required"]
    active_fields = FAULTS[case["family"]]
    with tempfile.TemporaryDirectory(prefix="edgesre_r16_") as temp:
        config_path = Path(temp) / "config.json"
        config_path.write_bytes(canonical(original))
        original_bytes = config_path.read_bytes()

        def failures(cfg: dict) -> set[str]:
            return {field for field in active_fields if
                    (cfg[field] < hidden[field] if field != "retry_limit" else cfg[field] > hidden[field])}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cfg = json.loads(config_path.read_text())
                bad = failures(cfg)
                if self.path == "/health":
                    status, body = 200, {"process": "up"}
                elif self.path == "/checkout":
                    status = 200 if not bad else (504 if "upstream_timeout_ms" in bad or "request_timeout_ms" in bad else 503)
                    body = {"transaction": "ok" if not bad else "failed"}
                elif self.path == "/metrics":
                    status, body = 200, {
                        "checkout_error_rate": 0.0 if not bad else 0.78,
                        "queue_depth": 31 if bad & {"worker_limit", "queue_consumers"} else 0,
                        "request_timeout_count": 17 if bad & {"request_timeout_ms", "upstream_timeout_ms"} else 0,
                        "db_pool_waiters": 22 if "db_pool_size" in bad else 0,
                        "upstream_p95_ms": 810 if "upstream_timeout_ms" in bad else 95,
                        "retry_attempts_per_request": 8 if "retry_limit" in bad else 1,
                        "oldest_queue_item_ms": 1400 if "queue_consumers" in bad else 20,
                    }
                elif self.path == "/logs":
                    status = 200
                    lines = []
                    clues = {"worker_limit": "workers saturated", "request_timeout_ms": "request deadline exceeded",
                             "db_pool_size": "database acquire wait exceeded", "upstream_timeout_ms": "upstream response deadline exceeded",
                             "retry_limit": "retries amplified downstream load", "queue_consumers": "queue age increasing"}
                    lines = [clues[f] for f in active_fields if f in bad]
                    body = {"lines": lines or ["checkout completed"]}
                else:
                    status, body = 404, {"error": "not_found"}
                raw = canonical(body)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        events: list[dict] = []
        previous = "0" * 64

        def record(stage: str, data: dict) -> None:
            nonlocal previous
            item = {"seq": len(events) + 1, "stage": stage, "data": data, "previous_sha256": previous}
            previous = hashlib.sha256(canonical(item)).hexdigest()
            item["sha256"] = previous
            events.append(item)

        def get(path: str) -> tuple[int, dict]:
            try:
                with urllib.request.urlopen(base + path, timeout=3) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read())

        def observe() -> dict:
            health, _ = get("/health")
            checkout, _ = get("/checkout")
            _, metrics = get("/metrics")
            _, logs = get("/logs")
            return {"health_http": health, "checkout_http": checkout, "metrics": metrics,
                    "logs": logs["lines"], "configuration": json.loads(config_path.read_text()),
                    "available_actions": copy.deepcopy(case["catalog"])}

        try:
            before = observe()
            record("OBSERVE_HTTP_LOGS_METRICS", {"attempt": 0, "observation": before})
            history: list[dict] = []
            outcome = "BLOCKED_FAIL_CLOSED"
            provider_meta: dict = {"provider": "none", "real_nebius_inference": False}
            if before["checkout_http"] == 200:
                raise ValueError("CASE_NOT_FAULTED")
            for attempt in range(1, case["max_attempts"] + 1):
                observation = observe()
                if history:
                    observation["repair_feedback"] = {"previous_attempts": copy.deepcopy(history),
                                                       "instruction": "Update the hypothesis from new evidence; avoid a failed action or abstain."}
                record("OBSERVE_HTTP_LOGS_METRICS", {"attempt": attempt, "observation": observation})
                try:
                    if provider is None:
                        raise RuntimeError("MODEL_PROVIDER_UNAVAILABLE")
                    decision, provider_meta = provider(copy.deepcopy(observation))
                    if not isinstance(provider_meta, dict) or not isinstance(provider_meta.get("provider"), str):
                        raise ValueError("INVALID_PROVIDER_METADATA")
                    record("DECISION", {"attempt": attempt, "decision": decision, "provider": provider_meta})
                    action, args = safety_gate(decision, observation, history)
                    record("SAFETY_GATE", {"attempt": attempt, "status": "ABSTAIN" if action == "abstain" else "ALLOW",
                                           "action": action, "args": args})
                    if action == "abstain":
                        config_path.write_bytes(original_bytes)
                        record("ROLLBACK", {"reason": "ABSTAIN", "restored_original": True})
                        outcome = "ABSTAIN_NO_REPAIR"
                        break
                    updated = copy.deepcopy(observation["configuration"])
                    updated[FIELDS[action][0]] = args["value"]
                    config_path.write_bytes(canonical(updated))
                    record("EXECUTE_LOCAL_CONFIG", {"attempt": attempt, "action": action, "args": args})
                    verified = observe()
                    record("VERIFY_INDEPENDENT_HTTP", {"attempt": attempt, "health_http": verified["health_http"],
                                                       "checkout_http": verified["checkout_http"], "metrics": verified["metrics"]})
                    if verified["health_http"] == 200 and verified["checkout_http"] == 200:
                        outcome = "VERIFIED_RECOVERY"
                        break
                    progress = symptom_score(verified["metrics"]) < symptom_score(observation["metrics"])
                    if not progress:
                        config_path.write_bytes(canonical(observation["configuration"]))
                        record("STEP_ROLLBACK", {"attempt": attempt, "reason": "NO_OBSERVED_PROGRESS",
                                                 "restored_previous": config_path.read_bytes() == canonical(observation["configuration"])})
                        verified = observe()
                    else:
                        record("PARTIAL_PROGRESS", {"attempt": attempt, "remaining_symptoms": symptom_score(verified["metrics"])})
                    feedback = {"attempt": attempt, "action": action, "args": args,
                                "diagnosis": decision["diagnosis"], "http": {"health": verified["health_http"],
                                "checkout": verified["checkout_http"]}, "configuration": verified["configuration"],
                                "metrics": verified["metrics"], "logs": verified["logs"]}
                    history.append(feedback)
                    record("VERIFY_FAIL", feedback)
                    if attempt == case["max_attempts"]:
                        config_path.write_bytes(original_bytes)
                        record("ROLLBACK", {"reason": "ATTEMPT_BUDGET_EXHAUSTED", "restored_original": True})
                        outcome = "ROLLED_BACK_EXHAUSTED"
                except Exception as exc:
                    config_path.write_bytes(original_bytes)
                    record("FAIL_CLOSED", {"attempt": attempt, "reason_code": str(exc)[:120], "restored_original": True})
                    outcome = "BLOCKED_FAIL_CLOSED"
                    break
            after = observe()
            record("FINAL", {"outcome": outcome, "health_http": after["health_http"],
                             "checkout_http": after["checkout_http"]})
            if not verify_chain(events):
                raise AssertionError("EVENT_CHAIN_INVALID")
            return {"case_id": case["id"], "outcome": outcome, "before": before,
                    "after": {"health_http": after["health_http"], "checkout_http": after["checkout_http"],
                              "configuration": after["configuration"]}, "config_restored": config_path.read_bytes() == original_bytes,
                    "attempts": sum(e["stage"] == "DECISION" for e in events), "events": events,
                    "head_sha256": previous, "provider": provider_meta, "scope": "loopback_http_tempfile_only"}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

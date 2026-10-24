"""R9 extension of the existing EdgeSRE loopback lab. No production access.

The fault thresholds and fault family are chosen when the experiment starts.
The decision provider sees only HTTP observations, logs, metrics, current
configuration, and an action catalog. It does not receive the hidden threshold.
"""
from __future__ import annotations

import hashlib
import json
import random
import tempfile
import threading
from dataclasses import dataclass
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from guardian import verify_chain

WORKER_CHOICES = (4, 8, 16)
TIMEOUT_CHOICES = (100, 250, 500)
FAULTS = ("worker_exhaustion", "request_timeout")
COMPOUND_FAULT = "compound_capacity_timeout"


@dataclass(frozen=True)
class UnseenCase:
    fault: str
    hidden_required: int | dict[str, int]
    initial_config: dict[str, int]
    available_actions: dict[str, list[int]]


def generate_unseen_case(seed: int, *, fault: str | None = None,
                         unrepairable: bool = False) -> UnseenCase:
    """Generate an isolated case; the provider never receives this object."""
    rng = random.Random(seed)
    fault = fault or rng.choice(FAULTS)
    if fault not in FAULTS + (COMPOUND_FAULT,):
        raise ValueError("UNKNOWN_FAULT")
    workers = sorted(rng.sample((4, 6, 8, 10, 12, 16, 20), rng.randint(3, 5)))
    timeouts = sorted(rng.sample((100, 150, 200, 250, 350, 500, 700), rng.randint(3, 5)))
    if fault == COMPOUND_FAULT:
        initial = {"worker_limit": rng.choice((1, 2, 3)),
                   "request_timeout_ms": rng.choice((40, 60, 80))}
        required = {
            "worker_limit": rng.randint(initial["worker_limit"] + 1, max(workers)),
            "request_timeout_ms": rng.randint(initial["request_timeout_ms"] + 1, max(timeouts)),
        }
        if unrepairable:
            required[rng.choice(("worker_limit", "request_timeout_ms"))] += max(max(workers), max(timeouts))
    elif fault == "worker_exhaustion":
        initial = {"worker_limit": rng.choice((1, 2, 3)), "request_timeout_ms": 700}
        ceiling = max(workers)
        required = ceiling + rng.randint(1, 5) if unrepairable else rng.randint(initial["worker_limit"] + 1, ceiling)
    else:
        initial = {"worker_limit": 20, "request_timeout_ms": rng.choice((40, 60, 80))}
        ceiling = max(timeouts)
        required = ceiling + rng.randint(1, 80) if unrepairable else rng.randint(initial["request_timeout_ms"] + 1, ceiling)
    return UnseenCase(fault, required, initial,
                      {"set_worker_limit": workers, "set_request_timeout_ms": timeouts, "abstain": []})


def safe_decision(raw: Any, available_actions: dict[str, list[int]] | None = None) -> tuple[str, dict]:
    if not isinstance(raw, dict) or set(raw) != {"diagnosis", "action", "args", "reason"}:
        raise ValueError("INVALID_DECISION_SCHEMA")
    if any(not isinstance(raw[k], str) or not 1 <= len(raw[k]) <= 500
           for k in ("diagnosis", "action", "reason")):
        raise ValueError("INVALID_DECISION_TEXT")
    action, args = raw["action"], raw["args"]
    if available_actions is None:
        available_actions = {"set_worker_limit": list(WORKER_CHOICES),
                             "set_request_timeout_ms": list(TIMEOUT_CHOICES), "abstain": []}
    if not isinstance(args, dict):
        raise ValueError("INVALID_ACTION_ARGS")
    if action == "set_worker_limit":
        if set(args) != {"value"} or type(args["value"]) is not int or args["value"] not in available_actions.get(action, ()):
            raise ValueError("WORKER_LIMIT_NOT_ALLOWLISTED")
    elif action == "set_request_timeout_ms":
        if set(args) != {"value"} or type(args["value"]) is not int or args["value"] not in available_actions.get(action, ()):
            raise ValueError("TIMEOUT_NOT_ALLOWLISTED")
    elif action == "abstain":
        if args or "abstain" not in available_actions:
            raise ValueError("ABSTAIN_ARGS_FORBIDDEN")
    else:
        raise ValueError("ACTION_NOT_ALLOWLISTED")
    return action, args


def run_unseen_incident(
    decision_provider: Callable[[dict], tuple[dict, dict]] | None = None,
    *,
    seed: int | None = None,
    fault: str | None = None,
    max_attempts: int = 1,
    case: UnseenCase | None = None,
    strict_progress: bool = False,
    event_sink: Callable[[dict], None] | None = None,
) -> dict:
    """Run bounded proposal/verification cycles on one isolated HTTP incident."""
    if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
        raise ValueError("INVALID_ATTEMPT_LIMIT")
    if case is None:
        rng = random.Random(seed) if seed is not None else random.SystemRandom()
        fault = fault or rng.choice(FAULTS)
        if fault not in FAULTS:
            raise ValueError("UNKNOWN_FAULT")
        hidden_required = rng.randint(5, 12) if fault == "worker_exhaustion" else rng.randint(120, 350)
        original = {"worker_limit": 2 if fault == "worker_exhaustion" else 16,
                    "request_timeout_ms": 80 if fault == "request_timeout" else 500}
        actions = {"set_worker_limit": list(WORKER_CHOICES),
                   "set_request_timeout_ms": list(TIMEOUT_CHOICES), "abstain": []}
    else:
        if fault is not None or seed is not None:
            raise ValueError("CASE_CONFLICTS_WITH_GENERATION")
        fault, hidden_required = case.fault, case.hidden_required
        original, actions = dict(case.initial_config), {k: list(v) for k, v in case.available_actions.items()}
        if fault not in FAULTS + (COMPOUND_FAULT,):
            raise ValueError("INVALID_CASE")
        if fault == COMPOUND_FAULT:
            if not isinstance(hidden_required, dict) or set(hidden_required) != {
                "worker_limit", "request_timeout_ms"
            } or any(type(value) is not int or value <= 0 for value in hidden_required.values()):
                raise ValueError("INVALID_CASE")
        elif type(hidden_required) is not int or hidden_required <= 0:
            raise ValueError("INVALID_CASE")
        if set(original) != {"worker_limit", "request_timeout_ms"} or any(type(v) is not int or v <= 0 for v in original.values()):
            raise ValueError("INVALID_INITIAL_CONFIG")
        if set(actions) != {"set_worker_limit", "set_request_timeout_ms", "abstain"} or any(
            type(value) is not int or value <= 0 for options in actions.values() for value in options
        ):
            raise ValueError("INVALID_ACTION_CATALOG")
    with tempfile.TemporaryDirectory(prefix="edgesre_r9_") as temp:
        config = Path(temp) / "service-config.json"
        config.write_text(json.dumps(original, sort_keys=True), encoding="utf-8")
        original_bytes = config.read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cfg = json.loads(config.read_text(encoding="utf-8"))
                worker_required = (hidden_required["worker_limit"] if fault == COMPOUND_FAULT
                                   else hidden_required if fault == "worker_exhaustion" else 4)
                timeout_required = (hidden_required["request_timeout_ms"] if fault == COMPOUND_FAULT
                                    else hidden_required if fault == "request_timeout" else 100)
                worker_bad = cfg["worker_limit"] < worker_required
                timeout_bad = cfg["request_timeout_ms"] < timeout_required
                if self.path == "/health":
                    code, body = 200, {"process": "up"}
                elif self.path == "/checkout":
                    code, body = (503 if worker_bad or timeout_bad else 200), {"transaction": "failed" if worker_bad or timeout_bad else "ok"}
                elif self.path == "/metrics":
                    code, body = 200, {"queue_depth": 23 if worker_bad else 0,
                                       "request_timeout_count": 19 if timeout_bad else 0,
                                       "checkout_error_rate": 0.8 if worker_bad or timeout_bad else 0.0}
                elif self.path == "/logs":
                    lines = (["workers saturated", "checkout capacity exhausted"] if worker_bad else [])
                    lines += (["upstream deadline exceeded", "checkout timed out"] if timeout_bad else [])
                    code, body = 200, {"lines": lines or ["checkout completed"]}
                else:
                    code, body = 404, {"error": "not_found"}
                raw = json.dumps(body, sort_keys=True).encode()
                self.send_response(code)
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
        prev = "0" * 64

        def record(stage: str, data: dict):
            nonlocal prev
            item = {"seq": len(events) + 1, "stage": stage, "data": data, "previous_sha256": prev}
            prev = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            item["sha256"] = prev
            events.append(item)
            if event_sink is not None:
                event_sink(json.loads(json.dumps(item)))

        def read(path: str) -> tuple[int, dict]:
            try:
                with urllib.request.urlopen(base + path, timeout=3) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read())

        def observe() -> dict:
            health, _ = read("/health")
            checkout, _ = read("/checkout")
            _, metrics = read("/metrics")
            _, logs = read("/logs")
            return {"health_http": health, "checkout_http": checkout,
                    "metrics": metrics, "logs": logs["lines"],
                    "configuration": json.loads(config.read_text(encoding="utf-8")),
                    "available_actions": {k: list(v) for k, v in actions.items()}}

        try:
            before = observe()
            record("INJECT_ISOLATED_FAULT", {"fault": fault, "original_config_sha256": hashlib.sha256(original_bytes).hexdigest()})
            provider = {"provider": "none", "real_nebius_inference": False}
            history: list[dict] = []
            outcome = "BLOCKED_FAIL_CLOSED"
            for attempt in range(1, max_attempts + 1):
                observation = observe()
                if history:
                    observation["repair_feedback"] = {
                        "previous_attempts": json.loads(json.dumps(history)),
                        "instruction": "Reassess the prior hypothesis using the failed HTTP verification and propose a new listed action or abstain.",
                    }
                record("OBSERVE_HTTP_LOGS_METRICS", {"attempt": attempt, "observation": observation})
                try:
                    if decision_provider is None:
                        raise RuntimeError("MODEL_PROVIDER_UNAVAILABLE")
                    # Isolate the provider input from mutable lab state and hidden case data.
                    decision, provider = decision_provider(json.loads(json.dumps(observation)))
                    if not isinstance(provider, dict):
                        raise ValueError("INVALID_PROVIDER_METADATA")
                    record("MODEL_DIAGNOSIS_PLAN", {"attempt": attempt, "decision": decision, "provider": provider,
                                                   "observation_sha256": hashlib.sha256(json.dumps(observation, sort_keys=True).encode()).hexdigest()})
                    action, args = safe_decision(decision, actions)
                    if action != "abstain":
                        field = "worker_limit" if action == "set_worker_limit" else "request_timeout_ms"
                        if args["value"] < observation["configuration"][field] or (
                            strict_progress and args["value"] == observation["configuration"][field]
                        ):
                            raise ValueError("NON_PROGRESSING_ACTION")
                        if any(item["action"] == action and item["args"] == args for item in history):
                            raise ValueError("REPEATED_FAILED_ACTION")
                    record("SAFETY_GATE", {"attempt": attempt, "status": "ALLOW" if action != "abstain" else "ABSTAIN",
                                           "action": action, "args": args})
                    if action == "abstain":
                        config.write_bytes(original_bytes)
                        record("ROLLBACK", {"reason": "MODEL_ABSTAIN", "restored_original": config.read_bytes() == original_bytes})
                        outcome = "ABSTAIN_NO_REPAIR"
                        break
                    updated = dict(observation["configuration"])
                    updated[field] = args["value"]
                    config.write_text(json.dumps(updated, sort_keys=True), encoding="utf-8")
                    record("EXECUTE_ALLOWLISTED_LOCAL_WRITE", {"attempt": attempt, "action": action, "args": args,
                                                               "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest()})
                    verified = observe()
                    record("VERIFY_INDEPENDENT_HTTP", {"attempt": attempt, "health_http": verified["health_http"],
                                                        "checkout_http": verified["checkout_http"]})
                    if verified["health_http"] == 200 and verified["checkout_http"] == 200:
                        outcome = "VERIFIED_RECOVERY"
                        break
                    feedback = {"attempt": attempt, "action": action, "args": args,
                                "diagnosis": decision["diagnosis"], "reason": decision["reason"],
                                "http": {"health": verified["health_http"], "checkout": verified["checkout_http"]},
                                "configuration": verified["configuration"], "metrics": verified["metrics"],
                                "logs": verified["logs"]}
                    history.append(feedback)
                    record("VERIFY_FAIL", feedback)
                    if attempt == max_attempts:
                        config.write_bytes(original_bytes)
                        record("ROLLBACK", {"reason": "ATTEMPT_BUDGET_EXHAUSTED", "restored_original": config.read_bytes() == original_bytes})
                        outcome = "ROLLED_BACK_NOT_RECOVERED" if max_attempts == 1 else "ROLLED_BACK_EXHAUSTED"
                except Exception as exc:
                    config.write_bytes(original_bytes)
                    record("FAIL_CLOSED", {"attempt": attempt, "reason_code": str(exc)[:120],
                                           "restored_original": config.read_bytes() == original_bytes})
                    outcome = "BLOCKED_FAIL_CLOSED"
                    break
            end = observe()
            record("FINAL", {"outcome": outcome, "health_http": end["health_http"],
                             "checkout_http": end["checkout_http"], "attempts": len([e for e in events if e["stage"] == "MODEL_DIAGNOSIS_PLAN"])})
            if outcome == "VERIFIED_RECOVERY" and end["checkout_http"] != 200:
                raise AssertionError("FALSE_RECOVERY")
            if not verify_chain(events):
                raise AssertionError("BROKEN_EVENT_CHAIN")
            return {"fault": fault, "hidden_threshold": hidden_required, "outcome": outcome,
                    "provider": provider, "before": before,
                    "after": {"health_http": end["health_http"], "checkout_http": end["checkout_http"],
                              "configuration": end["configuration"]},
                    "config_restored": config.read_bytes() == original_bytes,
                    "attempts": len([e for e in events if e["stage"] == "MODEL_DIAGNOSIS_PLAN"]),
                    "events": events, "head_sha256": prev, "scope": "loopback_http_tempfile_only"}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=4)

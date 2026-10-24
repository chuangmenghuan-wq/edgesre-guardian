"""Single gated Nebius decision for the R9 unseen loopback fault lab.

Default invocation is precheck only. An attempt lock is written before any
network request, and an ambiguous result is never retried automatically.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import guardian
import live_probe_once as baseline
from r9_unseen_lab import run_unseen_incident
from r12_provider_parser import parse_nebius_response

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "R9_LIVE_ATTEMPT_STARTED.json"
RECEIPT = ROOT / "R9_LIVE_MODEL_RECEIPT.json"
FAILURE = ROOT / "R9_LIVE_MODEL_FAILURE.json"


def precheck() -> dict[str, bool]:
    checks = baseline.checks()
    checks["R9_NO_PREVIOUS_ATTEMPT"] = not LOCK.exists()
    checks["R9_NO_PREVIOUS_RECEIPT"] = not RECEIPT.exists()
    checks["R9_NO_PREVIOUS_FAILURE"] = not FAILURE.exists()
    checks["NEBIUS_ACCOUNT_MODEL_VERIFIED"] = False  # Must be confirmed in signed-in catalog.
    return checks


def request_decision(
    observation: dict,
    audit: dict,
    *,
    reserve_call: Callable[[float, int, str], None] | None = None,
) -> tuple[dict, dict]:
    key = os.environ["NEBIUS_API_KEY"]
    guardian.guard_real_inference(key, baseline.MODEL, baseline.URL)
    payload = {
        "model": baseline.MODEL,
        "temperature": 0,
        "max_completion_tokens": 1024,
        "stream": False,
        "messages": [
            {"role": "system", "content": (
                "Diagnose the incident from the supplied HTTP checks, logs, metrics and current configuration. "
                "Choose exactly one listed repair action and one listed candidate value, or abstain if uncertain. "
                "If repair_feedback exists, reassess why the previous hypothesis failed using the new HTTP result "
                "and current configuration; explain this in reason and choose a new listed candidate. "
                "Return JSON only with exactly diagnosis, action, args, reason. "
                "For set_worker_limit or set_request_timeout_ms, args must be {\"value\": integer}; "
                "for abstain, args must be {}. Do not request commands, files, network access, or credentials."
            )},
            {"role": "user", "content": json.dumps(observation, sort_keys=True)},
        ],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    # At the current official $0.06/$0.24 per 1M input/output tokens,
    # this byte-based bound includes a 512-token margin for chat framing.
    estimated_upper_usd = (len(body) + 512) * 0.06 / 1_000_000 + 1024 * 0.24 / 1_000_000
    audit["estimated_upper_usd"] = estimated_upper_usd
    audit["request_body_sha256"] = hashlib.sha256(body).hexdigest()
    audit["request_body_bytes"] = len(body)
    if estimated_upper_usd >= 0.009:
        raise RuntimeError("R11_COST_CAP_EXCEEDED")
    if reserve_call is None:
        guardian.reserve_one_live_call()
    else:
        reserve_call(estimated_upper_usd, len(body), audit["request_body_sha256"])
    request = urllib.request.Request(
        baseline.URL + "/chat/completions",
        body,
        method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read(100_001)
            audit["http_status"] = response.status
            audit["http_request_id"] = response.headers.get("x-request-id")
            audit["response_sha256"] = hashlib.sha256(raw).hexdigest()
            if len(raw) > 100_000:
                raise RuntimeError("NEBIUS_RESPONSE_TOO_LARGE")
    except urllib.error.HTTPError as exc:
        audit["http_status"] = exc.code
        audit["http_request_id"] = exc.headers.get("x-request-id") if exc.headers else None
        raise RuntimeError("NEBIUS_HTTP_" + str(exc.code)) from None
    except Exception as exc:
        raise RuntimeError("NEBIUS_REQUEST_" + type(exc).__name__) from None
    if key.encode() not in raw:
        audit["response_body_nonsecret"] = raw.decode("utf-8", errors="replace")
    else:
        audit["response_body_omitted"] = "CREDENTIAL_ECHO_DETECTED"
    return parse_nebius_response(raw, baseline.MODEL, audit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--account-model-verified", action="store_true",
                        help="Assert signed-in catalog confirms this exact NVIDIA model")
    args = parser.parse_args()
    checks = precheck()
    checks["NEBIUS_ACCOUNT_MODEL_VERIFIED"] = args.account_model_verified
    missing = [name for name, value in checks.items() if not value]
    if missing or not args.execute:
        print(json.dumps({"status": "BLOCKED_SAFE_NO_NETWORK" if missing else "READY_REQUIRES_EXECUTE",
                          "missing": missing, "provider_requests": 0, "model": baseline.MODEL}))
        return 3 if args.execute and missing else 0
    baseline.write_once(LOCK, {"status": "ATTEMPT_STARTED_UNVERIFIED",
                               "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                               "model": baseline.MODEL, "request_cap": 1})
    audit: dict = {}
    try:
        result = run_unseen_incident(lambda observation: request_decision(observation, audit))
        if not audit.get("provider_id"):
            raise RuntimeError("NO_VERIFIED_PROVIDER_RESPONSE")
        record = {"status": "REAL_NEBIUS_RESPONSE", "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "model": baseline.MODEL, "provider_audit": audit, "incident": result,
                  "autonomous_repair_verified": result["outcome"] == "VERIFIED_RECOVERY"}
        record["payload_sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        baseline.write_once(RECEIPT, record)
        print(json.dumps({"status": record["status"], "outcome": result["outcome"],
                          "receipt_path": str(RECEIPT)}))
        return 0
    except Exception as exc:
        baseline.write_once(FAILURE, {"status": "PROVIDER_CALL_FAILED_OR_UNVERIFIED",
                                      "error_code": str(exc)[:120], "provider_audit": audit,
                                      "no_automatic_retries": True})
        print(json.dumps({"status": "PROVIDER_CALL_FAILED_OR_UNVERIFIED", "failure_path": str(FAILURE)}))
        return 5


if __name__ == "__main__":
    raise SystemExit(main())

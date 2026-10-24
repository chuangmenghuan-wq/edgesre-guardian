"""R14 live adapter for the existing R9/R12 isolated HTTP feedback lab.

Offline by default. A distinct Owner record, interactive trial readback before
and after every request, and durable per-call reservations are mandatory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
R9 = Path(__file__).resolve().parent
sys.path.insert(0, str(R9))

import guardian  # noqa: E402
import live_probe_once as baseline  # noqa: E402
from r9_live_probe_once import request_decision  # noqa: E402
from r9_unseen_lab import generate_unseen_case, run_unseen_incident  # noqa: E402

MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
AUTH = ROOT / "private" / "r14_owner_authorization.json"
EVIDENCE = ROOT / "private" / "r14_live_evidence"
FINAL = ROOT / "private" / "R14_REAL_RESULT.json"
MAX_REQUESTS = 4
MAX_ESTIMATED_USD = 0.005
MAX_BODY_BYTES = 10_000
INPUT_USD_PER_M = 0.06
OUTPUT_USD_PER_M = 0.24
MAX_COMPLETION_TOKENS = 1024
Readback = Callable[[str, int, float], bool]


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_once(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def authorization_valid(path: Path = AUTH) -> bool:
    """The record is written only after the Owner's distinct R13 reply."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(data, dict)
        and data.get("round") == "R14"
        and data.get("owner_authorized") is True
        and data.get("max_new_requests") == MAX_REQUESTS
        and data.get("max_estimated_usd") == MAX_ESTIMATED_USD
        and data.get("funding") == "existing_free_trial_only"
        and data.get("no_card_charge") is True
        and isinstance(data.get("owner_reply"), str)
        and len(data["owner_reply"]) >= 8
    )


def actual_cost(usage: dict | None) -> float | None:
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if type(prompt) is not int or type(completion) is not int or prompt < 0 or completion < 0:
        return None
    return (prompt * INPUT_USD_PER_M + completion * OUTPUT_USD_PER_M) / 1_000_000


class RequestBudget:
    def __init__(self, directory: Path, readback: Readback):
        self.directory = directory
        self.readback = readback
        self.active_slot: int | None = None

    def slots(self) -> list[dict]:
        out = []
        for path in sorted(self.directory.glob("attempt_??_reserved.json")):
            out.append(json.loads(path.read_text(encoding="utf-8")))
        return out

    def reserve(self, estimated_upper_usd: float, body_bytes: int, body_sha256: str) -> None:
        if self.active_slot is not None:
            raise RuntimeError("R14_PREVIOUS_REQUEST_NOT_RECONCILED")
        if body_bytes > MAX_BODY_BYTES or body_bytes <= 0:
            raise RuntimeError("R14_REQUEST_BODY_SIZE_CAP")
        if not isinstance(body_sha256, str) or len(body_sha256) != 64:
            raise RuntimeError("R14_REQUEST_HASH_INVALID")
        if not 0 < estimated_upper_usd <= MAX_ESTIMATED_USD:
            raise RuntimeError("R14_REQUEST_COST_INVALID")
        previous = self.slots()
        slot = len(previous) + 1
        if slot > MAX_REQUESTS:
            raise RuntimeError("R14_REQUEST_COUNT_CAP")
        reserved_total = sum(item["estimated_upper_usd"] for item in previous)
        if reserved_total + estimated_upper_usd > MAX_ESTIMATED_USD:
            raise RuntimeError("R14_TOTAL_COST_CAP")
        if not self.readback("before", slot, estimated_upper_usd):
            raise RuntimeError("R14_TRIAL_READBACK_NOT_CONFIRMED")
        write_once(self.directory / f"attempt_{slot:02d}_reserved.json", {
            "slot": slot, "utc": utc(), "model": MODEL,
            "request_body_bytes": body_bytes, "request_body_sha256": body_sha256,
            "estimated_upper_usd": estimated_upper_usd,
            "reserved_total_usd": reserved_total + estimated_upper_usd,
            "trial_readback_before": True,
            "state": "ATTEMPT_RESERVED_UNVERIFIED_NO_AUTOMATIC_RETRY",
        })
        self.active_slot = slot

    def finish(self, audit: dict, provider: dict | None, error: str | None) -> None:
        slot = self.active_slot
        if slot is None:
            return
        upper = self.slots()[slot - 1]["estimated_upper_usd"]
        used = actual_cost(audit.get("usage"))
        write_once(self.directory / f"attempt_{slot:02d}_response.json", {
            "slot": slot, "utc": utc(), "audit": audit, "provider": provider,
            "error_code": error, "actual_model_cost_usd": used,
            "actual_exceeds_reserved_bound": used is not None and used > upper,
        })
        post_ok = self.readback("after", slot, upper)
        write_once(self.directory / f"attempt_{slot:02d}_post_usage.json", {
            "slot": slot, "utc": utc(), "trial_and_usage_readback_after": bool(post_ok),
        })
        self.active_slot = None
        if not post_ok:
            raise RuntimeError("R14_POST_USAGE_READBACK_FAILED")
        if used is not None and used > upper:
            raise RuntimeError("R14_ACTUAL_COST_EXCEEDS_RESERVED")


def interactive_readback(phase: str, slot: int, upper: float) -> bool:
    marker = f"R14_{phase.upper()}_TRIAL_OK_{slot}"
    print(json.dumps({
        "status": "AWAIT_TRIAL_READBACK" if phase == "before" else "AWAIT_POST_USAGE_READBACK",
        "slot": slot, "estimated_upper_usd": upper,
        "check": "trial active; Stop usage after trial; no paid mode/card charge; usage and balance",
        "continue_marker": marker,
    }), flush=True)
    try:
        if input().strip() != marker:
            return False
        path = EVIDENCE / f"trial_{slot:02d}_{phase}_readback.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        observed = dt.datetime.fromisoformat(data["observed_utc"].replace("Z", "+00:00"))
        age = dt.datetime.now(dt.timezone.utc) - observed
        return (
            data.get("phase") == phase
            and data.get("slot") == slot
            and data.get("trial_active") is True
            and data.get("stop_usage_after_trial") is True
            and data.get("paid_mode_observed") is False
            and data.get("card_charge_risk_observed") is False
            and type(data.get("trial_credits_display_usd")) in (int, float)
            and data["trial_credits_display_usd"] >= upper
            and type(data.get("days_left")) is int and data["days_left"] > 0
            and isinstance(data.get("usage_display"), str)
            and 0 <= age.total_seconds() <= 300
        )
    except EOFError:
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return False


def preflight() -> dict:
    # No key is loaded, and no provider network call occurs here.
    return {
        "status": "READY_FOR_OWNER_AUTHORIZATION" if not authorization_valid() else "OWNER_AUTHORIZATION_RECORDED",
        "owner_authorization": authorization_valid(),
        "r9_lab_exists": (R9 / "r9_unseen_lab.py").is_file(),
        "r12_parser_exists": (R9 / "r12_provider_parser.py").is_file(),
        "api_key_present": bool(os.environ.get("NEBIUS_API_KEY")),
        "model": MODEL, "max_requests": MAX_REQUESTS,
        "max_estimated_usd": MAX_ESTIMATED_USD,
        "request_body_bytes_cap": MAX_BODY_BYTES,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "worst_case_estimated_usd": MAX_REQUESTS * (
            (MAX_BODY_BYTES + 512) * INPUT_USD_PER_M + MAX_COMPLETION_TOKENS * OUTPUT_USD_PER_M
        ) / 1_000_000,
        "provider_requests": 0,
    }


def qualifies_multistep(incident: dict) -> bool:
    model_events = [event for event in incident["events"] if event["stage"] == "MODEL_DIAGNOSIS_PLAN"]
    verify_events = [event for event in incident["events"] if event["stage"] == "VERIFY_INDEPENDENT_HTTP"]
    all_real = all(event["data"]["provider"].get("real_nebius_inference") is True and
                   event["data"]["provider"].get("model") == MODEL for event in model_events)
    return (
        incident["outcome"] == "VERIFIED_RECOVERY"
        and len(model_events) >= 2 and all_real
        and len(verify_events) >= 2
        and verify_events[0]["data"]["checkout_http"] == 503
        and verify_events[-1]["data"]["checkout_http"] == 200
        and (model_events[0]["data"]["decision"]["action"], model_events[0]["data"]["decision"]["args"])
        != (model_events[1]["data"]["decision"]["action"], model_events[1]["data"]["decision"]["args"])
    )


def execute() -> int:
    if not authorization_valid():
        raise RuntimeError("R14_OWNER_AUTHORIZATION_MISSING")
    if baseline.MODEL != MODEL or baseline.URL != "https://api.tokenfactory.nebius.com/v1":
        raise RuntimeError("R14_MODEL_OR_ENDPOINT_MISMATCH")
    if FINAL.exists() or (EVIDENCE / "run_started.json").exists():
        raise RuntimeError("R14_EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY")
    key = os.environ.get("NEBIUS_API_KEY", "")
    guardian.guard_real_inference(key, MODEL, baseline.URL)
    if os.environ.get("NEBIUS_ACCOUNT_VERIFIED") != "1" or os.environ.get("NEBIUS_BILLING_BLOCK_CONFIRMED") != "1":
        raise RuntimeError("R14_BILLING_FLAGS_MISSING")
    # A fresh unpredictable isolated case. The provider only receives the
    # observations that run_unseen_incident passes to its callback.
    seed = secrets.randbits(63)
    case = generate_unseen_case(seed, fault="compound_capacity_timeout")
    write_once(EVIDENCE / "run_started.json", {
        "utc": utc(), "seed": seed, "case": case.__dict__, "model": MODEL,
        "owner_authorization_sha256": hashlib.sha256(AUTH.read_bytes()).hexdigest(),
    })
    budget = RequestBudget(EVIDENCE, interactive_readback)

    def provider(observation: dict) -> tuple[dict, dict]:
        audit: dict = {}
        response: dict | None = None
        error: str | None = None
        try:
            decision, response = request_decision(observation, audit, reserve_call=budget.reserve)
            return decision, response
        except Exception as exc:
            error = (type(exc).__name__ + ":" + str(exc).replace(key, "[REDACTED]"))[:150]
            raise
        finally:
            budget.finish(audit, response, error)

    incident = run_unseen_incident(
        provider, case=case, max_attempts=MAX_REQUESTS, strict_progress=True,
        event_sink=lambda event: write_once(EVIDENCE / f"event_{event['seq']:03d}.json", event),
    )
    multi_step_pass = qualifies_multistep(incident)
    record = {
        "status": "REAL_NEMOTRON_MULTI_STEP_PASS" if multi_step_pass else "REAL_RESULT_NO_MULTI_STEP_PASS",
        "utc": utc(), "model": MODEL, "case": case.__dict__, "incident": incident,
        "owner_authorization_sha256": hashlib.sha256(AUTH.read_bytes()).hexdigest(),
        "provider_request_count": len(budget.slots()),
        "reserved_estimated_cost_usd": sum(x["estimated_upper_usd"] for x in budget.slots()),
        "actual_model_cost_usd": sum(
            actual_cost(json.loads(path.read_text(encoding="utf-8"))["audit"].get("usage")) or 0
            for path in sorted(EVIDENCE.glob("attempt_??_response.json"))
        ),
        "multi_step_pass": multi_step_pass,
    }
    write_once(FINAL, record)
    print(json.dumps({
        "status": record["status"], "outcome": incident["outcome"],
        "provider_request_count": record["provider_request_count"],
        "reserved_estimated_cost_usd": record["reserved_estimated_cost_usd"],
        "evidence_path": str(FINAL),
    }), flush=True)
    return 0 if multi_step_pass else 4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(preflight()), flush=True)
        return 0
    try:
        return execute()
    except Exception as exc:
        print(json.dumps({"status": "R14_FAIL_CLOSED", "error_code": type(exc).__name__ + ":" + str(exc)[:120],
                          "provider_request_count": len(list(EVIDENCE.glob("attempt_??_reserved.json")))}), flush=True)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())

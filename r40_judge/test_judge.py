"""R39 candidate acceptance; no provider or credential access."""
from __future__ import annotations

import copy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
import urllib.error
import urllib.request

from judge_runtime import DEV_CASE, contract_preview, run_public_development_case
from judge_server import Handler
from contract import MODEL, build_request, parse_and_gate
from public_integrity import verify_chain
from r12_provider_parser import ProviderParseError


def observation():
    return {"health_http": 200, "checkout_http": 503,
            "metrics": {"checkout_error_rate": .78, "queue_depth": 0,
                        "request_timeout_count": 0, "db_pool_waiters": 22,
                        "upstream_p95_ms": 95, "retry_attempts_per_request": 1,
                        "oldest_queue_item_ms": 20},
            "logs": ["database acquire wait exceeded"],
            "configuration": DEV_CASE["initial"], "available_actions": DEV_CASE["catalog"]}


def plan(value=8):
    return {"hypotheses": ["database acquire contention"],
            "action": "set_db_pool_size", "value": value,
            "reason": "supported by acquire-wait log", "predict_metric": "db_pool_waiters",
            "predict_direction": "decrease", "if_failed": "inspect HTTP and new waiters"}


def envelope(value, finish="stop"):
    return json.dumps({"id": "SYNTHETIC_CONTRACT_TEST_ONLY", "model": MODEL,
                       "usage": {"prompt_tokens": 100, "completion_tokens": 100,
                                 "total_tokens": 200},
                       "choices": [{"finish_reason": finish,
                                    "message": {"content": json.dumps(value)}}]}).encode()


class JudgeTests(unittest.TestCase):
    def test_redacted_receipt_is_complete_and_failure_visible(self):
        public = json.loads((Path(__file__).parent / "evidence" / "public_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(public["summary"]["provider_calls_cumulative"], 278)
        self.assertEqual(public["summary"]["new_case_count"], 104)
        self.assertEqual(len(public["cases"]), 138)
        self.assertEqual(len(public["redacted_provider_receipts_r34_r38"]), 238)
        self.assertEqual([x["slot"] for x in public["redacted_provider_receipts_r34_r38"]], list(range(41, 279)))
        r38 = [x for x in public["cases"] if x["round"] == "R38"]
        self.assertEqual(len(r38), 8)
        self.assertEqual(sum(x["outcome"] == "ABSTAIN_NO_REPAIR" for x in r38), 4)
        self.assertEqual(sum(x["outcome"] == "ROLLED_BACK_EXHAUSTED" for x in r38), 4)
        self.assertFalse(public["private_blind_answers_included"])
        self.assertFalse(public["live_provider_transport_included"])
        for key in ("mechanics", "hidden_required", "response_body_utf8", "Authorization", "api_key"):
            self.assertNotIn('"' + key + '"', json.dumps(public))

    def test_frozen_contract_and_hidden_field_boundary(self):
        preview = contract_preview()
        self.assertEqual(preview["r34_contract_sha256"],
                         "b61e139c26d651801da7365a754d127abf8b0b61129e4a036d9ef916c2258532")
        body, _ = build_request(observation())
        request = json.loads(body)
        self.assertEqual(request["response_format"]["type"], "json_schema")
        self.assertEqual(request["reasoning_effort"], "low")
        self.assertNotIn("hidden_required", request["messages"][1]["content"])
        self.assertEqual(preview["live_calls_exposed_by_this_build"], 0)

    def test_parser_and_safety_gate(self):
        obs = observation()
        decision, meta = parse_and_gate(envelope(plan()), obs, [], {})
        self.assertEqual(decision["action"], "set_db_pool_size")
        self.assertEqual(decision["args"], {"value": 8})
        self.assertEqual(meta["validated_plan"]["chosen"]["value"], 8)
        bad = copy.deepcopy(plan()); bad["value"] = 999
        with self.assertRaises(ProviderParseError):
            parse_and_gate(envelope(bad), obs, [], {})
        bad = copy.deepcopy(plan()); bad["predict_metric"] = "invented_metric"
        with self.assertRaises(ProviderParseError):
            parse_and_gate(envelope(bad), obs, [], {})
        with self.assertRaises(ProviderParseError):
            parse_and_gate(envelope(plan(), "length"), obs, [], {})
        with self.assertRaisesRegex(ValueError, "REPEATED_FAILED_ACTION"):
            parse_and_gate(envelope(plan()), obs,
                           [{"action": "set_db_pool_size", "args": {"value": 8}}], {})

    def test_fresh_offline_http_with_failure_feedback(self):
        result = run_public_development_case()
        self.assertEqual(result["mode"], "OFFLINE_POLICY_FRESH_LOCAL_HTTP")
        self.assertEqual(result["model"], "NOT_RUN")
        incident = result["incident"]
        self.assertEqual(incident["before"]["checkout_http"], 503)
        self.assertEqual(incident["after"]["checkout_http"], 200)
        self.assertEqual(incident["after"]["health_http"], 200)
        self.assertEqual(incident["attempts"], 2)
        self.assertEqual(incident["outcome"], "VERIFIED_RECOVERY")
        self.assertTrue(verify_chain(incident["events"]))
        decisions = [e["data"]["provider"] for e in incident["events"] if e["stage"] == "DECISION"]
        self.assertTrue(all(x["provider"] == "offline_deterministic_development_policy" and
                            x["real_nebius_inference"] is False for x in decisions))
        self.assertEqual([e["data"]["checkout_http"] for e in incident["events"]
                          if e["stage"] == "VERIFY_INDEPENDENT_HTTP"], [503, 200])

    def test_refusal_and_compound_public_scenarios(self):
        refusal = run_public_development_case("D02_PUBLIC_UNREPAIRABLE")["incident"]
        compound = run_public_development_case("D03_PUBLIC_COMPOUND")["incident"]
        self.assertEqual(refusal["outcome"], "ABSTAIN_NO_REPAIR")
        self.assertTrue(refusal["config_restored"])
        self.assertEqual(refusal["after"]["checkout_http"], 503)
        self.assertEqual(compound["outcome"], "VERIFIED_RECOVERY")
        self.assertEqual(compound["after"]["checkout_http"], 200)
        self.assertTrue(verify_chain(refusal["events"]))
        self.assertTrue(verify_chain(compound["events"]))

    def test_http_api_and_live_hard_stop(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            for route in ("/", "/judge.html", "/judge.js", "/evidence/public_receipt.json"):
                with opener.open(base + route, timeout=5) as response:
                    self.assertEqual(response.status, 200)
            with opener.open(base + "/api/judge/status", timeout=5) as response:
                status = json.loads(response.read())
            self.assertEqual(status["live_inference"], "DISABLED_PUBLIC_REPLAY_BUILD")
            with opener.open(base + "/api/judge/contract", timeout=5) as response:
                self.assertEqual(json.loads(response.read())["mode"], "NO_PROVIDER_CALL")
            body = json.dumps({"case_id": "D01_PUBLIC_DEVELOPMENT"}).encode()
            req = urllib.request.Request(base + "/api/judge/run", body,
                                         {"Content-Type": "application/json"}, method="POST")
            with opener.open(req, timeout=10) as response:
                run = json.loads(response.read())
            self.assertEqual(run["incident"]["outcome"], "VERIFIED_RECOVERY")
            req = urllib.request.Request(base + "/api/judge/live", b"{}",
                                         {"Content-Type": "application/json"}, method="POST")
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(req, timeout=5)
            self.assertEqual(raised.exception.code, 423)
            self.assertEqual(json.loads(raised.exception.read())["provider_calls_sent"], 0)
            bad = urllib.request.Request(base + "/api/judge/run", b'{"case_id":"B01"}',
                                         {"Content-Type": "application/json"}, method="POST")
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(bad, timeout=5)
            self.assertEqual(raised.exception.code, 400)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

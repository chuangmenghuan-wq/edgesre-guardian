"""Offline parser regressions; all constructed responses are synthetic."""
import json
import unittest
from pathlib import Path

from r12_provider_parser import ProviderParseError, parse_nebius_response


MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
DECISION = {"diagnosis": "capacity", "action": "set_worker_limit", "args": {"value": 8}, "reason": "queue grew"}
R11_FAILURE = Path(__file__).resolve().parent / "fixtures" / "R11_SECOND_REQUEST_FAILURE.json"
R11_THIRD = R11_FAILURE.with_name("R11_REAL_AUTONOMOUS_REPAIR.json")


def envelope(*, content=None, reasoning=None, calls=None, finish="stop", usage=None):
    message = {"content": content, "reasoning_content": reasoning, "tool_calls": calls}
    return json.dumps({"id": "synthetic-id", "model": MODEL, "choices": [{"finish_reason": finish, "message": message}],
                       "usage": usage if usage is not None else {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}).encode()


class ParserTests(unittest.TestCase):
    def parse(self, raw):
        audit = {}
        decision, provider = parse_nebius_response(raw, MODEL, audit)
        self.assertEqual(provider["model"], MODEL)
        self.assertEqual(audit["response_id"], "synthetic-id")
        return decision, audit

    def test_content_and_reasoning_separated(self):
        decision, audit = self.parse(envelope(content="\n```json\n" + json.dumps(DECISION) + "\n```",
                                              reasoning="Private reasoning is not a repair command."))
        self.assertEqual(decision, DECISION)
        self.assertEqual(audit["decision_source"], "message.content")
        self.assertTrue(audit["reasoning_content_present"])
        self.assertEqual(audit["usage"]["completion_tokens"], 20)

    def test_only_named_tool_call_can_supply_final_decision(self):
        call = [{"type": "function", "function": {"name": "propose_repair", "arguments": json.dumps(DECISION)}}]
        decision, audit = self.parse(envelope(calls=call, finish="tool_calls"))
        self.assertEqual(decision, DECISION)
        self.assertEqual(audit["decision_source"], "tool_calls.propose_repair")
        call[0]["function"]["name"] = "run_shell"
        with self.assertRaisesRegex(ProviderParseError, "TOOL_CALL_UNSUPPORTED"):
            self.parse(envelope(calls=call, finish="tool_calls"))
        call[0]["function"]["name"] = "propose_repair"
        with self.assertRaisesRegex(ProviderParseError, "TOOL_FINISH_MISMATCH"):
            self.parse(envelope(calls=call, finish="stop"))

    def test_reasoning_alone_is_not_an_executable_decision(self):
        with self.assertRaisesRegex(ProviderParseError, "NO_FINAL_DECISION"):
            self.parse(envelope(reasoning=json.dumps(DECISION)))

    def test_truncation_and_malformed_json_fail_closed(self):
        with self.assertRaisesRegex(ProviderParseError, "TRUNCATED_MODEL_OUTPUT"):
            self.parse(envelope(content=json.dumps(DECISION), finish="length"))
        with self.assertRaisesRegex(ProviderParseError, "DECISION_JSON_INVALID"):
            self.parse(envelope(content='{"action":'))
        with self.assertRaisesRegex(ProviderParseError, "RESPONSE_JSON_INVALID"):
            self.parse(b'{"choices":')

    def test_usage_and_structure_are_recorded_before_decision_failure(self):
        audit = {}
        with self.assertRaisesRegex(ProviderParseError, "NO_FINAL_DECISION"):
            parse_nebius_response(envelope(reasoning="considered a candidate"), MODEL, audit)
        self.assertEqual(audit["finish_reason"], "stop")
        self.assertEqual(audit["choices_count"], 1)
        self.assertEqual(audit["usage"]["total_tokens"], 30)
        self.assertEqual(audit["parse_error"], "NO_FINAL_DECISION")
        with self.assertRaisesRegex(ProviderParseError, "PROVIDER_USAGE_INVALID"):
            self.parse(envelope(content=json.dumps(DECISION), usage={"total_tokens": 30}))

    def test_r11_second_response_body_is_missing(self):
        record = json.loads(R11_FAILURE.read_text(encoding="utf-8"))
        audit = record["provider_audit"]
        self.assertEqual(audit["http_status"], 200)
        self.assertRegex(audit["response_sha256"], r"^[0-9a-f]{64}$")
        for field in ("response_body", "response_body_nonsecret", "content", "reasoning_content",
                      "tool_calls", "finish_reason", "usage", "choices", "response_id"):
            self.assertNotIn(field, audit)

    def test_r11_third_saved_final_content_reparses(self):
        # The original full HTTP body was not saved; this reconstructs only
        # the envelope from fields in the real provider receipt.
        saved = json.loads(R11_THIRD.read_text(encoding="utf-8"))["provider_audit"]
        reconstructed = json.dumps({"id": saved["response_id"], "model": saved["response_model"],
                                    "usage": saved["usage"], "choices": [{"finish_reason": saved["finish_reason"],
                                    "message": {"content": saved["content"]}}]}).encode()
        audit = {}
        decision, provider = parse_nebius_response(reconstructed, MODEL, audit)
        self.assertEqual(decision["action"], "set_worker_limit")
        self.assertEqual(decision["args"]["value"], 4)
        self.assertEqual(provider["id"], saved["response_id"])


if __name__ == "__main__":
    unittest.main()

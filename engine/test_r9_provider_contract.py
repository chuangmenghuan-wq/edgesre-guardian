"""Offline HTTP contract checks. The response is synthetic, never Nebius evidence."""
import json
import os
import unittest
from unittest.mock import patch

import r9_live_probe_once as probe


class _Reply:
    status = 200
    headers = {"x-request-id": "synthetic-contract-request"}

    def __init__(self, model):
        self.body = json.dumps({
            "id": "synthetic-contract-id",
            "model": model,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "diagnosis": "capacity issue", "action": "abstain", "args": {}, "reason": "uncertain"
            })}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
        }).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.body


class ProviderContractTests(unittest.TestCase):
    def test_request_shape_and_response_identity(self):
        observed = []

        def fake_urlopen(request, timeout):
            self.assertEqual(request.full_url, "https://api.tokenfactory.nebius.com/v1/chat/completions")
            self.assertEqual(timeout, 90)
            body = json.loads(request.data)
            self.assertEqual(body["model"], probe.baseline.MODEL)
            self.assertIn("metrics", body["messages"][1]["content"])
            observed.append(1)
            return _Reply(probe.baseline.MODEL)

        with patch.dict(os.environ, {"NEBIUS_API_KEY": "synthetic-test-value"}), \
                patch.object(probe.guardian, "guard_real_inference"), \
                patch.object(probe.guardian, "reserve_one_live_call"), \
                patch.object(probe.urllib.request, "urlopen", side_effect=fake_urlopen):
            decision, provider = probe.request_decision({"metrics": {"queue_depth": 2}}, {})
        self.assertEqual(observed, [1])
        self.assertEqual(decision["action"], "abstain")
        self.assertEqual(provider["model"], probe.baseline.MODEL)

    def test_model_mismatch_fails_closed(self):
        with patch.dict(os.environ, {"NEBIUS_API_KEY": "synthetic-test-value"}), \
                patch.object(probe.guardian, "guard_real_inference"), \
                patch.object(probe.guardian, "reserve_one_live_call"), \
                patch.object(probe.urllib.request, "urlopen", return_value=_Reply("other/model")):
            with self.assertRaisesRegex(ValueError, "PROVIDER_MODEL_MISMATCH"):
                probe.request_decision({"metrics": {}}, {})


if __name__ == "__main__":
    unittest.main()

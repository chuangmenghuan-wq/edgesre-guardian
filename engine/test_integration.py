"""Controlled local acceptance for the one-call bridge; no provider network access."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import guardian
import http_lab
import live_probe_once as live


class LiveBridgeTests(unittest.TestCase):
    def test_model_receipt_drives_same_loopback_service_once(self):
        calls = []

        def fake_live_model(observation, api_key, model, url, audit):
            self.assertEqual(503, observation['real_http']['business_http'])
            self.assertEqual('cache.bad.local', observation['configuration']['cache_endpoint'])
            self.assertEqual('fake-private-key-only', api_key)
            calls.append(observation)
            audit['http_status'] = 200
            audit['response_body_sha256'] = 'f' * 64
            audit['redacted_provider_body'] = {'id': 'controlled-test-id'}
            return ({'action': 'set_cache_endpoint', 'args': {'endpoint': 'cache.prod.local'},
                     'reason': 'Observed configuration drift'},
                    {'provider': 'nebius_token_factory', 'id': 'controlled-test-id',
                     'model': live.MODEL, 'usage': {'total_tokens': 10}})

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            flags = {name: '1' for name in live.FLAGS}
            flags['NEBIUS_API_KEY'] = 'fake-private-key-only'
            with patch.object(live, 'R4', Path(__file__).resolve().parent), \
                 patch.object(live, 'ROOT', base), \
                 patch.object(live, 'LOCK', base / 'LIVE_CALL_ATTEMPT_STARTED.json'), \
                 patch.object(live, 'RECEIPT', base / 'LIVE_MODEL_RECEIPT.json'), \
                 patch.object(live, 'FAILURE', base / 'LIVE_MODEL_FAILURE.json'), \
                 patch.object(guardian, 'live_model', side_effect=fake_live_model), \
                 patch.dict(os.environ, flags), \
                 patch.object(sys, 'argv', ['live_probe_once.py', '--execute']), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, live.main())
                self.assertEqual(1, len(calls))
                receipt = json.loads(live.RECEIPT.read_text(encoding='utf-8'))
                self.assertEqual('REAL_NEBIUS_RESPONSE', receipt['status'])
                self.assertTrue(receipt['independent_repair_verified'])
                self.assertEqual(200, receipt['http_receipt']['after']['business_http'])
                self.assertEqual(1, receipt['http_receipt']['real_nebius_calls'])
                self.assertTrue(live.LOCK.exists())
                self.assertEqual(3, live.main())
                self.assertEqual(1, len(calls))

    def test_controlled_callback_failure_rolls_back(self):
        observed = []

        def choose(observation):
            observed.append(observation['real_http'])
            return ({'action': 'restart_service', 'args': {}, 'reason': 'try restart'},
                    {'provider': 'controlled_test', 'eligible_nebius_inference': False})

        result = http_lab.run_http_incident('config_drift', decision_provider=choose)
        self.assertEqual(1, len(observed))
        self.assertEqual('ROLLED_BACK_NOT_RECOVERED', result['outcome'])
        self.assertTrue(result['config_rolled_back'])
        self.assertEqual(503, result['after']['business_http'])
        self.assertEqual(0, result['real_nebius_calls'])


if __name__ == '__main__':
    unittest.main()

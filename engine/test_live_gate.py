import unittest,os,json
from unittest.mock import patch
import guardian

class FakeResponse:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return json.dumps({'id':'MOCK-NOT-REAL','model':guardian.MODEL,'choices':[{'message':{'content':'{"action":"set_cache_endpoint","args":{"endpoint":"cache.prod.local"}}'}}]}).encode()

class LiveGateTests(unittest.TestCase):
    def setUp(self):
        guardian._live_call_count=0
        self.obs=guardian.make_observation(guardian.initial_state('config_drift'))
    def test_requires_key(self):
        with patch.dict(os.environ,{'NEBIUS_LIVE_ENABLED':'1','NEBIUS_FREE_CREDITS_VERIFIED':'1'}):
            with self.assertRaisesRegex(RuntimeError,'API_KEY_NOT_CONFIGURED'):guardian.live_model(self.obs,'')
    def test_requires_explicit_live(self):
        with patch.dict(os.environ,{'NEBIUS_LIVE_ENABLED':'0','NEBIUS_FREE_CREDITS_VERIFIED':'1'}):
            with self.assertRaisesRegex(RuntimeError,'LIVE_GATE_DISABLED'):guardian.live_model(self.obs,'not-real')
    def test_requires_credits(self):
        with patch.dict(os.environ,{'NEBIUS_LIVE_ENABLED':'1','NEBIUS_FREE_CREDITS_VERIFIED':'0'}):
            with self.assertRaisesRegex(RuntimeError,'FREE_CREDIT_BALANCE_NOT_VERIFIED'):guardian.live_model(self.obs,'not-real')
    def test_off_domain_blocked(self):
        with patch.dict(os.environ,{'NEBIUS_LIVE_ENABLED':'1','NEBIUS_FREE_CREDITS_VERIFIED':'1'}):
            with self.assertRaisesRegex(RuntimeError,'UNAPPROVED_NEBIUS_ENDPOINT'):guardian.live_model(self.obs,'not-real',url='https://example.com/v1')
    def test_nvidia_required(self):
        with patch.dict(os.environ,{'NEBIUS_LIVE_ENABLED':'1','NEBIUS_FREE_CREDITS_VERIFIED':'1'}):
            with self.assertRaisesRegex(RuntimeError,'NVIDIA_MODEL_REQUIRED'):guardian.live_model(self.obs,'not-real',model='foo/bar')
    def test_mock_protocol_and_one_call_cap(self):
        with patch.dict(os.environ,{'NEBIUS_LIVE_ENABLED':'1','NEBIUS_FREE_CREDITS_VERIFIED':'1'}):
            with patch('guardian.urllib.request.urlopen',return_value=FakeResponse()) as u:
                decision,receipt=guardian.live_model(self.obs,'not-real')
                self.assertEqual('set_cache_endpoint',decision['action'])
                self.assertEqual('MOCK-NOT-REAL',receipt['id'])
                self.assertIn('tokenfactory.nebius.com',u.call_args.args[0].full_url)
                with self.assertRaisesRegex(RuntimeError,'NEBIUS_LIVE_CALL_LIMIT_REACHED'):guardian.live_model(self.obs,'not-real')
                self.assertEqual(1,u.call_count)

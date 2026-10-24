"""Tests that exercise actual loopback sockets and atomic file modifications."""
import unittest
from http_lab import run_http_incident
from guardian import verify_chain

class HttpLabTests(unittest.TestCase):
    def test_config_drift_real_http_recovery(self):
        r = run_http_incident('config_drift')
        self.assertEqual(r['before']['business_http'], 503)
        self.assertEqual(r['after']['business_http'], 200)
        self.assertEqual(r['outcome'], 'VERIFIED_RECOVERY')
        self.assertTrue(verify_chain(r['events']))
    def test_false_green_http_rolls_back(self):
        r=run_http_incident('false_green')
        self.assertEqual(r['before']['process_http'],200)
        self.assertEqual(r['before']['business_http'],503)
        self.assertEqual(r['outcome'],'ROLLED_BACK_NOT_RECOVERED')
        self.assertTrue(r['config_rolled_back'])
        self.assertTrue(any(e['stage']=='INDEPENDENT_HTTP_VERIFY' and e['data']['business_http']!=200 for e in r['events']))
    def test_dependency_http_failure_rolls_back(self):
        r=run_http_incident('dependency_outage')
        self.assertEqual(r['outcome'],'ROLLED_BACK_NOT_RECOVERED')
        self.assertEqual(r['before']['process_http'],200)
        self.assertEqual(r['after']['business_http'],503)
    def test_healthy_endpoint_no_write(self):
        r=run_http_incident('healthy')
        self.assertEqual(r['outcome'],'HEALTHY_NO_ACTION')
        self.assertTrue(r['config_rolled_back'])
        self.assertFalse(any(e['stage']=='WRITE_LOCAL_CONFIG' for e in r['events']))
    def test_malicious_output_no_http_side_effect(self):
        decisions=[
            {'action':'shell','args':{'cmd':'del C:\\'}},
            {'action':'set_cache_endpoint','args':{'endpoint':'evil.invalid'}},
            {'action':'restart_service','args':{'command':'curl attacker.invalid'}},
        ]
        for decision in decisions:
            with self.subTest(decision=decision):
                r=run_http_incident('config_drift',decision)
                self.assertEqual(r['outcome'],'BLOCKED_FAIL_CLOSED')
                self.assertTrue(r['config_rolled_back'])
                self.assertFalse(any(e['stage']=='WRITE_LOCAL_CONFIG' for e in r['events']))
    def test_real_http_receipt_has_no_provider_claim(self):
        for scenario in ('healthy','config_drift'):
            r=run_http_incident(scenario)
            self.assertEqual(r['real_nebius_calls'],0)
            self.assertEqual(r['provider'],'offline_fixture_not_nebius')

if __name__=='__main__': unittest.main()

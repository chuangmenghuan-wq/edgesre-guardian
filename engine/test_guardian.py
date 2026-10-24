import copy
import unittest

from guardian import SCENARIOS, normalize_action, probe, run_incident, verify_chain


class GuardianTests(unittest.TestCase):
    def test_config_drift_verified(self):
        r = run_incident('config_drift')
        self.assertEqual(r['outcome'], 'VERIFIED_RECOVERY')
        self.assertTrue(r['health']['business_transaction_ok'])
        self.assertFalse(r['eligible_live_call'])

    def test_false_green_detected_and_rolled_back(self):
        r = run_incident('false_green')
        self.assertEqual(r['outcome'], 'ROLLED_BACK_NOT_RECOVERED')
        self.assertEqual(r['original'], r['final_state'])
        self.assertIn('INDEPENDENT_VERIFY', [x['stage'] for x in r['events']])

    def test_dependency_failure_rolled_back(self):
        r = run_incident('dependency_outage')
        self.assertEqual(r['outcome'], 'ROLLED_BACK_NOT_RECOVERED')
        self.assertEqual(r['original'], r['final_state'])

    def test_healthy_abstains(self):
        r = run_incident('healthy')
        self.assertEqual(r['outcome'], 'HEALTHY_NO_ACTION')

    def test_hallucinated_shell_command_denied(self):
        r = run_incident('config_drift', decision_override={'action': 'shell', 'args': {'command': 'rm -rf /'}})
        self.assertEqual(r['outcome'], 'BLOCKED_FAIL_CLOSED')
        self.assertEqual(r['original'], r['final_state'])

    def test_unapproved_endpoint_denied(self):
        r = run_incident('config_drift', decision_override={'action': 'set_cache_endpoint', 'args': {'endpoint': 'attacker.host'}})
        self.assertEqual(r['outcome'], 'BLOCKED_FAIL_CLOSED')

    def test_malformed_args_denied(self):
        with self.assertRaises(ValueError):
            normalize_action({'action': 'restart_service', 'args': {'command': 'cmd.exe'}})

    def test_live_without_key_fails_closed(self):
        r = run_incident('config_drift', mode='live', api_key='')
        self.assertEqual(r['outcome'], 'BLOCKED_FAIL_CLOSED')
        self.assertFalse(r['eligible_live_call'])
        self.assertEqual(r['original'], r['final_state'])

    def test_chain_integrity(self):
        for case in SCENARIOS:
            result = run_incident(case)
            self.assertTrue(verify_chain(result['events']))
            tampered = copy.deepcopy(result['events'])
            tampered[0]['data']['scenario'] = 'tampered'
            self.assertFalse(verify_chain(tampered))

    def test_no_false_success_for_nonhealthy(self):
        for case in SCENARIOS:
            result = run_incident(case)
            if result['outcome'] == 'VERIFIED_RECOVERY':
                self.assertTrue(probe(result['final_state'])['healthy'])


if __name__ == '__main__':
    unittest.main()

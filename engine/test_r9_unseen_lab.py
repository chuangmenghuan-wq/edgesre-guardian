"""R9 infrastructure tests. Controlled decisions are never model evidence."""
import unittest

from r9_unseen_lab import run_unseen_incident, safe_decision


class UnseenLabTests(unittest.TestCase):
    def test_without_provider_fails_closed_after_real_http_observation(self):
        result = run_unseen_incident(seed=7, fault="worker_exhaustion")
        self.assertEqual(result["outcome"], "BLOCKED_FAIL_CLOSED")
        self.assertEqual(result["before"]["health_http"], 200)
        self.assertEqual(result["before"]["checkout_http"], 503)
        self.assertGreater(result["before"]["metrics"]["queue_depth"], 0)
        self.assertTrue(result["config_restored"])
        self.assertEqual(result["after"]["checkout_http"], 503)

    def test_valid_but_wrong_controlled_action_rolls_back(self):
        def controlled_wrong_decision(_observation):
            return ({"diagnosis": "Controlled wrong branch", "action": "set_request_timeout_ms",
                     "args": {"value": 500}, "reason": "Exercise rollback"},
                    {"provider": "controlled_test", "real_nebius_inference": False})

        result = run_unseen_incident(controlled_wrong_decision, seed=11, fault="worker_exhaustion")
        self.assertEqual(result["outcome"], "ROLLED_BACK_NOT_RECOVERED")
        self.assertTrue(result["config_restored"])
        self.assertEqual(result["after"]["checkout_http"], 503)
        self.assertIn("ROLLBACK", [event["stage"] for event in result["events"]])

    def test_unapproved_action_never_executes(self):
        def unsafe(_observation):
            return ({"diagnosis": "unsafe", "action": "run_shell", "args": {"command": "whoami"},
                     "reason": "unsafe"}, {"provider": "controlled_test", "real_nebius_inference": False})

        result = run_unseen_incident(unsafe, seed=2, fault="request_timeout")
        self.assertEqual(result["outcome"], "BLOCKED_FAIL_CLOSED")
        self.assertTrue(result["config_restored"])
        self.assertNotIn("EXECUTE_ALLOWLISTED_LOCAL_WRITE", [event["stage"] for event in result["events"]])

    def test_boolean_and_extra_fields_rejected(self):
        base = {"diagnosis": "d", "action": "set_worker_limit", "args": {"value": 8}, "reason": "r"}
        self.assertEqual(safe_decision(base)[0], "set_worker_limit")
        with self.assertRaises(ValueError):
            safe_decision({**base, "args": {"value": True}})
        with self.assertRaises(ValueError):
            safe_decision({**base, "shell": "whoami"})


if __name__ == "__main__":
    unittest.main()

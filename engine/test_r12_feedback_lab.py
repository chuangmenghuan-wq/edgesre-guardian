"""Controlled offline loopback tests; policies here are not Nemotron decisions."""
import json
import unittest

from guardian import verify_chain
from r9_unseen_lab import generate_unseen_case, run_unseen_incident


def controlled_increment(observation):
    assert "hidden_required" not in json.dumps(observation)
    worker_fault = observation["metrics"]["queue_depth"] > 0
    action = "set_worker_limit" if worker_fault else "set_request_timeout_ms"
    field = "worker_limit" if worker_fault else "request_timeout_ms"
    choices = [value for value in observation["available_actions"][action]
               if value > observation["configuration"][field]]
    if not choices:
        decision = {"diagnosis": "candidate set exhausted", "action": "abstain", "args": {},
                    "reason": "No remaining listed value"}
    else:
        prior = observation.get("repair_feedback", {}).get("previous_attempts", [])
        decision = {"diagnosis": "capacity remains insufficient", "action": action,
                    "args": {"value": min(choices)},
                    "reason": "Prior HTTP verification remained 503; reassess capacity" if prior else "Initial telemetry indicates capacity pressure"}
    return decision, {"provider": "CONTROLLED_OFFLINE_POLICY", "real_nebius_inference": False}


class FeedbackLoopTests(unittest.TestCase):
    def test_new_cases_vary_and_recover_through_feedback(self):
        cases = [generate_unseen_case(seed, fault="worker_exhaustion" if seed % 2 == 0 else "request_timeout")
                 for seed in (0, 1, 3, 4, 5, 6)]
        self.assertGreater(len({case.hidden_required for case in cases}), 3)
        self.assertGreater(len({tuple(case.available_actions["set_worker_limit"]) for case in cases}), 2)
        self.assertGreater(len({tuple(case.initial_config.values()) for case in cases}), 2)
        for case in cases:
            seen = []

            def provider(observation):
                seen.append(observation)
                return controlled_increment(observation)

            result = run_unseen_incident(provider, case=case, max_attempts=5)
            self.assertEqual(result["outcome"], "VERIFIED_RECOVERY")
            self.assertEqual(result["after"]["checkout_http"], 200)
            self.assertTrue(verify_chain(result["events"]))
            self.assertEqual(result["attempts"], len(seen))
            self.assertLessEqual(result["attempts"], 5)
            self.assertTrue(all("hidden_required" not in obs and "hidden_threshold" not in obs for obs in seen))
            for prior, current in zip(seen, seen[1:]):
                feedback = current["repair_feedback"]["previous_attempts"][-1]
                self.assertEqual(feedback["http"]["checkout"], 503)
                self.assertEqual(feedback["configuration"], current["configuration"])
                self.assertIn(feedback["args"]["value"], prior["available_actions"][feedback["action"]])

    def test_all_candidates_fail_then_rollback(self):
        case = generate_unseen_case(41, fault="request_timeout", unrepairable=True)
        count = len(case.available_actions["set_request_timeout_ms"])
        result = run_unseen_incident(controlled_increment, case=case, max_attempts=count)
        self.assertEqual(result["outcome"], "ROLLED_BACK_EXHAUSTED")
        self.assertEqual(result["attempts"], count)
        self.assertEqual(len([e for e in result["events"] if e["stage"] == "VERIFY_FAIL"]), count)
        self.assertEqual(len([e for e in result["events"] if e["stage"] == "ROLLBACK"]), 1)
        self.assertTrue(result["config_restored"])
        self.assertEqual(result["after"]["configuration"], case.initial_config)
        self.assertEqual(result["after"]["checkout_http"], 503)

    def test_unsafe_second_proposal_stops_and_rolls_back(self):
        case = generate_unseen_case(0, fault="worker_exhaustion")
        def provider(observation):
            if "repair_feedback" not in observation:
                return controlled_increment(observation)
            return ({"diagnosis": "unsafe", "action": "run_shell", "args": {"command": "whoami"},
                     "reason": "invalid"}, {"provider": "CONTROLLED_OFFLINE_POLICY", "real_nebius_inference": False})
        result = run_unseen_incident(provider, case=case, max_attempts=4)
        self.assertEqual(result["outcome"], "BLOCKED_FAIL_CLOSED")
        self.assertEqual(result["attempts"], 2)
        self.assertTrue(result["config_restored"])
        self.assertEqual(len([e for e in result["events"] if e["stage"] == "EXECUTE_ALLOWLISTED_LOCAL_WRITE"]), 1)
        self.assertEqual(len([e for e in result["events"] if e["stage"] == "FAIL_CLOSED"]), 1)

    def test_no_provider_never_calls_external_model(self):
        result = run_unseen_incident(case=generate_unseen_case(17), max_attempts=3)
        self.assertEqual(result["outcome"], "BLOCKED_FAIL_CLOSED")
        self.assertEqual(result["attempts"], 0)
        self.assertTrue(result["config_restored"])

    def test_dynamic_catalog_rejects_unlisted_value(self):
        case = generate_unseen_case(0, fault="worker_exhaustion")
        invalid = max(case.available_actions["set_worker_limit"]) + 1
        def provider(_observation):
            return ({"diagnosis": "capacity", "action": "set_worker_limit",
                     "args": {"value": invalid}, "reason": "unlisted value"},
                    {"provider": "CONTROLLED_OFFLINE_POLICY", "real_nebius_inference": False})
        result = run_unseen_incident(provider, case=case, max_attempts=3)
        self.assertEqual(result["outcome"], "BLOCKED_FAIL_CLOSED")
        self.assertTrue(result["config_restored"])
        self.assertFalse(any(e["stage"] == "EXECUTE_ALLOWLISTED_LOCAL_WRITE" for e in result["events"]))

    def test_repeated_failed_candidate_stops_without_second_write(self):
        case = generate_unseen_case(0, fault="worker_exhaustion")
        def provider(observation):
            return ({"diagnosis": "capacity", "action": "set_worker_limit", "args": {"value": 4},
                     "reason": "repeat" if "repair_feedback" in observation else "first attempt"},
                    {"provider": "CONTROLLED_OFFLINE_POLICY", "real_nebius_inference": False})
        result = run_unseen_incident(provider, case=case, max_attempts=3)
        self.assertEqual(result["outcome"], "BLOCKED_FAIL_CLOSED")
        self.assertTrue(result["config_restored"])
        self.assertEqual(len([e for e in result["events"] if e["stage"] == "EXECUTE_ALLOWLISTED_LOCAL_WRITE"]), 1)


if __name__ == "__main__":
    unittest.main()

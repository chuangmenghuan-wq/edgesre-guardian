"""Fresh isolated cases exercise the inherited executor, not model intelligence."""
import json
import unittest

from guardian import verify_chain
from r9_unseen_lab import generate_unseen_case, run_unseen_incident


SEEDS = (107, 233, 991, 1327)


def offline_observation_policy(obs):
    assert "hidden_required" not in json.dumps(obs)
    if obs["metrics"]["queue_depth"]:
        action, field = "set_worker_limit", "worker_limit"
    elif obs["metrics"]["request_timeout_count"]:
        action, field = "set_request_timeout_ms", "request_timeout_ms"
    else:
        action, field = "abstain", None
    values = [] if field is None else [v for v in obs["available_actions"][action]
                                       if v > obs["configuration"][field]]
    if values:
        decision = {"diagnosis": "offline telemetry rule", "action": action,
                    "args": {"value": max(values)}, "reason": "Latest observed metric remains abnormal"}
    else:
        decision = {"diagnosis": "no safe candidate", "action": "abstain",
                    "args": {}, "reason": "No listed value remains above the current setting"}
    return decision, {"provider": "CONTROLLED_OFFLINE_POLICY", "real_nebius_inference": False}


class NewCases(unittest.TestCase):
    def test_unseen_worker_timeout_compound_and_unrepairable(self):
        specs = ((SEEDS[0], "worker_exhaustion", False),
                 (SEEDS[1], "request_timeout", False),
                 (SEEDS[2], "compound_capacity_timeout", False),
                 (SEEDS[3], "compound_capacity_timeout", True))
        cases = [generate_unseen_case(seed, fault=fault, unrepairable=unrepairable)
                 for seed, fault, unrepairable in specs]
        self.assertGreater(len({json.dumps(case.hidden_required, sort_keys=True) for case in cases}), 2)
        self.assertGreater(len({json.dumps(case.available_actions, sort_keys=True) for case in cases}), 2)
        self.assertGreater(len({json.dumps(case.initial_config, sort_keys=True) for case in cases}), 2)
        for case, (_, _, unrepairable) in zip(cases, specs):
            seen = []
            def provider(obs):
                seen.append(obs)
                return offline_observation_policy(obs)
            result = run_unseen_incident(provider, case=case, max_attempts=4, strict_progress=True)
            self.assertTrue(verify_chain(result["events"]))
            self.assertTrue(all("hidden_required" not in obs and "hidden_threshold" not in obs for obs in seen))
            if unrepairable:
                self.assertTrue(result["config_restored"])
                self.assertEqual(result["after"]["configuration"], case.initial_config)
                self.assertIn(result["outcome"], {"ABSTAIN_NO_REPAIR", "ROLLED_BACK_EXHAUSTED"})
            else:
                self.assertEqual(result["outcome"], "VERIFIED_RECOVERY")
                self.assertEqual(result["after"]["checkout_http"], 200)


if __name__ == "__main__":
    unittest.main()

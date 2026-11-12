import copy
import json
import unittest

from examples.dios_nous.unified.recovery import RecoveryAdvisor


class RecoveryTests(unittest.TestCase):
    def test_initial_unknown_and_out_of_band_stop(self):
        advisor = RecoveryAdvisor()
        self.assertEqual(advisor.read()["advice"], "REQUEST_OBSERVATION")
        self.assertEqual(advisor.request_stop()["state"], "HALTED")
        recovered = RecoveryAdvisor.restore(advisor.checkpoint())
        self.assertEqual(recovered.step(tick=0, stress=0, fatigue=0, energy=1000)["state"], "HALTED")

    def test_hysteresis_and_cold_restore(self):
        advisor = RecoveryAdvisor()
        states = []
        for tick, inputs in enumerate(((900, 800, 100), (200, 200, 800), (500, 500, 500),
                                      (200, 200, 800), (200, 200, 800))):
            result = advisor.step(tick=tick, stress=inputs[0], fatigue=inputs[1], energy=inputs[2])
            states.append(result["state"])
            advisor = RecoveryAdvisor.restore(json.loads(json.dumps(advisor.checkpoint())))
        self.assertEqual(states, ["PAUSED", "RECOVERING", "PAUSED", "RECOVERING", "ACTIVE"])

    def test_stop_survives_unknown_and_healthy_samples(self):
        advisor = RecoveryAdvisor()
        advisor.step(tick=1, stress=None, fatigue=None, energy=None, stop=True)
        advisor = RecoveryAdvisor.restore(advisor.checkpoint())
        for i in range(2, 6):
            result = advisor.step(tick=i, stress=0, fatigue=0, energy=1000)
            self.assertEqual(result["state"], "HALTED")
            self.assertFalse(result["execution_permitted"])

    def test_invalid_inputs_never_mutate(self):
        advisor = RecoveryAdvisor()
        advisor.step(tick=3, stress=500, fatigue=500, energy=500)
        prior = advisor.checkpoint()
        for update in ({"tick": 2}, {"tick": 3, "stress": 100}, {"stress": True},
                       {"energy": float("nan")}, {"fatigue": -1}, {"stop": 1}):
            data = dict(tick=4, stress=500, fatigue=500, energy=500)
            data.update(update)
            with self.assertRaises(ValueError):
                advisor.step(**data)
            self.assertEqual(prior, advisor.checkpoint())

    def test_missing_data_and_duplicate_are_not_recovery(self):
        advisor = RecoveryAdvisor()
        advisor.step(tick=1, stress=None, fatigue=0, energy=1000)
        first = advisor.step(tick=2, stress=0, fatigue=0, energy=1000)
        duplicate = advisor.step(tick=2, stress=0, fatigue=0, energy=1000)
        self.assertEqual(first, duplicate)
        self.assertEqual(first["state"], "RECOVERING")
        self.assertEqual(advisor.read(), first)

    def test_checkpoint_mutation_and_private_fields_rejected(self):
        advisor = RecoveryAdvisor()
        for key, value in (("password", "private-canary"), ("state", "ACTIVE"),
                           ("safe_streak", True), ("last_input", {"prompt": "private-canary"})):
            checkpoint = copy.deepcopy(advisor.checkpoint())
            checkpoint[key] = value
            with self.assertRaises(ValueError):
                RecoveryAdvisor.restore(checkpoint)


if __name__ == "__main__":
    unittest.main()

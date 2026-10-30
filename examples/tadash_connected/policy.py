"""pymdp POMDP for three body requests, conditioned on measured work reserve."""
import jax.numpy as jnp
import numpy as np
from pymdp.agent import Agent

ACTIONS = ("walk", "rest", "observe")
CUES = ("ready", "tired", "unclear")


class EffortPolicy:
    """Six hidden states: two reserve levels crossed with the last action."""

    def __init__(self):
        cue = np.empty((3, 6))
        outcome = np.full((4, 6), .001)
        transition = np.zeros((6, 6, 3))
        # Rest can recover reserve; work can consume it. The observation action
        # provides a more informative signal. All probabilities are authored.
        readiness = ((.92, .03), (.99, .38), (.99, .04))
        for level in range(2):
            for last_action in range(3):
                state = 3 * level + last_action
                reliable = last_action == 2
                row = np.array([.96, .02, .02] if reliable else [.71, .09, .20])
                cue[:, state] = row if level == 0 else row[[1, 0, 2]]
                reward_symbol = (2 + level) if last_action == 0 else last_action - 1
                outcome[reward_symbol, state] = .997
                for action, rates in enumerate(readiness):
                    transition[action, state, action] = rates[level]
                    transition[3 + action, state, action] = 1. - rates[level]
        prior = np.array([0., 0., .5, 0., 0., .5])
        self.agent = Agent(
            A=[jnp.asarray(cue), jnp.asarray(outcome)],
            B=[jnp.asarray(transition)],
            C=[jnp.zeros(3), jnp.array([.24, 0., 2.6, -4.8])],
            D=[jnp.asarray(prior)], batch_size=1, policy_len=1,
            action_selection="deterministic", use_states_info_gain=True, gamma=4.,
        )
        self.prior = self.agent.D
        self.last_outcome = 1  # The native fixture starts after an observation.
        self.posterior = None

    def decide(self, native, muscle_fatigue, *, missing=False):
        native_limited = (native["fatigue"] >= .65 or
                    native["energy"] < .30 or native["pain"] >= .35 or native["balance"] < .50)
        if native_limited:
            cue = 1
        elif missing or not np.isfinite(muscle_fatigue):
            cue = 2
        elif muscle_fatigue >= .40:
            cue = 1
        else:
            cue = 2 if muscle_fatigue > .18 else 0
        self.posterior = self.agent.infer_states(
            [jnp.array([cue]), jnp.array([self.last_outcome])], self.prior)
        policy, _ = self.agent.infer_policies(self.posterior)
        action = int(np.asarray(self.agent.sample_action(policy)).item())
        beliefs = np.asarray(self.posterior[0]).reshape(-1, 6)[-1]
        probs = np.asarray(policy).reshape(-1)
        return {"requested": ACTIONS[action], "cue": CUES[cue],
                "ready_posterior": float(beliefs[:3].sum()),
                "action_probabilities": dict(zip(ACTIONS, map(float, probs), strict=True))}

    def feedback(self, selected, muscle_fatigue):
        # The transition follows the native arbitration result, including vetoes.
        action = ACTIONS.index(selected) if selected in ACTIONS else ACTIONS.index("rest")
        self.prior = self.agent.update_empirical_prior(jnp.array([[action]]), self.posterior)
        self.last_outcome = 2 + int(muscle_fatigue >= .40) if action == 0 else action - 1

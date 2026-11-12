"""Small supervised numeric decoder: no prompt, label or simulator API."""
from dataclasses import dataclass
import math

from .sensory import LOCATIONS, TYPES, finite
from .state import digest

CLASSES = ('none',) + tuple(r + ':' + k for r in LOCATIONS for k in TYPES)


@dataclass(frozen=True)
class Prediction:
    occurred: bool
    probability: float
    location: str
    stimulus_type: str
    intensity: float
    confidence: float
    novelty_uncertain: bool


class Decoder:
    def __init__(self, examples, *, temperature=1.):
        self.temperature = finite(temperature, .1, 10)
        checked = []
        for features, label, intensity in examples:
            features = self.validate_features(features)
            if label not in CLASSES: raise ValueError('novel classes cannot train this decoder')
            checked.append((features, label, finite(intensity, 0, 1)))
        if len(checked) < 9: raise ValueError('at least nine training observations required')
        self.examples = tuple(checked)

    @staticmethod
    def validate_features(features):
        if type(features) is not tuple or len(features) != 12:
            raise ValueError('only twelve numeric internal features accepted')
        return tuple(finite(x, 0, 3) for x in features)

    def fingerprint(self):
        return digest({'examples': self.examples, 'temperature': self.temperature})

    def predict(self, features):
        features = self.validate_features(features)
        neighbours = sorted((sum((x-y)**2 for x, y in zip(features, old)), label, intensity)
                            for old, label, intensity in self.examples)[:9]
        votes = {key: .05 for key in CLASSES}
        # Bounded weights avoid exact replay dominating numerical calibration.
        weights = [1 / (.01 + d) for d, _, _ in neighbours]
        scale = sum(weights)
        for (_, label, _), w in zip(neighbours, weights): votes[label] += 9 * w / scale
        total = sum(votes.values())
        probabilities = {key: value / total for key, value in votes.items()}
        p = 1 - probabilities['none']
        p = 1 / (1 + math.exp(-math.log(p / (1-p)) / self.temperature))
        best = max(CLASSES[1:], key=probabilities.get)
        location, kind = best.split(':')
        detected = p >= .5
        intensity = sum(w * row[2] for row, w in zip(neighbours, weights)) / scale
        certainty = probabilities[best] / (1 - probabilities['none'])
        return Prediction(detected, p, location if detected else 'none', kind if detected else 'none',
                          intensity if detected else 0., certainty if detected else 1-p,
                          detected and certainty < .65)

    def with_temperature(self, temperature):
        return Decoder(self.examples, temperature=temperature)

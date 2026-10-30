"""Small River-compatible dependency surface for the vendored detector.

Mean.update/get are adapted from River stats/mean.py (BSD-3-Clause).
Copyright (c) 2020, the river developers. See third_party/river/LICENSE.
This is not a replacement for the full River estimator API.
"""
from types import SimpleNamespace


class Mean:
    def __init__(self):
        self.n = 0.0
        self._mean = 0.0

    def update(self, x, w=1.0):
        self.n += w
        self._mean += (w / self.n) * (x - self._mean)

    def get(self):
        return self._mean


class DriftDetector:
    def __init__(self):
        self._drift_detected = False

    @property
    def drift_detected(self):
        return self._drift_detected

    def _reset(self):
        self._drift_detected = False


stats = SimpleNamespace(Mean=Mean)

"""Behavioral checks for the isolated 2026-11-08 evening session."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import research as r


class EveningResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space = TemporaryDirectory()
        cls.addClassCleanup(cls.space.cleanup)
        cls.out = Path(cls.space.name)
        cls.invoke("--slot", "0")
        cls.receipt = r.read_slot(cls.out / "slot-00.json")

    @classmethod
    def invoke(cls, *args):
        capture = io.StringIO()
        with patch("sys.argv", ["research.py", "--out", str(cls.out), *args]), redirect_stdout(capture):
            r.main()
        return json.loads(capture.getvalue())

    def test_replay_uses_original_receipt(self):
        f = self.out / "slot-00.json"
        old = (f.read_bytes(), f.stat().st_mtime_ns)
        with patch.object(r, "cohort", side_effect=AssertionError("recomputed past slot")):
            result = self.invoke("--slot", "0")
        self.assertEqual(result["slot"], 0)
        self.assertEqual(old, (f.read_bytes(), f.stat().st_mtime_ns))

    def test_controls_and_analytic_peak_boundary(self):
        p = self.receipt["physiology"]
        for mode in ("no_start", "early_stop"):
            self.assertEqual(p[mode]["peaks"], 0)
            self.assertEqual(p[mode]["final_phase"], "baseline")
        for rhythm in (.1, .3, .5, .7, .9, 1.):
            a, b = [[t for t in p["boundary_traces"]
                     if t["rhythm"] == rhythm and t["recovery_cue"] == cue] for cue in (.25,.9)]
            self.assertEqual(len(a), 15)
            self.assertEqual([t["peaks"] for t in a], [t["peaks"] for t in b])
            hits = [t for t in a if t["peaks"]]
            misses = [t for t in a if not t["peaks"]]
            pred = a[0]["predicted_onset_s"]
            self.assertTrue(hits and misses)
            first = min(t["cutoff_s"] for t in hits)
            last_miss = max(t["cutoff_s"] for t in misses)
            self.assertAlmostEqual(first-last_miss,.1)
            self.assertLessEqual(abs(first-pred),.101)
            # Two-centisecond internal substeps set the precision of the modeled peak.
            self.assertTrue(all(abs(t["peak_at_s"]-pred) <= .020001 for t in hits))

    def test_label_perturbation_is_paired(self):
        rows = self.receipt["context"]["trials"]
        self.assertEqual({t["train_n"] for t in rows}, {16,64,320,960})
        self.assertEqual(len({t["seed"] for t in rows}), 128)
        self.assertTrue(all(t["label_errors"]==0 and
                            t["mean_utility"]["clean"]==t["mean_utility"]["noisy"] for t in rows))
        for trained in rows[:8]:
            other = r.context_trial(trained["seed"],1.,trained["train_n"])
            self.assertEqual(other["label_errors"],128)
            for metric in ("clean","oracle","blind","rest"):
                self.assertEqual(other["mean_utility"][metric],trained["mean_utility"][metric])
            self.assertGreaterEqual(other["mean_utility"]["oracle"],other["mean_utility"]["noisy"])

    def test_reversal_vs_matched_frozen_and_censoring(self):
        trials = self.receipt["reversal"]["trials"]
        zero = (0.,0.,0.)
        paired_expected = r.changed_utility("rest",zero)-r.changed_utility("explore",zero)
        for t in trials:
            self.assertEqual(t["frozen"],"explore")
            if t["final"]==t["frozen"]:
                self.assertIsNone(t["blocks_to_rest_through_end"])
                self.assertEqual(t["heldout_gain_over_frozen"],0.)
            else:
                self.assertEqual(t["final"],"rest")
                self.assertAlmostEqual(t["heldout_gain_over_frozen"],paired_expected,places=6)
                self.assertLessEqual(t["blocks_to_rest_through_end"],128)
        short = [t for t in trials if t["pre_blocks"]==8]
        long = [t for t in trials if t["pre_blocks"]==512]
        self.assertTrue(all(t["final"]=="rest" for t in short))
        self.assertTrue(all(t["final"]=="explore" for t in long))

    def test_recorded_counts_and_summary(self):
        d = self.receipt
        p = d["physiology"]
        s = self.invoke("--summary")
        self.assertEqual(s["latest_slot"],0)
        self.assertEqual(s["slots"],1)
        self.assertEqual(s["physiology_cases"],len(p["traces"])+len(p["boundary_traces"])+2)
        self.assertEqual(s["reversal_trials"],len(d["reversal"]["trials"]))
        self.assertEqual(s["heldout_choices"],128*len(d["context"]["trials"]))
        self.assertEqual(s["control_peak_count"],0)
        self.assertEqual(s["reversal_results"]["512"]["median_blocks"],None)
        self.assertEqual(set(d["source_commits"]),set(r.PINS))

    def test_bad_slot_identity_is_rejected(self):
        p = self.out / "slot-01.json"
        p.write_text(json.dumps(self.receipt),encoding="utf-8")
        try:
            with self.assertRaisesRegex(ValueError,"incompatible"):
                r.read_slot(p)
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()

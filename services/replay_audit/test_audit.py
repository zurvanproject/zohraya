import json
import unittest
from .audit import audit, MAX_BYTES


def event(kind, run="r1", request="q1", cost=0, **extra):
    return dict(at="2026-10-21T09:00:00Z", kind=kind, run_id=run,
                request_id=request, cost_minor=cost, **extra)


def raw(*events):
    return "\n".join(json.dumps(e) for e in events).encode()


class AuditTests(unittest.TestCase):
    def check(self, *events):
        return audit(raw(*events), 100, "USD")

    def test_clean_trace(self):
        r = self.check(event("start"), event("effect", effect_id="e1", cost=100), event("finish"))
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["reported_cost_minor"], 100)

    def test_repeated_effect_across_retries(self):
        r = self.check(event("start"), event("effect", effect_id="e1"), event("fail"),
                       event("start", "r2", "q1"), event("effect", "r2", effect_id="e1"))
        self.assertEqual(r["counts"], {"duplicate_effect": 1, "request_reused": 1, "unresolved_run": 1})
        self.assertEqual(r["findings"][1]["related_line"], 2)

    def test_wrong_request_cannot_close_run(self):
        r = self.check(event("start"), event("finish", request="q2"))
        self.assertEqual(r["counts"], {"orphan_terminal": 1, "unresolved_run": 1})

    def test_duplicate_start_and_terminal(self):
        r = self.check(event("start"), event("start"), event("finish"), event("finish"))
        self.assertEqual(r["counts"], {"duplicate_start": 1, "request_reused": 1, "duplicate_terminal": 1})

    def test_effect_after_completion(self):
        self.assertEqual(self.check(event("start"), event("finish"), event("effect", effect_id="e1"))["counts"], {"effect_outside_run": 1})

    def test_costs_incremental_and_overrun_once(self):
        r = self.check(event("start", cost=50), event("effect", effect_id="e1", cost=51), event("finish", cost=1))
        self.assertEqual(r["reported_cost_minor"], 102)
        self.assertEqual(r["counts"], {"budget_exceeded": 1})

    def test_invalid_schema_and_unknown_fields(self):
        for change in ({"cost_minor": -1}, {"cost_minor": True}, {"cost_minor": 0.2},
                       {"at": "2026-10-21T09:00:00"}, {"secret": "secret-value"}, {"kind": "shell"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                audit(raw(event("start") | change), 100, "USD")

    def test_out_of_order_and_timezone_equivalence(self):
        a = event("start")
        b = event("finish") | {"at": "2026-10-21T12:30:00+03:30"}
        self.assertFalse(self.check(a, b)["findings"])
        b["at"] = "2026-10-21T08:00:00Z"
        with self.assertRaises(ValueError):
            self.check(a, b)

    def test_report_omits_raw_identifiers(self):
        r = self.check(event("start", run="private-run", request="private-request"))
        self.assertNotIn("private-", json.dumps(r))

    def test_bounds_and_determinism(self):
        for data in (b"", b" " * (MAX_BYTES + 1), b"\xff", raw(*([event("start")] * 5001))):
            with self.assertRaises(ValueError):
                audit(data, 100, "USD")
        self.assertEqual(self.check(event("start")), self.check(event("start")))


if __name__ == "__main__":
    unittest.main()

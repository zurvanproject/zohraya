"""Regression for receipt-cache eviction after canonical JSON key sorting."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest

from synthetic_fixture import synthetic_body
from unified_body_v2 import UnifiedBody, digest, instant


class CacheOrderChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = synthetic_body()
        for index in range(33):
            body = cls.template
            body.cycle(event_id='order-'+digest(index)[:12],
                at_utc=(instant(body.owner.wall_utc)+timedelta(seconds=.1)).isoformat(),
                duration_s=.1, requested='observe', expected_revision=body.revision)

    def restored_pair(self):
        live = deepcopy(self.template)
        cold = UnifiedBody.restore(json.loads(json.dumps(live.checkpoint(),sort_keys=True)))
        return live, cold

    def test_both_cache_orders_survive_sorted_json_restore(self):
        live, cold = self.restored_pair()
        self.assertEqual(list(live.results),list(cold.results))
        self.assertEqual(list(live.owner.results),list(cold.owner.results))

    def test_next_eviction_keeps_exact_state_and_receipt(self):
        live, cold = self.restored_pair()
        event=dict(event_id='continuation-after-sort',
            at_utc=(instant(live.owner.wall_utc)+timedelta(seconds=.1)).isoformat(),
            duration_s=.1,requested='observe',expected_revision=live.revision)
        self.assertEqual(live.cycle(**event),cold.cycle(**event))
        self.assertEqual(live.checkpoint(),cold.checkpoint())


if __name__ == '__main__':
    unittest.main(verbosity=2)

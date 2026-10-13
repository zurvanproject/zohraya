from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from reflection_cycle import ReflectionCycle
ROOT=Path(__file__).resolve().parent
CASES=json.loads((ROOT/'stage2_cases.json').read_text())['cases']

class Stage2MemoryTests(unittest.TestCase):
 def scenario(self,kind):
  c=deepcopy(next(c for c in CASES if c['type']==kind and c['split']=='final'))
  with tempfile.TemporaryDirectory() as tmp,ReflectionCycle(Path(tmp)/'ledger.sqlite') as e:
   for h in c['history']:
    e.decide(h['request']);e.complete(h['request']['id'],h['actual_outcome'],verified=h['verified'],evidence=h['evidence'],reason=h['reason'])
   self.assertEqual(e.decide(c['request'])['selected_action'],c['expected'])
 def test_aged_correction_survives_130_unrelated_same_topic_decisions(self):self.scenario('aged')
 def test_changed_expected_outcome_cannot_inherit_failure(self):self.scenario('changed_expectation')
 def test_explicitly_expired_feedback_does_not_penalize(self):self.scenario('expired_feedback')
 def test_order_only_change_of_requirements_keeps_recall(self):self.scenario('permuted_requirements')
 def test_unverified_success_does_not_erase_verified_failure(self):self.scenario('unverified_success')
 def test_expired_latest_success_does_not_revive_older_failure(self):
  c=deepcopy(next(c for c in CASES if c['type']=='related' and c['split']=='final'))
  with tempfile.TemporaryDirectory() as tmp,ReflectionCycle(Path(tmp)/'ledger.sqlite') as e:
   h=c['history'][0];e.decide(h['request']);e.complete(h['request']['id'],h['actual_outcome'],verified=True,evidence=h['evidence'],reason=h['reason'])
   success=deepcopy(h['request']);success['id']='later-success';w=deepcopy(h['evidence']);w[0]['expires_at']='2026-10-11T00:00:00+00:00'
   e.decide(success);e.complete(success['id'],{'status':'completed'},verified=True,evidence=w,reason='later explicitly expired success witness')
   self.assertEqual(e.decide(c['request'])['selected_action'],c['request']['actions'][0]['id'])
 def test_index_write_failure_rolls_back_feedback(self):
  c=deepcopy(next(c for c in CASES if c['type']=='related' and c['split']=='final'));h=c['history'][0]
  with tempfile.TemporaryDirectory() as tmp,ReflectionCycle(Path(tmp)/'ledger.sqlite') as e:
   e.decide(h['request']);before=e.export()
   e.db.execute("CREATE TEMP TRIGGER fail_index BEFORE INSERT ON feedback_index BEGIN SELECT RAISE(ABORT,'generated storage failure'); END")
   with self.assertRaises(sqlite3.IntegrityError):e.complete(h['request']['id'],h['actual_outcome'],verified=True,evidence=h['evidence'],reason=h['reason'])
   self.assertEqual(e.export(),before);self.assertEqual(e.db.execute('SELECT count(*) FROM feedback_index').fetchone()[0],0)
 def test_claim_order_does_not_change_semantic_signature(self):
  from reflection_cycle import action_signature
  c=deepcopy(next(c for c in CASES if c['type']=='valid' and c['split']=='final')['request']['actions'][0]);c['claims']=[{'key':'alpha','value':1},{'key':'beta','value':2}];before=action_signature(c);c['claims'].reverse();self.assertEqual(action_signature(c),before)

if __name__=='__main__':unittest.main()

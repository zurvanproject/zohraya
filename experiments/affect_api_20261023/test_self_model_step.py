import copy
import json
import unittest
from unittest.mock import patch
from . import self_model_step as m, session as s
from .test_session import Ledger

def response():
    rows=[dict(id=f,predicted_action='walk',predicted_metrics=dict.fromkeys(m.METRICS,.5),
               confidence=.5,prior_attribution='no_history',self_model_fa='وضعیت مشاهده‌شده',unknowns_fa='پیامد هنوز اجرا نشده است.') for f in m.FIXTURES]
    return dict(id='resp_fixture',model=s.MODEL,status='completed',service_tier='default',
        output=[dict(type='message',content=[dict(type='output_text',text=s.encode(dict(predictions=rows)))])],
        usage=dict(input_tokens=1000,output_tokens=500))

class Tests(unittest.TestCase):
    def test_prediction_contract(self):
        self.assertEqual(len(m.parse(response())['predictions']),2)
        r=response(); rows=json.loads(r['output'][0]['content'][0]['text'])
        rows['predictions'][0]['confidence']=float('nan')
        r['output'][0]['content'][0]['text']=s.encode(rows)
        with self.assertRaises(ValueError): m.parse(r)

    def test_prediction_error_and_attribution_use_actual_receipt(self):
        p=m.parse(response())['predictions'][0]
        before=dict(observed=dict.fromkeys(m.METRICS,.5))
        receipt=dict(actual_action='protect',self_model_after=dict(minimum_state=dict.fromkeys(m.METRICS,.6)))
        result=m.measured(p,before,receipt,'host_changed_preference')
        self.assertAlmostEqual(result['metric_mae'],.1)
        self.assertFalse(result['action_correct'])
        self.assertFalse(result['attribution_correct'])

    def test_budget_reservation_before_send_and_two_call_cap(self):
        state=dict(calls=[],prior_cost=dict(reserved_micro_usd=360000))
        ledger=Ledger()
        def send(*args):
            self.assertEqual(ledger.snapshots[-1]['calls'][-1]['status'],'pending')
            return response()
        with patch.object(s,'request_json',side_effect=send) as api:
            m.paid(state,ledger,[],[],'mock-key')
            m.paid(state,ledger,[],[],'mock-key')
            with self.assertRaises(ValueError): m.paid(state,ledger,[],[],'mock-key')
            self.assertEqual(api.call_count,2)
        self.assertEqual(360000+sum(x['reserved_micro_usd'] for x in state['calls']),440000)

    def test_unknown_result_blocks_retry_and_keeps_reservation(self):
        state=dict(calls=[],prior_cost=dict(reserved_micro_usd=360000))
        ledger=Ledger()
        with patch.object(s,'request_json',side_effect=TimeoutError('private-detail')) as api:
            with self.assertRaises(RuntimeError): m.paid(state,ledger,[],[],'mock-key')
            with self.assertRaises(ValueError): m.paid(state,ledger,[],[],'mock-key')
            self.assertEqual(api.call_count,1)
        self.assertNotIn('private-detail',s.encode(state))
        self.assertEqual(state['calls'][0]['reserved_micro_usd'],40000)

    def test_payload_bound_and_future_outcome_absent(self):
        p=m.payload([dict(id='normal',observed=dict.fromkeys(m.METRICS,.5))],[])
        self.assertEqual(json.loads(p['input'])['previous_observed_episodes'],[])
        with self.assertRaises(ValueError): m.payload([{'x':'x'*50000}],[])

if __name__=='__main__': unittest.main()

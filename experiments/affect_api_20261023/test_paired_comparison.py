import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from . import paired_comparison as p, self_model_step as m, session as s
from .test_session import Ledger

def response():
    predictions=[dict(id=c['id'],predicted_action='walk',predicted_metrics=dict.fromkeys(m.METRICS,.5)) for c in p.CASES]
    return dict(id='resp_test_only',model=s.MODEL,status='completed',service_tier='default',
        output=[dict(type='message',content=[dict(type='output_text',text=s.encode(dict(predictions=predictions)))])],
        usage=dict(input_tokens=1000,output_tokens=500))

class Tests(unittest.TestCase):
    def test_memory_uses_nearest_state_and_scales_observed_delta(self):
        observation=dict(id='new',fixture='normal',duration_s=.2,observed=dict.fromkeys(m.METRICS,.5))
        history=[dict(id='past',fixture='normal',duration_s=.1,observed=dict.fromkeys(m.METRICS,.5),
                      actual_metrics=dict.fromkeys(m.METRICS,.6),actual_action='protect'),
                 dict(id='unrelated',fixture='sleep',duration_s=.1,observed=dict.fromkeys(m.METRICS,.5),
                      actual_metrics=dict.fromkeys(m.METRICS,0),actual_action='observe')]
        original=copy.deepcopy((observation,history))
        result=p.baselines(observation,history)
        self.assertEqual(result['persistence']['predicted_action'],'walk')
        self.assertEqual(result['nearest_episode']['predicted_action'],'protect')
        self.assertAlmostEqual(result['nearest_episode']['predicted_metrics']['energy'],.7)
        self.assertEqual((observation,history),original)
        observation['duration_s']=1
        self.assertEqual(p.baselines(observation,history)['nearest_episode']['predicted_metrics']['energy'],1.)

    def test_score_known_absolute_error_and_action(self):
        prediction=dict(predicted_metrics=dict(zip(m.METRICS,[.1,.2,.3,.4])),predicted_action='walk')
        result=p.score(prediction,dict.fromkeys(m.METRICS,.2),'observe')
        self.assertAlmostEqual(result['metric_mae'],.1)
        self.assertFalse(result['action_correct'])

    def test_parse_rejects_duplicate_case_and_nonfinite(self):
        self.assertEqual(len(p.parse(response())),6)
        for mutation in ('duplicate','nan'):
            r=response(); data=json.loads(r['output'][0]['content'][0]['text'])
            if mutation=='duplicate': data['predictions'][1]['id']=data['predictions'][0]['id']
            else: data['predictions'][0]['predicted_metrics']['energy']=float('nan')
            r['output'][0]['content'][0]['text']=s.encode(data)
            with self.assertRaises(ValueError): p.parse(r)

    def test_reservation_before_send_raw_before_parse_and_cap(self):
        state=dict(calls=[],prior_cost=dict(reserved_micro_usd=440000)); ledger=Ledger()
        def send(*args):
            self.assertEqual(ledger.snapshots[-1]['calls'][-1]['status'],'pending')
            return response()
        with patch.object(s,'request_json',side_effect=send) as api:
            p.paid(state,ledger,[],[],'mock-key'); p.paid(state,ledger,[],[],'mock-key')
            with self.assertRaises(ValueError): p.paid(state,ledger,[],[],'mock-key')
        self.assertEqual(api.call_count,2)
        self.assertTrue(any(x['calls'][-1].get('provider_response') and x['calls'][-1]['status']=='pending' for x in ledger.snapshots))
        blocked=dict(calls=[],prior_cost=dict(reserved_micro_usd=990000))
        with patch.object(s,'request_json') as api:
            with self.assertRaises(ValueError): p.paid(blocked,Ledger(),[],[],'mock-key')
            api.assert_not_called()

    def test_unknown_response_blocks_retry(self):
        state=dict(calls=[],prior_cost=dict(reserved_micro_usd=440000)); ledger=Ledger()
        with patch.object(s,'request_json',side_effect=TimeoutError('private')) as api:
            with self.assertRaises(RuntimeError): p.paid(state,ledger,[],[],'mock-key')
            with self.assertRaises(ValueError): p.paid(state,ledger,[],[],'mock-key')
            self.assertEqual(api.call_count,1)
        self.assertNotIn('private',s.encode(state))

    def test_execution_freezes_all_predictions_before_ground_truth(self):
        state=dict(calls=[],calibration=[],prior_cost=dict(reserved_micro_usd=440000,estimated_micro_usd=12653))
        ledger=Ledger(); ledger.token='mock-github'
        events=[]
        def body(command,path,*args):
            snapshot=dict(minimum_state=dict.fromkeys(m.METRICS,.5),checkpoint_sha256='checkpoint')
            if command=='start': path.write_bytes(b'test checkpoint')
            if command=='observe': return snapshot
            if command=='status': return dict(self_model=snapshot)
            if command=='step':
                self.assertEqual(ledger.snapshots[-1]['rounds'][-1]['status'],'predictions_frozen')
                self.assertEqual(len(ledger.snapshots[-1]['rounds'][-1]['baseline_predictions']),6)
                events.append('step')
                return dict(actual_action='walk',self_model_after=snapshot)
        seen_histories=[]
        def paid(state,ledger,observations,history,key):
            events.append('predict'); seen_histories.append(copy.deepcopy(history))
            self.assertEqual(len(observations),6)
            state['calls'].append(dict(usage=dict(estimated_upper_micro_usd=1)))
            return p.parse(response())
        with tempfile.TemporaryDirectory() as directory, patch.object(m,'body',side_effect=body), patch.object(p,'paid',side_effect=paid), patch.object(s,'request_json'):
            p.run(state,ledger,'mock-key',Path(directory))
        self.assertEqual(events,['predict']+['step']*6+['predict']+['step']*6)
        self.assertEqual([len(h) for h in seen_histories],[0,6])
        self.assertEqual(state['assessment']['api']['n'],12)
        self.assertEqual(state['assessment']['api']['metric_mae'],0)
        self.assertFalse(state['api_numeric_benefit'])

    def test_payload_envelope_and_evidence_only(self):
        value=p.payload([],[])
        self.assertEqual(json.loads(value['input']),dict(observations=[],previous_observed_episodes=[]))
        with self.assertRaises(ValueError): p.payload([dict(x='x'*50000)],[])

if __name__=='__main__': unittest.main()

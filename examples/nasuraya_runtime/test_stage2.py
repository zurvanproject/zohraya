"""Development seeds only. No first test split is inspected by unit tests."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.dios_nous.unified import body as body_export
from examples.tadash_interoception.state import canonical
from .adapters import ROOT, decoder
from .session import Session
from .__main__ import demo_frames
from . import reconsider, stream_study


def unit_observation(revision, *, pain=.1, sleep=.3, energy=.9, fatigue=.1):
    """Declared unit fixture, not an authenticated native body or action authority.

    Full runtime retries additionally execute preflight in a real native copy.
    """
    path=ROOT/'docs/evidence/nasuraya-integration-v01/native-snapshot.json.gz'
    record=json.loads(gzip.decompress(path.read_bytes()))['body']['export']
    record['minimum_state'].update(pain=pain,sleep_pressure=sleep,energy=energy,fatigue=fatigue)
    record.update(revision=revision,sampled_at_s=float(revision),native_checkpoint_sha256=f'{revision:064x}')
    record['sha256']=body_export._digest({k:v for k,v in record.items() if k!='sha256'})
    return {'export':record,'clock':float(revision),
            'checkpoint':{'sha256':f'{revision:064x}','payload':{'revision':revision}}}


class GateTests(unittest.TestCase):
    def test_persistent_sleep_never_expires_by_time(self):
        block=reconsider.block(unit_observation(0,sleep=.95))
        for revision in range(1,20):
            block, result=reconsider.assess(block,unit_observation(revision,sleep=.95),enabled=True)
            self.assertFalse(result['eligible_for_native_preflight'])
        self.assertEqual(block['safe_streak'],0)

    def test_distinct_safe_observations_and_resolution_required(self):
        block=reconsider.block(unit_observation(0,pain=.8))
        block,first=reconsider.assess(block,unit_observation(1),enabled=True)
        self.assertFalse(first['eligible_for_native_preflight'])
        repeated,result=reconsider.assess(block,unit_observation(1),enabled=True)
        self.assertEqual(repeated,block)
        self.assertFalse(result['eligible_for_native_preflight'])
        block,second=reconsider.assess(block,unit_observation(2),enabled=True)
        self.assertTrue(second['eligible_for_native_preflight'])
        self.assertFalse(second['forecast_is_observed_success'])

    def test_new_unsafe_observation_resets_streak(self):
        block=reconsider.block(unit_observation(0,pain=.8))
        block,_=reconsider.assess(block,unit_observation(1),enabled=True)
        block,_=reconsider.assess(block,unit_observation(2,sleep=.8),enabled=True)
        block,result=reconsider.assess(block,unit_observation(3),enabled=True)
        self.assertEqual(block['safe_streak'],1)
        self.assertFalse(result['eligible_for_native_preflight'])

    def test_disabled_unknown_stale_and_unbound_stay_blocked(self):
        unknown=reconsider.block(unit_observation(0))
        self.assertEqual(reconsider.assess(unknown,unit_observation(1),enabled=True)[1]['reason'],
                         'unknown_veto_cause_requires_review')
        block=reconsider.block(unit_observation(0,pain=.8))
        self.assertEqual(reconsider.assess(block,unit_observation(1),enabled=False)[0],block)
        stale=unit_observation(1);stale['clock']+=6
        with self.assertRaises(ValueError):reconsider.assess(block,stale,enabled=True)
        unbound=unit_observation(1);unbound['checkpoint']['sha256']='f'*64
        with self.assertRaises(ValueError):reconsider.assess(block,unbound,enabled=True)


class StreamTests(unittest.TestCase):
    def test_whole_stream_splits_disjoint_and_development_separate(self):
        seen=set()
        for seeds in stream_study.SPLITS.values():
            self.assertFalse(seen.intersection(seeds));seen.update(seeds)
            self.assertGreater(min(seeds),10000)

    def test_stream_and_cold_state_repeat_for_all_ablations(self):
        for variant in stream_study.VARIANTS:
            a=stream_study.rows([11,12],variant=variant,ticks=80)
            b=stream_study.rows([11,12],variant=variant,ticks=80)
            self.assertEqual(a,b)
            self.assertTrue(all(r['memory_consistent'] for r in a))
            self.assertTrue(all(len(r['features'])==12 for r in a))

    def test_truth_history_uses_only_the_last_twelve_ticks(self):
        samples,_=stream_study.generate(13,ticks=80)
        for row in stream_study.rows([13],ticks=80):
            active=[x for _,x in samples[row['tick']-12:row['tick']] if x is not None]
            self.assertEqual(row['truth']['occurred'],bool(active))
            self.assertEqual(row['truth']['classifiable'],
                             len({(x[0],x[1]) for x in active})==1)

    def test_predictor_cannot_use_labels_or_truth(self):
        rows=stream_study.rows([14,15],ticks=80)
        original=stream_study.predict(stream_study.legacy(),rows)
        altered=deepcopy(rows)
        for row in altered:
            row['label']='fabricated';row['truth']={'occurred':False};row['seed']=-99;row['condition']='fabricated'
        self.assertEqual(original,stream_study.predict(stream_study.legacy(),altered))

    def test_fit_budget_and_no_holdout_or_novel_fitting(self):
        rows=stream_study.rows(range(20,28),ticks=160)
        model=stream_study.fit(rows)
        self.assertLessEqual(len(model.examples),256)
        self.assertEqual(model.fingerprint(),stream_study.decode(stream_study.encode(model)).fingerprint())
        bad=deepcopy(rows);bad[0]['seed']=stream_study.SPLITS['test'][0]
        with self.assertRaisesRegex(ValueError,'training stream IDs'):stream_study.fit(bad)
        bad=deepcopy(rows);bad[0]['truth']['novel_present']=True
        with self.assertRaisesRegex(ValueError,'novel'):stream_study.fit(bad)

    def test_cluster_bootstrap_resamples_streams_and_is_paired(self):
        rows=stream_study.rows([30,31,32],ticks=80)
        predictions=stream_study.predict(stream_study.legacy(),rows)
        result=stream_study.cluster_interval(rows,predictions,predictions)
        self.assertEqual(result['brier'],{'delta':0.,'ci95':[0.,0.]})
        self.assertEqual(result['accuracy'],{'delta':0.,'ci95':[0.,0.]})


@unittest.skipUnless(sys.platform=='linux','native owner requires Linux')
class NativeReconsiderationTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def episode(self,name,fixture,enabled):
        session=Session.create(self.root/name,backend='native',fixture=fixture,
                               reconsideration=enabled,max_actions=8)
        receipts=[]
        try:
            for index in range(8):
                if index==3:
                    snapshot=session.snapshot();session.close();session=Session(self.root/name)
                    self.assertEqual(snapshot,session.snapshot())
                receipts.append(session.step('e'+str(index),demo_frames(index,0),expected_revision=index))
            snap=session.snapshot();session.stop()
            with patch('examples.nasuraya_runtime.session.native_call',side_effect=AssertionError('no post-stop probe')):
                with self.assertRaisesRegex(ValueError,'stopped'):
                    session.step('after-stop',demo_frames(8,0),expected_revision=9)
        finally:session.close()
        return receipts,snap

    def test_transient_native_recovery_can_revise_actual_action_evidence(self):
        blocked,_=self.episode('permanent','transient_pain',False)
        corrected,snap=self.episode('corrected','transient_pain',True)
        self.assertEqual(sum(r['outcome']['executed']=='walk' for r in blocked),0)
        self.assertTrue(any(r['outcome']['body_veto'] for r in corrected))
        attempts=[r for r in corrected if r['reconsideration'].get('retry_permitted')]
        self.assertEqual(len(attempts),1)
        retry=attempts[0]
        self.assertEqual(retry['outcome']['executed'],'walk')
        self.assertEqual(retry['reconsideration']['safe_streak'],2)
        self.assertEqual(retry['candidate_review']['evidence_review']['decision'],'B')
        self.assertEqual(snap['dios']['action_reviews']['walk']['evidence_review']['decision'],'A')
        self.assertNotIn('walk',snap['retry_blocks'])

    def test_persistent_sleep_never_retries_even_after_restart(self):
        receipts,snap=self.episode('sleep','sleep',True)
        self.assertEqual(sum(r['requested']=='walk' for r in receipts),1)
        self.assertFalse(any(r['reconsideration'].get('retry_permitted') for r in receipts))
        self.assertEqual(snap['dios']['action_reviews']['walk']['evidence_review']['decision'],'B')

    def test_counterfactual_preflight_does_not_commit_body_state(self):
        from .adapters import native_call
        native=native_call({'checkpoint':None,'fixture':'normal'})
        before=canonical(native)
        preview=native_call({'checkpoint':native['checkpoint'],'fixture':'normal','duration':.1,
                            'touch':0.,'event_id':'preview','requested':'walk','mode':'preflight'})
        self.assertEqual(preview['origin_checkpoint_sha'],native['checkpoint']['sha256'])
        self.assertEqual(preview['actual_session_cycles_committed'],0)
        self.assertEqual(canonical(native),before)
        self.assertEqual(preview['selected'],'walk')

    def test_forecast_from_other_checkpoint_cannot_authorize_retry(self):
        from .adapters import native_call
        with Session.create(self.root/'binding',backend='native',fixture='transient_pain',
                            reconsideration=True,max_actions=4) as session:
            for i in range(3):session.step('e'+str(i),demo_frames(i,0),expected_revision=i)
            before=session.snapshot()
            def swapped(request):
                if request.get('mode')=='preflight':
                    return {'origin_checkpoint_sha':'f'*64,'selected':'walk'}
                return native_call(request)
            with patch('examples.nasuraya_runtime.session.native_call',side_effect=swapped):
                with self.assertRaisesRegex(ValueError,'different owner'):
                    session.step('e3',demo_frames(3,0),expected_revision=3)
            self.assertEqual(before,session.snapshot())
            self.assertEqual(session.step('e3',demo_frames(3,0),expected_revision=3)['outcome']['executed'],'walk')
            with patch('examples.nasuraya_runtime.session.native_call',side_effect=AssertionError('no post-budget probe')):
                with self.assertRaisesRegex(ValueError,'budget'):
                    session.step('e4',demo_frames(4,0),expected_revision=4)


@unittest.skipUnless((ROOT/'docs/evidence/nasuraya-stage2-v01/frozen-models.json.gz').exists(),
                     'continuous model has not yet been frozen')
class ContinuousRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='linux','native owner requires Linux')
    def test_continuous_decoder_and_native_retry_share_one_resumed_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'combined'
            session=Session.create(path,backend='native',fixture='transient_pain',
                decoder_version='continuous_v1',reconsideration=True,max_actions=8)
            receipts=[]
            try:
                for index in range(8):
                    if index==3:
                        before=session.snapshot();session.close();session=Session(path)
                        self.assertEqual(before,session.snapshot())
                    receipts.append(session.step('e'+str(index),demo_frames(index,0),expected_revision=index))
                self.assertEqual(sum(r['outcome']['executed']=='walk' for r in receipts),5)
                self.assertEqual(sum(r['reconsideration'].get('retry_permitted',False) for r in receipts),1)
                self.assertTrue(all(r['model_sha']==decoder('continuous_v1').fingerprint() for r in receipts))
                self.assertEqual(session.snapshot()['dios']['action_reviews']['walk']['evidence_review']['decision'],'A')
            finally:session.close()

    def test_selected_model_is_used_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'session'
            with Session.create(path,decoder_version='continuous_v1') as session:
                self.assertEqual(session.model.fingerprint(),decoder('continuous_v1').fingerprint())
                first=session.step('one',demo_frames(0,.8),expected_revision=0)
                snap=session.snapshot()
            with Session(path) as cold:
                self.assertEqual(cold.snapshot(),snap)
                self.assertEqual(cold.step('one',demo_frames(0,.8),expected_revision=0),first)

    def test_continuous_start_requires_complete_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Session.create(Path(tmp)/'session',decoder_version='continuous_v1') as session:
                with self.assertRaisesRegex(ValueError,'twelve observed ticks'):
                    session.step('too-short',demo_frames(0,0)[:1],expected_revision=0)
                self.assertEqual(session.snapshot()['actions_used'],0)


if __name__=='__main__':unittest.main()

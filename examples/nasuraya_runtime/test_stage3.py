"""Current body contract and signed-state integration; no new holdout reads."""
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from examples.nasuraya_body_loop.__main__ import SOURCE,verified_sources
from examples.tadash_interoception.sensory import AfferentFrame
from examples.tadash_interoception.state import canonical
from . import profile,noise_study
from .adapters import native_call,decoder,ROOT
from .perception import SignedTrace
from .session import Session
from .__main__ import demo_frames
from .audit import report


class ContractTests(unittest.TestCase):
    def test_one_approved_current_profile_and_explicit_archive(self):
        a=report();m=a['current_body']['morphology']
        self.assertEqual((m['ground_to_crown_cm'],m['ground_to_horn_tip_cm'],m['mass_kg'],m['tail_centerline_cm']),
                         (170,192,78,85))
        self.assertEqual(a['native_defaults']['body'],profile.CURRENT)
        self.assertFalse(a['noise_candidate']['promoted_to_default'])
        self.assertFalse(a['noise_candidate']['validation_accepted'])
        self.assertEqual(a['native_cycles_executed_by_this_audit'],0)

    def test_profile_derivation_is_deterministic_and_rejects_modified_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=Path(tmp)/'first';second=Path(tmp)/'second'
            for root in (first,second):
                for name in verified_sources():
                    f=root/name;f.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/name,f)
            a=profile.prepare(first);b=profile.prepare(second)
            self.assertEqual(a,b)
            self.assertEqual(a['contact_design']['mass_kg'],78)
            self.assertEqual(a['contact_design']['tail_length_m'],.85)
            with self.assertRaisesRegex(ValueError,'original verified bytes'):profile.prepare(first)
            verified_sources() # Original archive still verifies after derived executions.

    def test_new_splits_are_disjoint_and_do_not_reuse_stage2(self):
        from .stream_study import SPLITS as old
        seen={s for seeds in old.values() for s in seeds}
        for seeds in noise_study.SPLITS.values():
            self.assertFalse(seen.intersection(seeds));seen.update(seeds)
            self.assertGreater(min(seeds),10000)

    def test_rejected_candidate_cannot_become_qualified_decoder(self):
        self.assertTrue(decoder('noise_candidate').requires_signed_trace)
        with self.assertRaisesRegex(ValueError,'rejected on validation'):decoder('noise_v1')


class SignedStateTests(unittest.TestCase):
    def test_signed_noise_is_not_rectified_before_averaging(self):
        a=SignedTrace();b=SignedTrace()
        for i in range(64):
            x=.2 if i%2 else -.2
            a.step(AfferentFrame((i+1)/10,(x,)*6));b.step(AfferentFrame((i+1)/10,(abs(x),)*6))
        self.assertTrue(all(abs(x)<1e-12 for x in a.features()[18:24]))
        self.assertTrue(all(x>1 for x in b.features()[18:24]))

    def test_signed_cold_state_clocks_and_corruption(self):
        a=SignedTrace()
        for i in range(40):a.step(AfferentFrame((i+1)/10,tuple((i%5-2)*.02 for _ in range(6))))
        b=SignedTrace.restore(json.loads(canonical(a.checkpoint())))
        for i in range(40,90):
            f=AfferentFrame((i+1)/10,(.1,0,0,0,0,0));a.step(f);b.step(f)
        self.assertEqual(a.checkpoint(),b.checkpoint());self.assertEqual(len(a.values),64)
        bad=deepcopy(a.checkpoint());bad['state']['values'][0][0]+=1
        with self.assertRaises(ValueError):SignedTrace.restore(bad)
        with self.assertRaises(ValueError):a.step(AfferentFrame(99.,(0.,)*6))

    def test_generator_and_blind_readout_ignore_evaluator_metadata(self):
        rows=noise_study.rows([71,72],ticks=80);original=deepcopy(rows)
        self.assertEqual(rows,noise_study.rows([71,72],ticks=80))
        model=decoder('noise_candidate');p=noise_study.predict(model,rows)
        for row in rows:row.update(seed=-1,truth={'occurred':False},label='wrong',condition='wrong')
        self.assertEqual(p,noise_study.predict(model,rows))
        self.assertTrue(all(r['memory_consistent'] for r in original))

    def test_research_candidate_persists_in_shared_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'run'
            with Session.create(path,decoder_version='noise_candidate',max_actions=2) as s:
                empty=s.snapshot()
                with self.assertRaisesRegex(ValueError,'twelve observed ticks'):
                    s.step('short',(AfferentFrame(.1,(0.,)*6),),expected_revision=0)
                self.assertEqual(empty,s.snapshot())
                first=s.step('first',demo_frames(0,.8),expected_revision=0);snap=s.snapshot()
            with Session(path) as cold:
                self.assertEqual(cold.snapshot(),snap)
                self.assertEqual(cold.step('first',demo_frames(0,.8),expected_revision=0),first)
                cold.step('next',demo_frames(1,0),expected_revision=1)
                self.assertEqual(cold.snapshot()['signed_sensory_memory']['state']['time'],3.2)
                cold.stop()
                with self.assertRaisesRegex(ValueError,'stopped'):
                    cold.step('late',demo_frames(2,0),expected_revision=3)


@unittest.skipUnless(sys.platform=='linux','native owner requires Linux')
class CurrentNativeTests(unittest.TestCase):
    def test_actual_mass_pose_pools_and_heat_capacity(self):
        r=native_call({'checkpoint':None,'fixture':'normal'})
        p=r['physical_parameters'];m=r['export']['minimum_state'];stocks=r['export']['finite_stocks']
        self.assertEqual(r['model'],profile.CURRENT);self.assertEqual(p['mass_kg'],78)
        self.assertAlmostEqual(p['weight_N'],78*9.81);self.assertEqual(p['tail_length_m'],.85)
        self.assertAlmostEqual(p['pose']['parts']['horn_L'][2],1.92)
        self.assertLess(stocks['water_L'],44);self.assertGreater(stocks['water_L'],43)
        self.assertAlmostEqual(m['hydration'],stocks['water_L']/44)
        self.assertAlmostEqual(m['energy'],stocks['fuel_J']/1600000)
        self.assertAlmostEqual(m['temperature'],37+stocks['heat_J']/(78*3500))
        self.assertEqual(r['profile_receipt']['profile']['sha256'],profile.current()['sha256'])

    def test_cross_profile_checkpoint_is_rejected_and_cold_execution_matches(self):
        current=native_call({'checkpoint':None,'fixture':'normal'})
        legacy=native_call({'checkpoint':None,'fixture':'normal','body_profile':profile.LEGACY})
        self.assertEqual(legacy['physical_parameters']['mass_kg'],195)
        for checkpoint,kind in ((current['checkpoint'],profile.LEGACY),(legacy['checkpoint'],profile.CURRENT)):
            with self.assertRaises(RuntimeError):native_call({'checkpoint':checkpoint,'body_profile':kind,
                'fixture':'normal','duration':.1,'touch':0.,'requested':'observe','event_id':'wrong'})
        request={'checkpoint':current['checkpoint'],'fixture':'normal','duration':1.6,
                 'touch':0.,'requested':'walk','event_id':'same'}
        a=native_call(request);b=native_call(json.loads(json.dumps(request)))
        self.assertEqual(a,b)
        audit=a['receipt']['audit']
        self.assertLess(abs(audit['energy_error_J']),1e-6)
        self.assertLess(abs(audit['water_error_L']),1e-9)
        self.assertTrue(audit['same_owner_ticks'])

    def test_new_body_moves_and_sleep_still_vetoes(self):
        for fixture in ('normal','sleep'):
            r=native_call({'checkpoint':None,'fixture':fixture})
            origin=r['physical_parameters']['walk_touchdowns'];parts=r['physical_parameters']['pose']['parts']
            # A native touchdown takes longer than four 1.6 s control windows;
            # test a bounded 9.6 s sequence, not just a selected action name.
            for i in range(6):
                r=native_call({'checkpoint':r['checkpoint'],'fixture':fixture,'duration':1.6,
                    'touch':0.,'requested':'walk','event_id':'w'+str(i)})
                if fixture=='sleep':self.assertNotEqual(r['receipt']['executed'],'walk')
            if fixture=='normal':
                self.assertGreater(r['physical_parameters']['walk_touchdowns'],origin)
                self.assertNotEqual(r['physical_parameters']['pose']['parts']['foot_R'],parts['foot_R'])


if __name__=='__main__':unittest.main()

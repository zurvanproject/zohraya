"""Adversarial synthetic clocks; no real absence or GitHub ref write."""
import copy
from datetime import datetime,timedelta,timezone
import random
import unittest
from continuity_host import cadence as c
from continuity_host.test_cadence_host import gate,Fake,DUE,START


def later(hours): return (gate.timestamp(DUE)+timedelta(hours=hours)).isoformat()


class CadenceTests(unittest.TestCase):
    def setUp(self):
        f=Fake();self.s,self.l=f.state,f.ledger
    def admitted(self,hours=0,run_id='slot-0',source=True):
        self.s,self.l,b=c.claim(gate,self.s,self.l,later(hours),run_id,source_work=source)
        self.s=gate.finish(self.s,later(hours),run_id)
        return b
    def test_four_slices_preserve_rolling_time_and_source_caps(self):
        for i in range(4): self.assertEqual(self.admitted(i*6,'slot-'+str(i)),c.SLOT)
        self.assertEqual(sum(r['seconds'] for r in self.l['entries']),1200)
        self.assertEqual(sum(r['lines'] for r in self.l['entries']),300)
        self.assertEqual(sum(r['files'] for r in self.l['entries']),4)
        self.assertEqual(c.evaluate(gate,self.s,self.l,later(23))['reason'],'interval_not_elapsed')
        self.admitted(24,'next-day')
        self.assertEqual(len(self.l['entries']),4)
    def test_midnight_does_not_reset_interval_or_refund_budget(self):
        self.admitted(13,'before-midnight')
        self.assertEqual(c.evaluate(gate,self.s,self.l,later(14))['reason'],'interval_not_elapsed')
    def test_legacy_claim_is_full_twenty_minutes_at_migration(self):
        old=copy.deepcopy(self.s);old['last_claimed_at']=DUE;old['last_completed_run_id']='old'
        del old['cadence_sha256']
        self.s,self.l=c.migrate(gate,old,DUE)
        self.assertEqual(c.evaluate(gate,self.s,self.l,later(6))['reason'],'rolling_budget_used')
        self.assertTrue(c.evaluate(gate,self.s,self.l,later(24))['eligible'])
    def test_old_writer_after_migration_is_conservatively_reserved(self):
        self.s=gate.claim(self.s,DUE,'old-writer');self.s=gate.finish(self.s,DUE,'old-writer')
        self.assertEqual(c.evaluate(gate,self.s,self.l,later(6))['reason'],'rolling_budget_used')
        self.admitted(24,'new-writer')
        self.assertEqual(sum(r['seconds'] for r in self.l['entries']),300)
    def test_unknown_old_writer_and_pause_never_expire(self):
        self.s=gate.claim(self.s,DUE,'old-writer')
        self.assertEqual(c.evaluate(gate,self.s,self.l,later(240))['reason'],'unresolved_previous_run')
        self.s['enabled']=False
        self.assertEqual(c.evaluate(gate,self.s,self.l,later(240))['reason'],'paused')
        with self.assertRaises(ValueError): c.migrate(gate,self.s,later(240))
    def test_initial_absence_still_requires_twenty_four_hours(self):
        self.s['last_contact_at']=DUE
        self.assertEqual(c.evaluate(gate,self.s,self.l,later(23))['reason'],'recent_contact')
        self.assertTrue(c.evaluate(gate,self.s,self.l,later(24))['eligible'])
    def test_missing_ledger_or_seal_never_bootstraps(self):
        self.assertFalse(c.evaluate(gate,self.s,None,DUE)['eligible'])
        del self.s['cadence_sha256']
        self.assertFalse(c.evaluate(gate,self.s,self.l,DUE)['eligible'])
    def test_lost_reservation_or_modified_budget_fails_closed(self):
        self.admitted(0,'slot-a');self.admitted(6,'slot-b')
        for change in ('drop','time','files'):
            ledger=copy.deepcopy(self.l)
            if change=='drop': ledger['entries'].pop(0)
            else: ledger['entries'][0]['seconds' if change=='time' else 'files']=-1
            self.assertFalse(c.evaluate(gate,self.s,ledger,later(12))['eligible'])
    def test_matching_bad_ledger_schema_still_fails_closed(self):
        self.l['entries']=[dict(at=DUE,run_id='bad',kind='slot',seconds=0,files=0,lines=0)]
        self.l['observed_claim_at']=DUE;self.s['last_claimed_at']=DUE
        self.s['cadence_sha256']=c.fingerprint(self.l)
        self.assertFalse(c.evaluate(gate,self.s,self.l,later(6))['eligible'])
    def test_clock_regression_and_reused_ids_rejected_without_mutation(self):
        self.admitted(0,'slot-a');before=copy.deepcopy((self.s,self.l))
        self.assertFalse(c.evaluate(gate,self.s,self.l,START)['eligible'])
        with self.assertRaises(ValueError): c.claim(gate,self.s,self.l,later(6),'slot-a')
        self.assertEqual((self.s,self.l),before)
    def test_read_only_probe_reserves_time_but_no_source_authority(self):
        self.assertEqual(self.admitted(0,'probe',False),dict(seconds=300,files=0,lines=0))
        self.assertFalse(c.evaluate(gate,self.s,self.l,later(5))['eligible'])
    def test_original_gate_cannot_grant_second_daily_legacy_run(self):
        self.admitted(0,'slot-a')
        self.assertEqual(gate.evaluate(self.s,later(6))['reason'],'daily_budget_used')
        self.assertTrue(c.evaluate(gate,self.s,self.l,later(6))['eligible'])
    def test_existing_cadence_cannot_be_reinitialized(self):
        self.admitted(0,'slot-a')
        with self.assertRaises(ValueError): c.migrate(gate,self.s,later(6))
    def test_competing_atomic_claims_have_one_budget_reservation(self):
        api=Fake();a=api.snapshot();b=api.snapshot()
        sa,la,_=c.claim(gate,a['state'],a['ledger'],DUE,'writer-a')
        sb,lb,_=c.claim(gate,b['state'],b['ledger'],DUE,'writer-b')
        api.save(a,sa,ledger=la)
        with self.assertRaises(RuntimeError): api.save(b,sb,ledger=lb)
        self.assertEqual(sum(r['seconds'] for r in api.ledger['entries']),300)
    def test_seeded_irregular_arrivals_match_independent_rolling_account(self):
        rng=random.Random(20261017);at=gate.timestamp(DUE);accepted=[]
        for i in range(400):
            at+=timedelta(seconds=rng.randrange(0,36001));stamp=at.isoformat()
            recent=[t for t in accepted if (at-t).total_seconds()<86400]
            expected=(not accepted or (at-accepted[-1]).total_seconds()>=21600) and len(recent)<4
            self.assertEqual(c.evaluate(gate,self.s,self.l,stamp)['eligible'],expected)
            if expected:
                self.s,self.l,_=c.claim(gate,self.s,self.l,stamp,'generated-'+str(i),source_work=True)
                self.s=gate.finish(self.s,stamp,'generated-'+str(i));accepted.append(at)
                self.assertLessEqual(sum(r['seconds'] for r in self.l['entries']),1200)
                self.assertLessEqual(sum(r['lines'] for r in self.l['entries']),300)


if __name__=='__main__': unittest.main()

"""Offline search over synthetic, source-pinned dialogue history only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.nasuraya_affect import history
from examples.nasuraya_affect.body_dialogue import DialogueBodyBridge
from examples.nasuraya_affect.engine import AffectiveAgent, CHECKS
from examples.nasuraya_body_loop.host import BodyLoop
from nasuraya import history_search_worker as target

ROOT = Path(__file__).resolve().parents[1]


def message(identifier, text):
    checks = dict.fromkeys(CHECKS, 0.)
    checks.update(relevance=1., certainty=1., goal_congruence=.1)
    return dict(id=identifier,text=text,intent='reflect',appraisal=checks,duration_s=.1)


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tmp.name)/'session'; cls.folder.mkdir()
        with BodyLoop.start(cls.folder/'body.sqlite',max_actions=1) as body, AffectiveAgent(cls.folder/'affect.sqlite') as affect:
            bridge = DialogueBodyBridge.enable(body,affect)
            for i,text in [('a','تمرین تعادل بدن و حرکت'), ('b','حافظهٔ كهن ناسورایا'),
                           ('c','تعادل در بدن آزمایشی')]:
                bridge.receive(message(i,text))
        cls.archive=Path(cls.tmp.name)/'history.json'
        cls.pin=history.export_history(cls.folder,cls.archive)['archive_sha256']

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def query(self, text, limit=10):
        return target.search(self.archive,self.pin,text,limit)

    def test_persian_word_search_preserves_original_and_source(self):
        result=self.query('تعادل')
        self.assertEqual({x['message_id'] for x in result['hits']}, {'a','c'})
        hit=next(x for x in result['hits'] if x['message_id']=='a')
        self.assertEqual(hit['message_text'],'تمرین تعادل بدن و حرکت')
        self.assertEqual(hit['message_source'],'conversation://a')
        self.assertTrue(hit['historical_id'].startswith(self.pin+'/'))
        self.assertEqual(hit['appraisal_kind'],'caller_authored_interpretation')
        self.assertEqual(result['body_cycles_executed'],0)
        self.assertEqual(result['learning_updates'],0)

    def test_arabic_variants_and_tashkeel_are_normalized(self):
        self.assertEqual([x['message_id'] for x in self.query('کَهَن')['hits']],['b'])
        self.assertEqual(target.normalize('كيان ۱۲٣'), 'کیان 123')

    def test_zero_width_spacing_and_case(self):
        self.assertEqual(target.normalize('حافظه\u200cخوب'), 'حافظه خوب')
        self.assertEqual(target.normalize('A B'), 'a b')

    def test_multiple_words_are_conjunctive(self):
        self.assertEqual([x['message_id'] for x in self.query('تعادل حرکت')['hits']],['a'])
        self.assertEqual(self.query('تعادل ناسورایا')['hits'],[])

    def test_fts_syntax_is_not_executed(self):
        # OR is an ordinary required word and cannot broaden the query.
        self.assertEqual(self.query('تعادل OR ناسورایا')['hits'],[])
        self.assertEqual({x['message_id'] for x in self.query('"تعادل"')['hits']},{'a','c'})

    def test_result_limit_and_query_bounds(self):
        self.assertEqual(len(self.query('تعادل',1)['hits']),1)
        for q in (' ', 'x '*9, 'x'*257, 'x'*81):
            with self.subTest(q=q), self.assertRaises(ValueError): self.query(q)
        for limit in (0,33,True):
            with self.subTest(limit=limit), self.assertRaises(ValueError): self.query('تعادل',limit)

    def test_bad_pin_does_not_search(self):
        with self.assertRaisesRegex(ValueError,'pinned export'):
            target.search(self.archive,'0'*64,'تعادل')

    def test_no_writes_or_body_calls(self):
        before=self.archive.read_bytes()
        prior={p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        with patch.object(BodyLoop,'step',side_effect=AssertionError('body step')), \
             patch.object(AffectiveAgent,'step',side_effect=AssertionError('affect update')):
            first=self.query('تعادل');second=self.query('تعادل')
        self.assertEqual(first,second)
        self.assertEqual(before,self.archive.read_bytes())
        self.assertEqual(prior,{p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()})

    def test_cold_cli_restart_and_pinned_archive(self):
        def call(pin):
            p=subprocess.run([sys.executable,'-m','nasuraya.history_search','--archive',str(self.archive),
                '--expected-sha256',pin,'--query','تعادل'],cwd=ROOT,env=dict(os.environ),
                text=True,capture_output=True)
            return p,json.loads(p.stdout)
        p,a=call(self.pin);q,b=call(self.pin)
        self.assertEqual(p.returncode,0,p.stderr+p.stdout)
        self.assertEqual(q.returncode,0,q.stderr+q.stdout)
        self.assertEqual(a,b)
        failed,c=call('f'*64)
        self.assertNotEqual(failed.returncode,0)
        self.assertEqual(c['status'],'rejected')

    def test_status_is_not_upgraded(self):
        report=history.load_history(self.archive,self.pin)
        report['records'][0]['status']='unresolved_do_not_execute'
        with patch.object(target,'load_history',return_value=report):
            hit=target.search('unused',self.pin,'حرکت')['hits'][0]
        self.assertEqual(hit['status'],'unresolved_do_not_execute')
        self.assertFalse(hit['native_outcome_recorded'])


if __name__ == '__main__': unittest.main()

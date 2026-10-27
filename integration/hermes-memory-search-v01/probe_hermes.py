"""Exercise actual pinned Hermes SessionDB only on disposable synthetic data."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

PIN = 'bf0203a794a07aac3ff764972ab9087baa4e4f4e'
SCRIPT = r'''
import json,sys
from pathlib import Path
from hermes_state import SessionDB
with SessionDB(db_path=Path(sys.argv[2])) as db:
 if sys.argv[1]=='seed':
  db.create_session('synthetic-001','cli')
  db.append_message('synthetic-001','user','تمرین تعادل ناسورایا در آزمایش ساختگی انجام شد.',message_uid='synthetic-message-1')
  db.append_message('synthetic-001','assistant','این نتیجه فقط یک آزمایش ساختگی است.',message_uid='synthetic-message-2')
  db.append_message('synthetic-001','user','مرحله بعد حرکت پا و چرخش است.',message_uid='synthetic-message-3')
 print(json.dumps({q:[r['id'] for r in db.search_messages(q,source_filter=['cli'])]
      for q in ['تعادل','تعادل AND چرخش','ناسورايا','ناسورایا']},ensure_ascii=False))
'''

def main():
 p=argparse.ArgumentParser();p.add_argument('--hermes-root',required=True,type=Path);p.add_argument('--python',required=True);args=p.parse_args()
 root=args.hermes_root.resolve();sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
 if sha!=PIN: raise ValueError('exact Hermes commit required')
 with tempfile.TemporaryDirectory(prefix='hermes-synthetic-probe-') as tmp:
  tmp=Path(tmp); env={'PATH':os.defpath,'PYTHONPATH':str(root),'HERMES_HOME':str(tmp/'home'),'PYTHONNOUSERSITE':'1'}
  def run(phase):
   p=subprocess.run([args.python,'-c',SCRIPT,phase,str(tmp/'state.sqlite')],cwd=root,env=env,text=True,capture_output=True,check=True)
   return json.loads(p.stdout)
  initial=run('seed');cold=run('reopen')
  if initial!=cold or initial['تعادل']!=[1] or initial['ناسورايا']!=[] or initial['ناسورایا']!=[1] or set(initial['تعادل AND چرخش'])!={1,3}:
   raise AssertionError('unexpected upstream behavior')
  print(json.dumps(dict(schema='nasuraya.hermes-synthetic-probe/1',hermes_commit=PIN,
     initial=initial,cold_restart=cold,match_after_restart=True,
     observation='Hermes relaxed AND to OR on zero matches in this fixture; Arabic yeh differs from Persian yeh.',
     scope='synthetic SQLite only, no model, gateway, real user memory or side effects resumed'),ensure_ascii=False,indent=2))
if __name__=='__main__':main()

import json,sys
from pathlib import Path
repo=Path(sys.argv[1]);sys.path.insert(0,str(repo));sys.path.insert(0,str(repo/'runtimes/tadash_body'))
from synthetic_fixture import prepare_defaults,synthetic_body
prepare_defaults()
from examples.nasuraya_research.body_observer import observe_native_body
from examples.nasuraya_research.adapters import digest
from unified_body_v2 import UnifiedBody
from unittest.mock import patch
rows=[]
shared=json.loads(Path(sys.argv[3]).read_text()) if len(sys.argv)>3 else None
checkpoints=[]
for pressure in (.05,.42,.7,.92):
 body=synthetic_body();before=body.owner.body();body.owner.aux['sleep_pressure']=pressure
 body.owner._record(before,body.owner.body(),'external_input','declared self-efficacy evaluation fixture; no user state reset',0.)
 if shared is not None: body=UnifiedBody.restore(shared[len(rows)])
 before=body.checkpoint(); checkpoints.append(before)
 with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native cycle')):
  result=observe_native_body(body,include_geometry=True,frame_yaw_rad=1.5707963267948966,
     decisions=[dict(correct=True,keep_withdraw='KEEP'),dict(correct=False,keep_withdraw='WITHDRAW')],
     events=[dict(seq=1,event_id='e',run_id='r',type='run_start',payload={})])
 assert before==body.checkpoint()
 rows.append(dict(pressure=pressure,observation=result,result_sha256=digest(result),checkpoint_unchanged=True))
Path(sys.argv[2]).write_text(json.dumps(rows,indent=2)+'\n')

if shared is None: Path(sys.argv[2]+'.checkpoints').write_text(json.dumps(checkpoints)+'\n')

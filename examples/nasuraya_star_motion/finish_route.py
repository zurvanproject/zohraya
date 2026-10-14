"""Bounded continuation of an incomplete, physically valid recorded route.

This is a separate prospective action budget, not an enlarged comparison window.
No failed state is reset or repaired, and native time/stocks/cursors continue.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timedelta
import json
from pathlib import Path
import sys


def run(native_root,source,output):
    sys.path.insert(0,str(Path(native_root).resolve()))
    from unified_body_v2 import UnifiedBody
    from extension_state import attach,checkpoint,restore
    source=Path(source);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    previous=json.loads((source/'performance.json').read_text())
    native=json.loads((source/'body_checkpoint.json').read_text())
    body=UnifiedBody.restore(native)
    if not previous['rows'][-1]['physical_model_valid']:raise ValueError('failed source cannot be resumed as a healthy body')
    controller=dict(star_enabled=True,star_started=previous['rows'][-1]['star_targets_started'],
        star_targets=previous['star_targets'],cursor_semantics='confirmed')
    attach(body,controller);start_native=body.checkpoint();start_cursors=deepcopy(body.owner.physical.star_started)
    clock=datetime.fromisoformat(body.owner.wall_utc)+timedelta(seconds=.5);rows=[];stop=None
    def advance(action,duration):
        nonlocal clock
        t=body.owner.owner.body.state.time_s
        r=body.cycle(event_id=f'star-growth-finish-{len(rows):03d}',at_utc=clock.isoformat(),duration_s=duration,
            requested=action,expected_revision=body.revision,
            external=dict(sensors=dict(vision=dict(value=.25,source_id=f'continued-star-floor-{len(rows)}',sampled_at_s=t,kind='declared_simulated_input'))))
        p=body.owner.physical
        row=dict(index=len(rows),selected=r['owner']['selected_action'],duration_s=duration,
            body_time_s=body.owner.owner.body.state.time_s,minimum=body.owner.body()['minimum_state'],
            physical_model_valid=r['owner']['physical_model_valid'],failure_reason=p.state.failed_reason,
            cursor=deepcopy(p.star_started),feet_m=deepcopy(p.state.feet_m),
            com_m=deepcopy(p.state.com_m),walk_touchdowns=p.state.walk_steps,
            fuel_used_J=sum(x['fuel_used_J'] for x in r['trace']),whole_body_audit=r['whole_body_audit'],
            support_adjustments=getattr(p,'support_adjustments',0))
        rows.append(row);clock+=timedelta(seconds=duration)
        print(json.dumps({k:row[k] for k in ('index','selected','cursor','physical_model_valid')}),flush=True)
        return row
    for _ in range(120):
        p=body.owner.physical
        if all(p.star_started[s]>=len(p.star_targets[s]) for s in ('L','R')):break
        row=advance('walk',.5)
        if not row['physical_model_valid']:stop='support failure';break
    complete=all(body.owner.physical.star_started[s]>=len(body.owner.physical.star_targets[s]) for s in ('L','R'))
    body.owner.physical.star_enabled=False
    if complete and stop is None:
        for _ in range(4):
            row=advance('slow_breath',.5)
            if not row['physical_model_valid']:stop='closure support failure';break
    final=checkpoint(body);assert checkpoint(restore(final))==final
    result=dict(schema='nasuraya-star-route-continuation/1',source_native_sha256=native['sha256'],
        starting_cursors=start_cursors,final_cursors=deepcopy(body.owner.physical.star_started),
        extra_budget_seconds=60.,closure_budget_seconds=2.,actual_seconds=sum(x['duration_s'] for x in rows),
        no_state_reset=start_native==native,complete=complete,stop_reason=stop,rows=rows,
        final_minimum=body.owner.body()['minimum_state'],final_revision=body.revision,
        final_checkpoint_sha256=final['sha256'],cold_restore_exact=True,
        scope='prospective continuation; not part of the original 41-second comparison')
    (output/'continuation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (output/'coordinated_checkpoint.json').write_text(json.dumps(final,ensure_ascii=False,indent=2)+'\n')
    print('FINAL',json.dumps({k:result[k] for k in ('actual_seconds','complete','stop_reason','final_cursors')}))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--native-root',required=True);p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.native_root,a.source,a.output)

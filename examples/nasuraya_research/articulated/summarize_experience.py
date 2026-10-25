"""Render measured evidence; never run physics or alter a selected policy."""
import argparse,gzip,json,math
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def summarize(folder):
    folder=Path(folder)
    plan=json.loads((folder/'protocol.json').read_text())
    policy=json.loads((folder/'policy.json').read_text())
    evaluation=json.loads((folder/'evaluation.json').read_text())
    secondary_path=folder/'secondary-evaluation.json'
    secondary=json.loads(secondary_path.read_text()) if secondary_path.exists() else None
    context_path=folder/'context-evaluation.json'
    context=json.loads(context_path.read_text()) if context_path.exists() else None
    training=[]
    for bias in plan['candidates_m']:
        training.append([json.loads((folder/f'train-{case["id"]}-{bias:+.3f}.json').read_text())['result']
                         for case in plan['training']])
    fig=plt.figure(figsize=(13.6,10.4),layout='constrained')
    grid=fig.add_gridspec(2,2,height_ratios=[1,1.1])
    ax=fig.add_subplot(grid[0,0])
    values=np.array([[r['tilt_rms_deg'] for r in rows] for rows in training]).T
    image=ax.imshow(values,cmap='YlOrRd',aspect='auto',vmin=0,vmax=max(1.,np.percentile(values,70)))
    for i,rows in enumerate(training):
        for j,r in enumerate(rows):
            passed=r['walk_pass'] and r['final_max_generalized_speed']<.05
            ax.text(i,j,f'{r["tilt_rms_deg"]:.3f}'+('' if passed else '\nFAIL'),ha='center',va='center',fontsize=10,
                    color='white' if values[j,i]>.9 else '#15283b')
    ax.set_xticks(range(len(training)),[f'{1000*b:+.0f}' for b in plan['candidates_m']])
    ax.set_yticks(range(3),['Nominal','Lower friction','Lateral push'])
    ax.set_xlabel('COM target offset (mm); 0 = no calibration')
    ax.set_title('A  Training: measured RMS pelvis tilt (degrees)',loc='left',fontweight='bold')
    fig.colorbar(image,ax=ax,shrink=.75,label='RMS degrees',extend='max')
    ax=fig.add_subplot(grid[0,1]);pairs=evaluation['pairs'];y=np.arange(len(pairs));w=.23
    names=['Friction 0.35','Friction 0.80','Longer stride','Rightward push','Combined challenge','Half timestep']
    ax.barh(y-w,[p['baseline_rms'] for p in pairs],w,label='No calibration',color='#506680')
    ax.barh(y,[p['candidate_rms'] for p in pairs],w,label='Fixed training selection',color='#d7853b')
    if context:
        lookup={r['case']:r for r in context['pairs']}
        ax.barh(y+w,[lookup[p['case']]['candidate_rms'] for p in pairs],w,
                label='Friction-context memory',color='#168678')
    ax.set_yticks(y,names);ax.invert_yaxis();ax.set_xlabel('RMS pelvis tilt (degrees; lower is better)')
    ax.set_title('B  Six held-out scenarios; no retuning',loc='left',fontweight='bold');ax.legend(fontsize=9)
    ax=fig.add_subplot(grid[1,0]);bias=policy['selected_bias_m']
    for offset,label,color in [(0.,'No calibration','#506680'),(bias,f'Training-selected {bias*1000:+.0f} mm','#d7853b')]:
        path=folder/f'holdout-holdout_push_right-{offset:+.3f}-trace.json.gz'
        data=json.loads(gzip.decompress(path.read_bytes()))
        ax.plot([r['t'] for r in data],[r['tilt_deg'] for r in data],label=label,color=color,lw=1.7)
    ax.set_title('C  Preselected unseen push case: recorded trajectory',loc='left',fontweight='bold')
    ax.set_xlabel('Simulation time (s)');ax.set_ylabel('Pelvis tilt (degrees)');ax.legend(fontsize=9)
    ax.grid(alpha=.2)
    ax=fig.add_subplot(grid[1,1])
    if secondary:
        rows=[p for p in secondary['pairs'] if p['requested_steps']==2]
        good=[p for p in rows if p['baseline_pass'] and p['candidate_pass']]
        ax.scatter([p['baseline_rms'] for p in good],[p['candidate_rms'] for p in good],s=35,color='#d7853b',alpha=.75,label='Fixed selection')
        if context:
            cg=[p for p in context['pairs'] if p['case'].startswith('new_context_')
                and p['baseline_pass'] and p['candidate_pass']]
            ax.scatter([p['baseline_rms'] for p in cg],[p['candidate_rms'] for p in cg],
                       s=35,marker='x',color='#168678',label='Context memory')
        high=max([max(p['baseline_rms'],p['candidate_rms']) for p in good],default=1.)*1.1
        ax.plot([0,high],[0,high],ls='--',color='#7e8894',label='Equal error')
        ax.set_xlim(0,high);ax.set_ylim(0,high);ax.set_xlabel('No-calibration RMS tilt (degrees)')
        ax.set_ylabel('Selected-policy RMS tilt (degrees)')
        ax.set_title('D  20 further fixed synthetic contexts',loc='left',fontweight='bold')
        bp=sum(p['baseline_pass'] for p in rows);cp=sum(p['candidate_pass'] for p in rows)
        ax.text(.04,.95,f'Accepted + settled: base {bp}/20; fixed {cp}/20\n'
                f'{len(good)} paired accepted + settled cases plotted',transform=ax.transAxes,va='top',fontsize=9)
        ax.legend(loc='lower right',fontsize=8)
    else:
        ax.axis('off');ax.text(.1,.8,'Secondary transfer results are incomplete.\nNo secondary benefit claimed.',va='top')
    status=f'Fixed +6 mm: {"PASS" if evaluation["predeclared_success"] else "criterion NOT MET"}'
    if context:status+=f'   |   Secondary context hypothesis: {"PASS" if context["secondary_hypothesis_pass"] else "criterion NOT MET"}'
    fig.suptitle(f'Nasuraya | measured balance on the same 78 kg / 1.70 m proxy\n'+status,fontsize=15,fontweight='bold')
    fig.supxlabel('Deterministic MuJoCo simulation • unchanged body, timing, motor limits and guards • offline selection, not neural training',fontsize=10)
    fig.savefig(folder/'comparison.png',dpi=170);fig.savefig(folder/'comparison.svg');plt.close(fig)
    audit=[]
    for file in sorted(folder.glob('*-trace.json.gz')):
        record_path=file.with_name(file.name.replace('-trace.json.gz','.json'))
        if not record_path.exists():continue
        record=json.loads(record_path.read_text());r=record['result']
        if not r['walk_pass']:continue
        tr=json.loads(gzip.decompress(file.read_bytes()))
        times=np.array([0]+[a['t'] for a in tr]+[r['measured_seconds']])
        tilts=np.array([tr[0]['tilt_deg']]+[a['tilt_deg'] for a in tr]+[tr[-1]['tilt_deg']])
        sampled=math.sqrt(float(np.trapezoid(tilts**2,times))/r['measured_seconds'])
        audit.append(dict(file=record_path.name,reported_rms=r['tilt_rms_deg'],sampled_50ms_rms=sampled,
                          absolute_disagreement_deg=abs(sampled-r['tilt_rms_deg'])))
    (folder/'sampled-metric-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    return dict(primary=evaluation,secondary=secondary,largest_sampled_disagreement_deg=max(
        (r['absolute_disagreement_deg'] for r in audit),default=None))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
    result=summarize(a.evidence)
    print(json.dumps({'largest_sampled_disagreement_deg':result['largest_sampled_disagreement_deg']}))

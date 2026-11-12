"""Machine-readable current contract; implementation is separate from execution."""
from pathlib import Path
from examples.dios_nous.unified import body
from examples.nasuraya_body_loop.__main__ import verified_sources
from .profile import current,CURRENT,LEGACY
from .noise_study import load_model
from .adapters import ROOT


def report():
    manifest=verified_sources();inventory=body.inventory();profile=current()
    default=[r for r in inventory['models'] if r.get('default_native')]
    if len(default)!=1 or default[0]['id']!=CURRENT:raise ValueError('one current native model required')
    frozen,model,sha=load_model(ROOT/'docs/evidence/nasuraya-stage3-v01/frozen-model.json')
    return {'schema':'nasuraya.integration-audit/1','current_body':profile,
        'current_entrypoint':'python -m examples.nasuraya_runtime',
        'native_defaults':{'body':CURRENT,'decoder':'legacy','reconsideration':False},
        'historical_entries':{'runtimes/tadash_body':'immutable source archive used for reproducible derivation',
            'python -m examples.nasuraya_body_loop':'historical standalone research interface; not current morphology',
            LEGACY:'available in current interface only with --legacy-body'},
        'noise_candidate':{'model_sha':model.fingerprint(),'frozen_sha':sha,
            'validation_accepted':frozen['validation_accepted'],'promoted_to_default':False,
            'explicit_option':'--decoder noise_candidate'},
        'implemented_connections':{
            'body_to_decision':'native owned export -> workload -> Rolyel -> native final veto',
            'decision_to_memory':'matched actual local receipt -> action-scoped CognitiveSession',
            'memory_to_decision':'DIOS dissent and bounded evidence-based reconsideration',
            'goal_continuity':'original AdvisoryGoalPlanner; persistent stop and budget',
            'sensation':'numeric frames -> persistent state and signed trace -> hypothesis and action pressure',
            'visual':'source-pinned text planning; no rendering',
            'genome':'fixed fixture only; no mutation/application to physics',
            'ritual_server_moltbook_desktop':'historical references; no live/authenticated coupling'},
        'historical_native_sources_verified':len(manifest),
        'native_cycles_executed_by_this_audit':0,'external_actions':0,
        'unresolved':['physiological calibration and independent foot/skeletal geometry',
            'noisy/novel detection qualification; rejected candidate retained',
            'explicit migration of old sessions; bounded replay cost',
            'live authenticated external ingress and provider execution'],
        'subjective_experience_established':False}


if __name__=='__main__':
    import argparse,json
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with args.output.open('x',encoding='utf-8') as file:json.dump(report(),file,indent=2,sort_keys=True)

"""One approved morphology, plus an explicitly derived reduced simulation.

Original recovered sources are immutable historical evidence. Parameter changes
are applied only to a verified disposable copy, before importing any native code.
This engineering scaling is not empirical whole-body physiological calibration.
"""
import hashlib
import json
from pathlib import Path

from examples.tadash_interoception.state import digest

CURRENT = 'tadash_reduced_78kg_v1'
LEGACY = 'tadash_legacy_195kg'
V06 = 'base_v09/tadash_renal_v09/retained_v08/body_v06/'
V08 = 'base_v09/tadash_renal_v09/retained_v08/'
V09 = 'base_v09/tadash_renal_v09/'


def current():
    from examples.dios_nous.unified import body
    manifest, sources = body._verified_sources()
    target = body._literal_assign(sources['tools/fullbody_design_atlas.py'], 'CANONICAL_TARGET')
    result = {'schema': 'nasuraya.current-body/1', 'model_id': CURRENT,
        'morphology': target, 'authority': manifest['files']['tools/fullbody_design_atlas.py'],
        'physics': 'reduced_parameterized_engineering_fixture_not_empirical_calibration',
        'historical_model': LEGACY, 'historical_default_allowed': False,
        'reference_pools': {'water_L': 110 * target['mass_kg']/195,
            'fuel_J': 4000000 * target['mass_kg']/195,
            'reserve_J': 60000 * target['mass_kg']/195,
            'heat_capacity_J_K': target['mass_kg']*3500}}
    result['sha256'] = digest(result)
    return result


def prepare(staging):
    """Transform verified source bytes using explicit, audited dimensional edits."""
    staging = Path(staging); profile = current(); t = profile['morphology']
    from examples.nasuraya_body_loop.__main__ import verified_sources
    for name,sha in verified_sources().items():
        if hashlib.sha256((staging/name).read_bytes()).hexdigest()!=sha:
            raise ValueError('profile derivation requires original verified bytes: '+name)
    mass = t['mass_kg']/195; length = t['ground_to_crown_cm']/250
    tail = t['tail_centerline_cm']/120
    edits = []
    def replace(path, old, new):
        file = staging/path; raw = file.read_bytes(); source = raw.decode('utf-8')
        count = source.count(old)
        if count == 0: raise ValueError('missing declared profile edit: '+path+' '+old)
        changed = source.replace(old, new).encode('utf-8')
        file.write_bytes(changed)
        edits.append({'path': path, 'old': old, 'new': new, 'count': count,
                      'before': hashlib.sha256(raw).hexdigest(), 'after': hashlib.sha256(changed).hexdigest()})
    def scale(path, token, value, factor=mass):
        replace(path, token, repr(value*factor))
    # Every normalization must agree with the single finite ledger.
    for path in ('persistent_embodiment_v1.py','unified_body_v2.py',V06+'body_loop_v06.py',
                 V06+'posture_step.py',V09+'renal_body_v09.py',V09+'renal_physiology_v09.py'):
        source = (staging/path).read_text()
        for old, new in (('110.0',repr(110*mass)), ('110.',repr(110*mass))):
            if old in source:
                replace(path,old,new); source=(staging/path).read_text()
    for path in ('persistent_embodiment_v1.py','unified_body_v2.py',V06+'body_loop_v06.py'):
        replace(path,'4000000.0',repr(4000000*mass))
    replace(V06+'body_loop_v06.py','60000.0',repr(60000*mass))
    replace(V06+'body_loop_v06.py','HEAT_LIMIT_J = 195000.0','HEAT_LIMIT_J = '+repr(195000*mass))
    replace(V08+'interoception_v07.py','195000.',repr(195000*mass))
    for path in ('persistent_embodiment_v1.py','unified_body_v2.py'):
        replace(path,'195.0*3500.0',repr(float(t['mass_kg']))+'*3500.0')
    # Authored extensive quantities scale with mass; time/constants of chemistry do not.
    replace(V06+'body_loop_v06.py','177.0 +',repr(177*mass)+' +')
    replace('unified_body_v2.py','-177.0-', '-'+repr(177*mass)+'-')
    replace('unified_body_v2.py','    requests=sum(demand.values())',
            '    demand={k:v*'+repr(mass)+' for k,v in demand.items()}\n    requests=sum(demand.values())')
    replace(V09+'renal_physiology_v09.py','filtration_reference_L_s: float = .002',
            'filtration_reference_L_s: float = '+repr(.002*mass))
    replace(V09+'renal_physiology_v09.py','basal_sodium_leak_mmol_s: float = .0005',
            'basal_sodium_leak_mmol_s: float = '+repr(.0005*mass))
    for name, value in (('O2_CAPACITY_L',3.),('O2_REFERENCE_L',2.),('DEAD_SPACE_L',.20),
                        ('BASE_VENTILATION_L_MIN',12.1),('BASE_METABOLIC_W',220.),('MAX_VENTILATION_L_MIN',80.)):
        file=staging/(V06+'breath_motion_v06.py')
        old=next(line for line in file.read_text().splitlines() if line.startswith(name+' = '))
        replace(V06+'breath_motion_v06.py',old,name+' = '+repr(value*mass))
    for name,value in (('usable_o2_L',2.),('co2_store_L',.22),('tidal_L',1.1)):
        file=staging/(V06+'breath_motion_v06.py')
        old=next(line for line in file.read_text().splitlines() if line.strip().startswith(name+':'))
        replace(V06+'breath_motion_v06.py',old,'    '+name+': float = '+repr(value*mass))
    for path in (V06+'breath_motion_v06.py','actuated_breath_v1.py'):
        replacements = [('0.30 / max(0.30, g.co2_store_L)',f'{.30*mass!r} / max({.30*mass!r}, g.co2_store_L)'),
            ('g.co2_store_L - 0.25','g.co2_store_L - '+repr(.25*mass)),
            ('0.32 * (target_ve - 12.1)',f'{.32/mass!r} * (target_ve - {12.1*mass!r})'),
            ('min(2.6, target_ve',f'min({2.6*mass!r}, target_ve'),
            ('1.5 + 0.005 * minute_ventilation ** 2',f'{1.5*mass!r} + {.005/mass!r} * minute_ventilation ** 2'),
            ('alveolar_ventilation >= 8.0','alveolar_ventilation >= '+repr(8*mass)),
            ('/ 60.0 * 0.25 *','/ 60.0 * '+repr(.25/mass)+' *')]
        for old,new in replacements:replace(path,old,new)
    for old,new in [('target_ve / 2.6','target_ve / '+repr(2.6*mass)),
                    ('max(1.1, tidal_target)',f'max({1.1*mass!r}, tidal_target)'),
                    ('g.usable_o2_L >= 1.9','g.usable_o2_L >= '+repr(1.9*mass)),
                    ('g.co2_store_L <= .35','g.co2_store_L <= '+repr(.35*mass))]:
        replace('actuated_breath_v1.py',old,new)
    for old,new in [('g.co2_store_L/.60','g.co2_store_L/'+repr(.60*mass)),
                    ('gas.co2_store_L/.60','gas.co2_store_L/'+repr(.60*mass)),
                    ('g.usable_o2_L/2.0','g.usable_o2_L/'+repr(2*mass)),
                    ('g.tidal_L/2.6','g.tidal_L/'+repr(2.6*mass)),
                    ('margin/.10','margin/'+repr(.10*length)),
                    ("'breath_depth':2.6","'breath_depth':"+repr(2.6*mass))]:
        replace('persistent_embodiment_v1.py',old,new)
    # Pose landmarks and levers: lengths scale with crown height; horn tip is explicit.
    for old,value in [('1.42',1.42),('1.80',1.8),('2.39',2.39),('2.06',2.06),('.43',.43)]:
        replace('persistent_embodiment_v1.py',old,repr(value*length))
    replace('persistent_embodiment_v1.py',"sign*.35,y,",'sign*'+repr(.35*length)+',y,')
    replace('persistent_embodiment_v1.py','sign*.15,-.025,.27',
            f'sign*{.15*length!r},{-.025*length!r},{t["ground_to_horn_tip_cm"]/100-2.39*length!r}')
    replace('persistent_embodiment_v1.py','1.2*math.',repr(t['tail_centerline_cm']/100)+'*math.')
    replace('persistent_embodiment_v1.py','self_location=[x,y,1.314]',f'self_location=[x,y,{1.314*length!r}]')
    replace(V06+'posture_step.py',"'L':[.196,0.,0.],'R':[-.196,0.,0.]",
            f"'L':[{.196*length!r},0.,0.],'R':[{- .196*length!r},0.,0.]")
    replace(V06+'posture_step.py','step_length_m: float=.12','step_length_m: float='+repr(.12*length))
    # Preserve dimensionless protective thresholds after resizing the stores.
    # Leaving /2 L here falsely classified the healthy 78 kg fixture as hypoxic.
    for old,new in [('g.usable_o2_L/2.<.78',f'g.usable_o2_L/{2*mass!r}<.78'),
                    ('g.co2_store_L>.6','g.co2_store_L>'+repr(.6*mass)),
                    ('b.fuel_J<40000','b.fuel_J<'+repr(40000*mass)),
                    ('masses=(14.,10.,8.)','masses='+repr(tuple(v*mass for v in (14.,10.,8.)))),
                    ('inertia=(4.,2.,.6)[idx]','inertia='+repr(tuple(v*mass*length**2 for v in (4.,2.,.6)))+'[idx]'),
                    ('(norm(moment)+8.)','(norm(moment)+'+repr(8*mass*length)+')'),
                    ('+2.*rate','+'+repr(2*mass*length**2)+'*rate'),
                    ('[0]+.28','[0]+'+repr(.28*length)),
                    ('[0]-.28','[0]-'+repr(.28*length)),
                    ("point_margin(support['polygon'],cp)<.008","point_margin(support['polygon'],cp)<"+repr(.008*length)),
                    ('margin<-.008','margin<'+repr(-.008*length)),
                    ('])>.018 or norm(s.velocity_m_s)>.03','])>'+repr(.018*length)+' or norm(s.velocity_m_s)>'+repr(.03*length)),
                    ('[:2],.12]','[:2],'+repr(.12*length)+']')]:
        replace(V06+'posture_step.py',old,new)
    for old,new in [('g.co2_store_L > 0.60','g.co2_store_L > '+repr(.60*mass)),
                    ('g.co2_store_L < 0.34','g.co2_store_L < '+repr(.34*mass)),
                    ('40000.0',repr(40000*mass)),('50000.0',repr(50000*mass)),
                    ('/ 100000.0','/ '+repr(100000*mass))]:
        replace(V06+'breath_motion_v06.py',old,new)
    replace('persistent_embodiment_v1.py','gas.co2_store_L>.35','gas.co2_store_L>'+repr(.35*mass))
    replace('persistent_embodiment_v1.py','gas.usable_o2_L<1.9','gas.usable_o2_L<'+repr(1.9*mass))
    replace(V06+'bilateral_sections.py','    return sections',
        '    for section in sections.values():\n'
        '        for key,value in list(section.items()):\n'
        '            if type(value) not in (int,float): continue\n'
        f'            factor = {mass*length!r} if key.endswith("_Nm") else {mass!r} if key.endswith("_N") else {length**3!r} if key.endswith("_m3") else {length**2!r} if key.endswith("_m2") else {length!r} if key.endswith("_m") else 1.0\n'
        '            section[key]=value*factor\n    return sections')
    # Data edits have the same before/after provenance as code edits.
    def data(path, value):
        old=(staging/path).read_text();replace(path,old,json.dumps(value,sort_keys=True,indent=2)+'\n')
    path=V06+'contact_design_v06.json'; design=json.loads((staging/path).read_text())
    design['mass_kg']=float(t['mass_kg'])
    for key in ('com_height_m','hip_height_m','hip_half_width_m','hock_height_m','foot_half_spacing_m',
                'swing_height_m','max_step_length_m','walk_step_length_m'):design[key]*=length
    design['leg_lengths_m']=[v*length for v in design['leg_lengths_m']]
    for patch in design['patches']:
        patch['xy']=[v*length for v in patch['xy']];patch['area_m2']*=length**2
    design['tail_length_m']=t['tail_centerline_cm']/100
    design['tail_mass_kg']*=mass;design['tail_inertia_kg_m2']*=mass*tail**2
    design['tail_torque_limit_Nm']*=mass*tail
    design['source']='approved current morphology; explicitly scaled reduced point-contact fixture'
    design['contact_area_note']='scaled historical patch areas; independent anatomical foot geometry unvalidated'
    data(path,design)
    path=V06+'hydraulic_table_v03.json'; table=json.loads((staging/path).read_text())
    for row in table.values():
        for key in ('flow_L_min','pump_extra_metabolic_W','node_balance_error_L_min'):row[key]*=mass
    data(path,table)
    path='phenotype_v1.json'; phenotype=json.loads((staging/path).read_text())
    phenotype['adult_scale']={'status':'current_reduced_engineering_profile',**t,
                             'mass_target_kg':t['mass_kg'],'reference_pools':profile['reference_pools']}
    data(path,phenotype)
    path='anatomy_systems_v01.json'; anatomy=json.loads((staging/path).read_text())
    anatomy['baseline_contract']['adult_scale']=phenotype['adult_scale']
    data(path,anatomy)
    result={'profile':profile,'edits':edits,'contact_design':design,
            'remaining_assumptions':['inherited controller gains and neural/affect parameters',
                'point contacts and scaled lever ceilings, not an independently measured skeleton',
                'hydraulic pressure proxies retained; no new vascular geometry solution',
                'linear extensive scaling, not physiological allometry or empirical calibration']}
    result['sha256']=digest(result)
    return result

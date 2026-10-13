"""Circular envelope budgets and one-joint lever examples; hypothetical material.
Area packing alone is not a complete muscle-volume or external contour proof.
"""
import math
def section_models():
    out=[]
    for i,fa,r,area,belly,fiber,moment,load,tendon,boneZ,joint in [
      ('elbow','خم‌کنندهٔ آرنج',.065,.0080,.27,.10,.035,.30,.00045,2.0e-5,320),
      ('knee','بازکنندهٔ زانو',.10,.017,.45,.14,.050,.42,.00085,4.0e-5,700),
      ('ankle','ساق و آشیل',.075,.0105,.29,.10,.060,.20,.00075,2.5e-5,600),
      ('tail','پایهٔ دم',.075,.0085,.22,.08,.040,.35,.00055,2.5e-5,450)]:
        outer=math.pi*r*r;reserved=outer*.26;free=outer-reserved
        pcsa=area*belly/fiber
        stress=.40e6;activation=.95;pennation=math.cos(math.radians(20))
        muscle=pcsa*stress*activation*pennation
        tendon_capacity=tendon*20e6 # allowable after assumed margin; not observed tissue
        bone_moment=boneZ*20e6
        capacity_moment=min(muscle*moment,tendon_capacity*moment,bone_moment,joint)
        reference_pcsa=pcsa/(250/175)**2
        reference_force=reference_pcsa*.20e6*.80*pennation
        out.append({'id':i,'name_fa':fa,'outer_radius_m':r,'envelope_area_m2':outer,'reserved_bone_vessel_nerve_fascia_area_m2':reserved,'allocated_anatomical_muscle_area_m2':area,'unallocated_area_m2':free-area,'allocated_fraction':(area+reserved)/outer,'muscle_belly_length_m':belly,'fiber_length_m':fiber,'PCSA_m2':pcsa,'pennation_deg':20,'assumed_specific_stress_Pa':stress,'activation':activation,'muscle_force_N':muscle,'assumed_tendon_area_m2':tendon,'tendon_allowable_force_N':tendon_capacity,'bone_section_modulus_m3':boneZ,'bone_allowable_moment_Nm':bone_moment,'joint_allowable_moment_Nm':joint,'muscle_moment_arm_m':moment,'external_load_arm_m':load,'allowable_moment_Nm':capacity_moment,'external_force_ceiling_N':capacity_moment/load,'reference_external_force_N':reference_force*moment/load,'force_ratio_to_fixture_reference':capacity_moment/(reference_force*moment),'allocated_muscle_volume_m3':area*belly,'status':'assumed material and sectional geometry, no verified tissue or whole body lift'})
    return out

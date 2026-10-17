"""An authored planar pad hypothesis, independently checked before sandbox use.

This is four triangulated contact islands, not a whole foot or tissue mesh.
Ellipse shapes are underdetermined by native patch areas and are assumptions.
The native centre-contact solver remains conservative and unchanged.
"""
from copy import deepcopy
from itertools import combinations
import json
import math

from .chromosomes import digest
from .traits import body_sources, express

SCHEMA = 'nasuraya.foot-contact-hypothesis/0.1'
MODES = ('affine', 'area_only', 'centres_only', 'descriptor_only')
IDS = ('ball', 'toe_1', 'toe_2', 'toe_3')
SEGMENTS = 256


def cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def integrate(patch):
    vertices = patch['vertices_m']
    area, cx, cy = 0., 0., 0.
    for face in patch['triangles']:
        a, b, c = [vertices[i] for i in face]
        signed = cross(a, b, c) / 2.
        if signed <= 0:
            raise ValueError('degenerate or inverted mesh face')
        area += signed
        cx += signed * (a[0]+b[0]+c[0]) / 3.
        cy += signed * (a[1]+b[1]+c[1]) / 3.
    return area, [cx / area, cy / area]


def disjoint(a, b):
    """Separating-axis check for convex pad polygons (touching is rejected)."""
    for polygon in (a, b):
        for p, q in zip(polygon, polygon[1:] + polygon[:1]):
            axis = [-(q[1]-p[1]), q[0]-p[0]]
            aa = [v[0]*axis[0] + v[1]*axis[1] for v in a]
            bb = [v[0]*axis[0] + v[1]*axis[1] for v in b]
            if max(aa) < min(bb) - 1e-14 or max(bb) < min(aa) - 1e-14:
                return True
    return False


def build_mesh(length_scale=1., width_scale=1., *, segments=SEGMENTS):
    for value in (length_scale, width_scale):
        if type(value) not in (float, int) or not 1. <= value <= 1.02:
            raise ValueError('foot scales outside authored exploration bounds')
    if abs(length_scale-width_scale) > .010000000001:
        raise ValueError('incompatible foot proportions')
    if type(segments) is not int or not 64 <= segments <= 512:
        raise ValueError('mesh resolution must be an integer from 64 to 512')
    phenotype, design = body_sources()
    feet = phenotype['adult_scale']['feet']
    patches = []
    for row in design['patches']:
        # The forepad horizontal semi-axis is authored, not image-derived.
        # Circular toe pads and an elliptical forepad reproduce source areas.
        rx = .12 if row['id'] == 'ball' else math.sqrt(row['area_m2'] / math.pi)
        ry = row['area_m2'] / (math.pi * rx)
        centre = [row['xy'][0]*width_scale, row['xy'][1]*length_scale, 0.]
        rx *= width_scale
        ry *= length_scale
        vertices = [centre] + [[centre[0] + rx*math.cos(2*math.pi*i/segments),
                                centre[1] + ry*math.sin(2*math.pi*i/segments), 0.]
                               for i in range(segments)]
        patches.append(dict(id=row['id'], centre_m=centre, semi_axes_m=[rx, ry],
                            analytic_area_m2=row['area_m2']*width_scale*length_scale,
                            vertices_m=vertices,
                            triangles=[[0, i+1, (i+1) % segments + 1] for i in range(segments)]))
    return dict(schema=SCHEMA, evidence='authored planar contact hypothesis; no measured surface',
                scales=dict(length=length_scale, width=width_scale), segments=segments,
                envelope_m=dict(length=feet['length_cm']/100*length_scale,
                                width=feet['spread_width_cm']/100*width_scale,
                                origin='foot anchor; symmetric rectangular design envelope'),
                patches=patches, heel_contact=False, toe_count=3,
                deformable_tissue=False, whole_foot_mesh=False)


def check_mesh(mesh):
    if mesh['schema'] != SCHEMA or [p['id'] for p in mesh['patches']] != list(IDS):
        raise ValueError('invalid mesh schema or pad identities')
    if (mesh['toe_count'] != 3 or mesh['heel_contact'] is not False or
            mesh['deformable_tissue'] is not False or mesh['whole_foot_mesh'] is not False):
        raise ValueError('contact hypothesis may not grant anatomy or new contacts')
    n = mesh['segments']
    if type(n) is not int or not 64 <= n <= 512:
        raise ValueError('invalid mesh resolution')
    expected_faces = [[0, i+1, (i+1) % n + 1] for i in range(n)]
    relative_error, centroid_error, total = 0., 0., 0.
    for patch in mesh['patches']:
        if len(patch['vertices_m']) != n+1 or patch['triangles'] != expected_faces:
            raise ValueError('contact patch must be a closed triangular fan')
        for point in patch['vertices_m']:
            if (type(point) is not list or len(point) != 3 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
                raise ValueError('invalid mesh coordinate')
            if point[2] != 0:
                raise ValueError('contact mesh must be planar')
            if (abs(point[0]) > mesh['envelope_m']['width']/2 + 1e-12 or
                    abs(point[1]) > mesh['envelope_m']['length']/2 + 1e-12):
                raise ValueError('pad is outside the declared external envelope')
        area, centre = integrate(patch)
        relative_error = max(relative_error, abs(area/patch['analytic_area_m2'] - 1.))
        centroid_error = max(centroid_error, math.dist(centre, patch['centre_m'][:2]))
        total += area
    for a, b in combinations(mesh['patches'], 2):
        if not disjoint(a['vertices_m'][1:], b['vertices_m'][1:]):
            raise ValueError('contact pad polygons overlap')
    discretization = 1. - n*math.sin(2*math.pi/n)/(2*math.pi)
    if relative_error > discretization + 1e-12 or centroid_error > 1e-12:
        raise ValueError('mesh area or centroid does not match the declared ellipse')
    return dict(patches=4, toes=3, triangles=4*n, nonoverlapping=True, inside_envelope=True,
                integrated_area_each_foot_cm2=total*1e4,
                analytic_area_each_foot_cm2=sum(p['analytic_area_m2'] for p in mesh['patches'])*1e4,
                maximum_relative_area_error=relative_error, centroid_error_m=centroid_error,
                geometric_checks_passed=True, anatomical_validation=False)


def compile_foot(genotype, mode='affine'):
    if mode not in MODES:
        raise ValueError('unknown contact mapping mode')
    phenotype = express(genotype)
    original, native = body_sources()
    if phenotype['compatibility']['copy_deviation']:
        raise ValueError('dosage changes do not authorize a foot experiment')
    if phenotype['structural_proposal']['tail_length_cm'] != phenotype['native_baseline']['tail_length_cm']:
        raise ValueError('foot experiment holds the tail fixed')
    proposed = phenotype['structural_proposal']
    feet = original['adult_scale']['feet']
    sy = proposed['foot_length_cm'] / feet['length_cm']
    sx = proposed['foot_width_cm'] / feet['spread_width_cm']
    mesh = build_mesh(sy, sx)
    geometry = check_mesh(mesh)
    design = deepcopy(native)
    for patch in design['patches']:
        if mode in ('affine', 'centres_only'):
            patch['xy'] = [patch['xy'][0]*sx, patch['xy'][1]*sy]
        if mode in ('affine', 'area_only'):
            # Exact continuum Jacobian, checked independently against mesh integration.
            patch['area_m2'] *= sx*sy
    return dict(schema=SCHEMA, genotype=deepcopy(genotype), mode=mode,
                status='conditional_sandbox_hypothesis', native_apply_allowed=False,
                mesh=mesh, mesh_sha256=digest(mesh), geometry=geometry, design=design,
                design_sha256=digest(design), original_design_sha256=digest(native),
                interpretation=('affine pad hypothesis' if mode == 'affine' else
                                'diagnostic ablation; not a complete geometric proposal'),
                exclusions=['whole-foot shape', 'soft tissue', 'ground adaptation', 'friction law changes',
                            'pressure-dependent loaded area', 'collision clearance', 'strength increase'],
                external_contact_target_cm2=feet['contact_area_each_cm2'])


def validate_plan(plan):
    # Recompile everything from genotype and the named hypothesis; no arbitrary
    # fixture, pressure limit, new patch or fake mesh can enter the worker.
    if plan != compile_foot(plan['genotype'], plan['mode']):
        raise ValueError('foot plan does not match genotype, mesh, source and mapping')


def write_svg(baseline, proposed, path):
    """Exact vector diagram of the planar hypothesis; intentionally no anatomy."""
    panels = []
    for x0, plan, title in ((210, baseline, 'Baseline'), (610, proposed, '+2% length and width')):
        mesh = plan['mesh']
        scale, y0 = 620, 240
        width = mesh['envelope_m']['width']*scale
        height = mesh['envelope_m']['length']*scale
        panels.append(f'<text x="{x0}" y="58" text-anchor="middle" font-size="18">{title}</text>')
        panels.append(f'<rect x="{x0-width/2}" y="{y0-height/2}" width="{width}" height="{height}" fill="none" stroke="#8ca1b4" stroke-dasharray="5 5"/>')
        for patch in mesh['patches']:
            pts = ' '.join(f'{x0+p[0]*scale:.3f},{y0-p[1]*scale:.3f}' for p in patch['vertices_m'][1:])
            panels.append(f'<polygon points="{pts}" fill="#52b6ad" fill-opacity=".5" stroke="#087d75"/>')
            cx, cy = patch['centre_m'][:2]
            panels.append(f'<circle cx="{x0+cx*scale}" cy="{y0-cy*scale}" r="3" fill="#9b3527"/>')
        area = plan['geometry']['analytic_area_each_foot_cm2']
        panels.append(f'<text x="{x0}" y="435" text-anchor="middle" font-size="16">Loaded pad area: {area:.2f} cm²</text>')
    text = ('<svg xmlns="http://www.w3.org/2000/svg" width="820" height="510" viewBox="0 0 820 510">'
            '<rect width="820" height="510" fill="#f6f8fa"/>'
            '<g font-family="sans-serif" fill="#203444">'
            '<text x="410" y="28" text-anchor="middle" font-size="17">Authored planar contact hypothesis - same scale</text>'
            + ''.join(panels) +
            '<text x="410" y="473" text-anchor="middle" font-size="14">Dots: native contact centres. Dashed box: external design envelope.</text>'
            '<text x="410" y="495" text-anchor="middle" font-size="14">Four contact islands; no heel contact, tissue model or whole-foot anatomy.</text></g></svg>')
    path.write_text(text)

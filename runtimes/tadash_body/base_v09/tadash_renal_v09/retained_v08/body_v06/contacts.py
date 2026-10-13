"""Pressure-constrained centre-contact statics, with explicit feasible loads.

Three toe centres and one forefoot pad per leg, retained from the old design.
The raised hock is never a contact. The polygon is conservative: finite patch
shapes do not expand the allowed CoP beyond these four centres.
"""
from functools import lru_cache
from itertools import product
import math

EPS = 1e-10

def cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])

def norm(v):
    return math.sqrt(sum(x*x for x in v))

def hull(points):
    """Each point is (x,y,normal-weight-vector); preserve a load witness."""
    unique = {}
    for p in points:
        unique[(round(p[0], 12), round(p[1], 12))] = p
    pts = sorted(unique.values(), key=lambda p:(p[0],p[1]))
    if len(pts) <= 2:
        return pts
    lo, hi = [], []
    for seq, acc in ((pts,lo),(reversed(pts),hi)):
        for p in seq:
            while len(acc)>1 and cross(acc[-2],acc[-1],p) <= EPS:
                acc.pop()
            acc.append(p)
    return lo[:-1]+hi[:-1]

@lru_cache(maxsize=64)
def bounded_simplex_vertices(caps):
    """Vertices of sum(w)=1, 0<=w_i<=cap_i, not an unconstrained hull."""
    n=len(caps); out=[]
    for free in range(n):
        others=[i for i in range(n) if i!=free]
        for bits in product((0,1), repeat=n-1):
            w=[0.]*n
            for i,b in zip(others,bits):
                w[i]=caps[i]*b
            w[free]=1.-sum(w)
            if -EPS <= w[free] <= caps[free]+EPS:
                w[free]=min(caps[free],max(0.,w[free]))
                out.append(tuple(w))
    return out

def solve3(a,b):
    a=[list(r)+[v] for r,v in zip(a,b)]
    for col in range(3):
        pivot=max(range(col,3),key=lambda r:abs(a[r][col]))
        if abs(a[pivot][col])<1e-14:
            return None
        a[col],a[pivot]=a[pivot],a[col]
        scale=a[col][col]; a[col]=[v/scale for v in a[col]]
        for r in range(3):
            if r!=col:
                scale=a[r][col]; a[r]=[v-scale*u for v,u in zip(a[r],a[col])]
    return [a[r][3] for r in range(3)]

def preferred_weights(patches,caps,target):
    """Bounded weighted least squares; geometric witnesses are the fallback."""
    n=len(patches); areas=[p['area_m2'] for p in patches]
    # Half of each foot's nominal normal load on pad, half on the three toes.
    priors=[]
    sides=set(p['side'] for p in patches)
    for p in patches:
        same=[q for q in patches if q['side']==p['side']]
        toe_area=sum(q['area_m2'] for q in same if q['local_id']!='ball')
        toe_share=.5 if any(q['local_id']=='ball' for q in same) else 1.
        prior=(1.-toe_share if p['local_id']=='ball' else
               toe_share*p['area_m2']/max(1e-12,toe_area))
        priors.append(prior/len(sides))
    aa=[[1.,p['xy'][0],p['xy'][1]] for p in patches]
    goal=[1.,target[0],target[1]]; fixed={}
    for _ in range(n+1):
        free=[i for i in range(n) if i not in fixed]
        residual=[goal[k]-sum(aa[i][k]*v for i,v in fixed.items())
                  -sum(aa[i][k]*priors[i] for i in free) for k in range(3)]
        matrix=[[sum(areas[i]*aa[i][j]*aa[i][k] for i in free)
                 for k in range(3)] for j in range(3)]
        lam=solve3(matrix,residual)
        if lam is None:
            return None
        w=[fixed.get(i, priors[i]+areas[i]*sum(aa[i][k]*lam[k] for k in range(3)))
           for i in range(n)]
        bad=[i for i in free if w[i]<-EPS or w[i]>caps[i]+EPS]
        if not bad:
            return [min(caps[i],max(0.,v)) for i,v in enumerate(w)]
        worst=max(bad,key=lambda i:max(-w[i],w[i]-caps[i]))
        fixed[worst]=0. if w[worst]<0 else caps[worst]
    return None

def point_margin(poly,p):
    if len(poly)<3:
        return -1.
    inside=all(cross(a,b,p)>=-EPS for a,b in zip(poly,poly[1:]+poly[:1]))
    d=math.inf
    for a,b in zip(poly,poly[1:]+poly[:1]):
        e=[b[k]-a[k] for k in range(2)]; ee=sum(v*v for v in e)
        t=max(0.,min(1.,sum((p[k]-a[k])*e[k] for k in range(2))/max(EPS,ee)))
        d=min(d,norm([p[k]-a[k]-t*e[k] for k in range(2)]))
    return d if inside else -d

def project(poly,p):
    if not poly:
        return None, None
    if len(poly)>=3 and point_margin(poly,p)>=-EPS:
        root=poly[0]
        for a,b in zip(poly[1:-1],poly[2:]):
            denom=cross(root,a,b)
            if abs(denom)<EPS:
                continue
            u=cross(p,a,b)/denom; v=cross(root,p,b)/denom; w=1.-u-v
            if min(u,v,w)>=-1e-8:
                return list(p), [u*x+v*y+w*z for x,y,z in zip(root[2],a[2],b[2])]
    best=None
    for a,b in zip(poly,poly[1:]+poly[:1]):
        e=[b[k]-a[k] for k in range(2)]; ee=sum(v*v for v in e)
        t=max(0.,min(1.,sum((p[k]-a[k])*e[k] for k in range(2))/max(EPS,ee)))
        q=[a[k]+t*e[k] for k in range(2)]; d=norm([p[k]-q[k] for k in range(2)])
        if best is None or d<best[0]:
            best=(d,q,[(1.-t)*u+t*v for u,v in zip(a[2],b[2])])
    return best[1],best[2]

class ContactModel:
    def __init__(self,design):
        self.design=design

    def patches(self,feet,active_sides,inactive=None):
        inactive=inactive or {}; out=[]
        for side in ('L','R'):
            if side not in active_sides:
                continue
            for row in self.design['patches']:
                if row['id'] in inactive.get(side,[]):
                    continue
                local=row['xy']; foot=feet[side]
                # Mirror toe numbering while retaining the same foot geometry.
                x=local[0] if side=='L' else -local[0]
                out.append({'id':side+'_'+row['id'], 'side':side,
                            'local_id':row['id'],'xy':[foot[0]+x,foot[1]+local[1]],
                            'area_m2':row['area_m2']})
        return out

    def region(self,patches,normal_N):
        if normal_N<=0 or not patches:
            return [],[]
        caps=tuple(min(1.,p['area_m2']*self.design['pressure_ceiling_kpa']*1000./normal_N)
                   for p in patches)
        vertices=bounded_simplex_vertices(caps)
        pts=[(sum(w*p['xy'][0] for w,p in zip(weights,patches)),
              sum(w*p['xy'][1] for w,p in zip(weights,patches)), weights)
             for weights in vertices]
        return hull(pts),list(caps)

    def solve(self,feet,active_sides,desired_cop,normal_N,inactive=None):
        patches=self.patches(feet,active_sides,inactive)
        poly,caps=self.region(patches,normal_N)
        cop,weights=project(poly,desired_cop)
        if cop is None:
            return {'feasible':False,'patches':patches,'polygon':[],'cop_m':None,
                    'normal_N':{},'pressure_kpa':{},'total_normal_N':0.}
        preferred=preferred_weights(patches,caps,cop)
        if preferred is not None:
            weights=preferred
        normals={p['id']:normal_N*w for p,w in zip(patches,weights)}
        return {'feasible':True,'patches':patches,
                'polygon':[[p[0],p[1]] for p in poly], 'cop_m':cop,
                'normal_N':normals,
                'pressure_kpa':{p['id']:normals[p['id']]/p['area_m2']/1000. for p in patches},
                'total_normal_N':sum(normals.values()),
                'by_foot_N':{s:sum(normals[p['id']] for p in patches if p['side']==s)
                             for s in ('L','R')},
                'desired_cop_m':list(desired_cop)}

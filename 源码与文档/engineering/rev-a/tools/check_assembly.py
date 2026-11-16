#!/usr/bin/env python3
"""Read saved CAD; check all nominal solids and complete linear key sweeps."""
import sys,json,itertools,time,argparse,hashlib
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from geometry_checks import overlap_volume
from key_cartridge import key_sweep
from curved_keys import curved_key_sweep
R=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--revision',default='04');args=ap.parse_args()
path=R/f'mechanical/AIKEY_REVA_DESIGN{args.revision}.FCStd'
d=A.openDocument(str(path));parts=list(d.Assembly.Group)
invalid=[o.Name for o in parts if not o.Shape.isValid()]
collisions=[];count=0;t=time.monotonic()
for a,b in itertools.combinations(parts,2):
    if not a.Shape.BoundBox.intersect(b.Shape.BoundBox):continue
    print(f'Static pair: {a.Name} / {b.Name}',flush=True)
    volume=overlap_volume(a.Shape,b.Shape);count+=1
    if volume>1e-5:
        hit={'a':a.Name,'b':b.Name,'overlap_mm3':volume};collisions.append(hit);print(json.dumps(hit),flush=True)
    if count%30==0:print(f'Static candidate pairs checked: {count}; elapsed {time.monotonic()-t:.1f}s',flush=True)
static={'candidate_pairs':count,'collisions':collisions}
print('Full static pass finished',flush=True)
sweeps={};frames={}
for name in ('Voice','Side','Left','Right'):
    key=d.getObject(name+'Key');meta=json.loads(key.LocalKeyFrame)
    p=A.Placement(A.Vector(*meta['origin_mm']),A.Rotation(*meta['rotation_xyzw']))
    if 'CapConstruction' in key.PropertiesList:
        s=curved_key_sweep(d,name,meta['inward_hard_stop_mm'])
    else:
        s=key_sweep(name,*meta['outline_mm'],meta['inward_hard_stop_mm']);s.Placement=p.multiply(s.Placement)
    sweeps[name]=s;frames[name]=p
motion=[]
for name,sweep in sweeps.items():
    for other in parts:
        if other.Name==name+'Key':continue
        if other.Name.endswith('Key') and other.Name[:-3] in sweeps:
            other_shape=sweeps[other.Name[:-3]]
        else:other_shape=other.Shape
        if not sweep.BoundBox.intersect(other_shape.BoundBox):continue
        if other.Name==name+'PCBAssembly':
            actuator=Part.makeCylinder(1.01,1.1,A.Vector(0,0,-5.1))
            actuator.Placement=frames[name].multiply(actuator.Placement)
            other_shape=other_shape.cut(actuator)
        vol=overlap_volume(sweep,other_shape)
        if vol>1e-5:motion.append({'key':name,'other':other.Name,'swept_overlap_mm3':vol})
    print(f'Complete linear swept volume checked: {name}',flush=True)
report={'status':'FAIL' if invalid or collisions or motion else 'NOMINAL_STATIC_AND_KEY_SWEEP_PASS',
    'native_file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'parts':len(parts),'invalid':invalid,
    'static':static,'key_sweeps':{'method':'Exact parallel primitive sweeps; curved front caps use native height-field band with underside translated by thickness plus 0.55 mm. Simultaneous key sweeps included.',
       'switch_interface':'Only centered actuator compression cylinder is treated as moving; all guide, fastener, board, shell and other module solids checked',
       'collisions':motion},'scope':'Nominal rigid geometry only. Does not prove printed tolerance, friction, return force, switch overtravel or RF performance.',
    'elapsed_s':time.monotonic()-t}
(R/f'reports/mechanical-design{args.revision}-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
sys.exit(1 if report['status']=='FAIL' else 0)

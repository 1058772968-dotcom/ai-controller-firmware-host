#!/usr/bin/env python3
"""Recheck changed geometry; reuse only byte-identical B-reps from a passed file."""
import sys,json,argparse,hashlib,itertools,time
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from geometry_checks import overlap_volume
from key_cartridge import key_sweep
from curved_keys import curved_key_sweep
R=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--revision',required=True);ap.add_argument('--baseline',required=True);opt=ap.parse_args()
path=R/f'mechanical/AIKEY_REVA_DESIGN{opt.revision}.FCStd';oldpath=R/f'mechanical/AIKEY_REVA_DESIGN{opt.baseline}.FCStd'
priorpath=R/f'reports/mechanical-design{opt.baseline}-validation.json';prior=json.loads(priorpath.read_text())
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if prior['status']!='NOMINAL_STATIC_AND_KEY_SWEEP_PASS' or prior['sha256']!=digest(oldpath):raise RuntimeError('Baseline is not the verified native file')
old=A.openDocument(str(oldpath));d=A.openDocument(str(path));t=time.monotonic()
parts={o.Name:o for o in d.Assembly.Group};previous={o.Name:o for o in old.Assembly.Group}
integrity=[]
for name in ('PalmShell','FingerShellSupported','TopCoverSupported'):
 if name not in parts or name not in previous:raise RuntimeError('Missing primary housing part: '+name)
 before=previous[name].Shape.Volume;after=parts[name].Shape.Volume
 row={'part':name,'baseline_volume_mm3':before,'current_volume_mm3':after,'volume_ratio':after/before}
 integrity.append(row)
 # These revisions add mounts to the same frozen housing. A small number of
 # intentional holes cannot justify losing most of a primary shell. A valid
 # one-solid B-rep and zero collisions alone do not establish completeness.
 if after<.90*before:raise RuntimeError('Unexpected housing material loss; explicit redesign review required: '+str(row))
def fp(shape):return hashlib.sha256(shape.exportBrepToString().encode()).hexdigest()
hashes={n:fp(o.Shape) for n,o in parts.items()};oldhash={n:fp(o.Shape) for n,o in previous.items()}
same={n for n in parts if n in oldhash and hashes[n]==oldhash[n]}
print('Unchanged native B-reps:',len(same),'Changed/new:',sorted(set(parts)-same),flush=True)
invalid=[n for n,o in parts.items() if not o.Shape.isValid()];collisions=[];computed=0;cached=0
additions={};addition_meta={}
for n in set(parts)-same:
 if n in previous:
  print('Exact added material:',n,flush=True)
  added=parts[n].Shape.cut(previous[n].Shape)
 else:added=parts[n].Shape.copy()
 if not added.isNull() and not added.isValid():raise RuntimeError('Invalid added-material difference '+n)
 additions[n]=added
 addition_meta[n]={'volume_mm3':added.Volume,'solids':len(added.Solids),'brep_sha256':fp(added) if not added.isNull() else None}
for (an,a),(bn,b) in itertools.combinations(parts.items(),2):
 if not a.Shape.BoundBox.intersect(b.Shape.BoundBox):continue
 if an in same and bn in same:cached+=1;continue
 # The passed baseline proves oldA intersection oldB is empty. Therefore any
 # new collision lies in ((newA-oldA) intersection newB) or its converse.
 # Compute the exact set differences, not bounding-box/corner samples. Pure
 # removal cannot introduce a new collision. Added/translated parts still
 # receive full counterpart geometry, including containment cases.
 print('Static delta pair:',an,bn,flush=True)
 bound=0.0
 for n,other in ((an,b.Shape),(bn,a.Shape)):
  if n in additions and additions[n].Solids:bound+=overlap_volume(additions[n],other)
 computed+=1
 # The sum is a conservative upper bound (the two regions may overlap).
 # Recompute the original full pair only to report a true union volume on hit.
 v=overlap_volume(a.Shape,b.Shape) if bound>0.0 else 0.0
 if v>1e-5:collisions.append({'a':an,'b':bn,'overlap_mm3':v});print(collisions[-1],flush=True)
def sweeps(doc):
 result={};frames={}
 for name in ('Voice','Side','Left','Right'):
  key=doc.getObject(name+'Key');meta=json.loads(key.LocalKeyFrame);p=A.Placement(A.Vector(*meta['origin_mm']),A.Rotation(*meta['rotation_xyzw']))
  if 'CapConstruction' in key.PropertiesList:s=curved_key_sweep(doc,name,meta['inward_hard_stop_mm'])
  else:s=key_sweep(name,*meta['outline_mm'],meta['inward_hard_stop_mm']);s.Placement=p.multiply(s.Placement)
  result[name]=s;frames[name]=p
 return result,frames
current,frames=sweeps(d);baseline,_=sweeps(old);equal_sweeps={n for n in current if fp(current[n])==fp(baseline[n])}
motion=[];motion_cached=0;motion_computed=0
for name,sweep in current.items():
 for other,obj in parts.items():
  if other==name+'Key':continue
  moving=other.endswith('Key') and other[:-3] in current
  shape=current[other[:-3]] if moving else obj.Shape
  if not sweep.BoundBox.intersect(shape.BoundBox):continue
  unchanged=other[:-3] in equal_sweeps if moving else other in same
  if name in equal_sweeps and unchanged:motion_cached+=1;continue
  if other==name+'PCBAssembly':
   actuator=Part.makeCylinder(1.01,1.1,A.Vector(0,0,-5.1));actuator.Placement=frames[name].multiply(actuator.Placement);shape=shape.cut(actuator)
  print('Motion delta pair:',name,other,flush=True);v=overlap_volume(sweep,shape);motion_computed+=1
  if v>1e-5:motion.append({'key':name,'other':other,'swept_overlap_mm3':v})
report={'status':'FAIL' if invalid or collisions or motion else 'NOMINAL_STATIC_AND_KEY_SWEEP_PASS','native_file':str(path),'sha256':digest(path),'parts':len(parts),'invalid':invalid,
 'housing_material_integrity':integrity,
 'baseline':{'native_file':str(oldpath),'sha256':digest(oldpath),'report':str(priorpath),'report_sha256':digest(priorpath),'status':prior['status']},
 'static':{'candidate_pairs':computed+cached,'computed_pairs':computed,'byte_identical_cached_pairs':cached,'collisions':collisions,'method':'Exact added-material set-difference bound against a collision-free native baseline; full pair recomputed on any positive bound. Pure removals inherit baseline clearance.','added_material':addition_meta},
 'key_sweeps':{'method':'Exact same full-sweep construction as baseline checker. Cached only when both complete B-rep serializations are identical to the already passed native baseline. All changed/new pairs recomputed.','computed_pairs':motion_computed,'byte_identical_cached_pairs':motion_cached,'collisions':motion},
 'changed_or_new_parts':sorted(set(parts)-same),'part_brep_sha256':hashes,'validator_sources':{n:digest(R/'tools'/n) for n in ('check_assembly_delta.py','geometry_checks.py','key_cartridge.py','curved_keys.py')},
 'scope':'Nominal rigid solids and continuous key sweeps; production tolerances, forces, friction, assembly paths, RF and other unfinished structures are not proven.','elapsed_s':time.monotonic()-t}
(R/f'reports/mechanical-design{opt.revision}-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
sys.exit(1 if report['status']=='FAIL' else 0)

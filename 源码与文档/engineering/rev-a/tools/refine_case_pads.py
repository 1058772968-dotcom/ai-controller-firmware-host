from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import box
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
source=R/'mechanical/AIKEY_REVA_DESIGN17_PAD_INTERFERENCE.FCStd';d=A.openDocument(str(source));changed=[]
for side,x in [('L',-18),('R',18)]:
 for suffix,z in [('Lower',-5.65),('Upper',-4.5)]:
  name='LidPad'+side+suffix;s=box(3,3,.15,x=x,y=98,z=z).cut(Part.makeCylinder(.95,5,V(x,98,-7)))
  assert s.isValid() and len(s.Solids)==1;d.getObject(name).Shape=s;changed.append(name)
d.recompute();checks=[]
for n in changed:
 a=d.getObject(n)
 for b in d.Assembly.Group:
  if n==b.Name or not a.Shape.BoundBox.intersect(b.Shape.BoundBox):continue
  v=overlap_volume(a.Shape,b.Shape);checks.append({'a':n,'b':b.Name,'overlap_mm3':v})
out=R/'mechanical/AIKEY_REVA_DESIGN17.FCStd';d.saveAs(str(out));A.closeDocument(d.Name);d=A.openDocument(str(out))
report=json.loads((R/'reports/history/mechanical-design17-pad-interference.json').read_text())
report['local_checks']=[x for x in report['local_checks'] if x['a'] not in changed and x['b'] not in changed]+checks
report['status']='FAIL' if any(x['overlap_mm3']>1e-5 for x in report['local_checks']) else 'CASE_CLOSURE_LOCAL_PASS_FULL_DELTA_PENDING'
report['sha256']=hashlib.sha256(out.read_bytes()).hexdigest();report['pad_refinement']={'size_mm':[3,3,.15],'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'reason':'3.8mm pad lower Y edge extended .25mm beyond the lid-ear pocket. New pads fit inside pocket and ear; same Ø1.9 hole and shaft axis.'}
(R/'reports/mechanical-design17-build.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'])
assert report['status']!='FAIL'

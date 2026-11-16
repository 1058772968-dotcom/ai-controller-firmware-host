#!/usr/bin/env python3
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from curved_keys import curved_key_sweep,curved_guide,key_frame
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];d=A.openDocument(str(R/'mechanical/AIKEY_REVA_DESIGN04.FCStd'))
results=[]
for name in ('Voice','Side'):
    obj=d.getObject(name+'Key');shape=curved_key_sweep(d,name)
    assert shape.isValid() and len(shape.Solids)==1,name
    obj.Shape=shape;obj.addProperty('App::PropertyString','CapConstruction');obj.CapConstruction='curved native envelope band, 0.9 mm along plunger axis; continuous sweep from translated underside'
    for side in ('L','R'):d.getObject(name+'Guide'+side).Shape=curved_guide(d,name,side)
    d.recompute();meta,p=key_frame(obj);normal=p.Rotation.multVec(A.Vector(0,0,1))
    checks=[]
    for displacement in (0,-.25,-.55,-.56,.01):
        shifted=obj.Shape.copy();shifted.translate(normal*displacement)
        overlap=sum(overlap_volume(shifted,d.getObject(name+'Guide'+side).Shape) for side in ('L','R'))
        checks.append({'displacement_mm':displacement,'guide_overlap_mm3':overlap})
        print(name,checks[-1],flush=True)
    if any(x['guide_overlap_mm3']>1e-5 for x in checks[:3]):raise RuntimeError('Premature guide collision: '+name)
    if not all(x['guide_overlap_mm3']>1e-5 for x in checks[3:]):raise RuntimeError('Hard stop or retention not demonstrated: '+name)
    results.append({'key':name,'checks':checks,'valid':obj.Shape.isValid(),'solids':len(obj.Shape.Solids)})
out=R/'mechanical/AIKEY_REVA_DESIGN05.FCStd';d.recompute();d.saveAs(str(out));A.closeDocument(d.Name);d=A.openDocument(str(out))
invalid=[o.Name for o in d.Assembly.Group if not o.Shape.isValid()]
if invalid:raise RuntimeError('Reopened invalid objects: '+str(invalid))
report={'status':'CURVED_CAP_LOCAL_STOP_PASS_FULL_ASSEMBLY_PENDING','native_file':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'keys':results,
 'construction':'Native shell band translated along each central plunger normal; fixed center coordinates and actuator interface retained',
 'remaining':['full saved-native static and curved-cap continuous sweep check','native visual inspection','printed friction, force and tolerance']}
(R/'reports/mechanical-design05-build.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)

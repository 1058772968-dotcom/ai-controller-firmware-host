#!/usr/bin/env python3
"""Read actual KiCad STEP components into a separate native assembly review."""
from pathlib import Path
import sys,json,itertools
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
r=Path(__file__).resolve().parents[1];V=A.Vector
d=A.openDocument(str(r/'mechanical/AIKEY_REVA.FCStd'));group=d.getObject('Assembly')
for name in ['MainPCB','ESP32Module','USBBoard','USBConnector','MicrophonePCB','Microphone']:
    obj=d.getObject(name)
    if obj:d.removeObject(obj.Name)
exchanges=[]
def insert(name,board,rotation,offset,notes):
    path=r/'electrical/exchange'/f'{board}.step';shape=Part.Shape();shape.read(str(path))
    assert shape.isValid() and len(shape.Solids)>0
    source=shape.BoundBox;shape.Placement=A.Placement(V(*offset),rotation)
    o=d.addObject('PartDesign::Feature',name);o.Label=name+' (native KiCad exchange)';o.Shape=shape
    o.addProperty('App::PropertyString','Source');o.Source=str(path)
    o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=notes
    group.addObject(o)
    points=[V(0,0,0),V(source.XMax,0,0),V(0,source.YMin,0)]
    mapped=[shape.Placement.multVec(p) for p in points]
    exchanges.append({'object':name,'source':str(path),'solids':len(shape.Solids),'translation_mm':offset,
        'source_fiducials_mm':[list(p) for p in points],'assembly_fiducials_mm':[list(p) for p in mapped],
        'notes':notes})
insert('MainPCBAssembly','aikey_main',A.Rotation(),[-12,98,-8.5],
       '24x42x1 nominal PCB; actual front/back component shapes. Backside clearance review required.')
insert('USBPCBAssembly','aikey_usb',A.Rotation(V(0,0,1),180),[8,2,-.4],
       '16x13x.8 board; front PCB edge is 2 mm inside housing. Connector opens toward -Y; mating face recessed 0.925 mm.')
insert('MicPCBAssembly','aikey_mic',A.Rotation(V(1,0,0),90),[-14.18,106,1.5],
       'PDM body faces inward -Y; PCB bottom-port center aligns x=-10,z=-2. Outer acoustic duct and seal pending.')
d.recompute()
items=[o for o in group.Group if hasattr(o,'Shape') and not o.Shape.isNull()]
collisions=[]
for a,b in itertools.combinations(items,2):
    if not a.Shape.BoundBox.intersect(b.Shape.BoundBox):continue
    overlap=a.Shape.common(b.Shape).Volume
    if overlap>1e-5:collisions.append({'a':a.Name,'b':b.Name,'overlap_mm3':overlap})
out=r/'mechanical/AIKEY_REVA_ECAD_REVIEW.FCStd';d.saveAs(str(out))
A.closeDocument(d.Name)
d=A.openDocument(str(out));group=d.getObject('Assembly')
items=[o for o in group.Group if hasattr(o,'Shape') and not o.Shape.isNull()]
for exchange in exchanges:
    obj=d.getObject(exchange['object'])
    distances=[Part.Vertex(V(*p)).distToShape(obj.Shape)[0] for p in exchange['assembly_fiducials_mm']]
    exchange['reopened_fiducial_distance_mm']=distances
    assert max(distances)<1e-5,exchange
report={'status':'INTERFERENCE_FOUND' if collisions else 'NOMINAL_CROSS_MODULE_INTERFERENCE_PASS',
        'scope':'actual exported PCB components against existing nominal mechanics; key motion, assembly paths and tolerances are separate checks',
        'native_file':str(out),'valid':all(o.Shape.isValid() for o in items),'exchanges':exchanges,'collisions':collisions,
        'remaining':'Resolve collisions, then integrate mounts, ducts, wiring, antenna, retention and full key motion. Original structure source not overwritten.'}
(r/'reports/ecad-mechanical-review.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
A.closeDocument(d.Name)

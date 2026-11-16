#!/usr/bin/env python3
"""B02: native parametric bracket; modify, save/reopen and STEP readback."""
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, '/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as App
import Part

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/tool-capability'
OUT.mkdir(exist_ok=True)
doc = App.newDocument('BracketCapability')
p = doc.addObject('App::FeaturePython', 'Parameters')
for k, v in [('Thickness', 2.0), ('HolePitch', 20.0)]:
    p.addProperty('App::PropertyLength', k, 'Dimensions'); setattr(p, k, v)
plate = doc.addObject('Part::Box', 'Plate')
plate.Length = 32; plate.Width = 12
plate.setExpression('Height', 'Parameters.Thickness')
holes=[]
for i, sign in enumerate([-1, 1]):
    h=doc.addObject('Part::Cylinder', f'HoleTool{i}')
    h.Radius=1.1; h.Height=10; h.Placement.Base=App.Vector(16,6,-1)
    h.setExpression('Placement.Base.x', f'16 mm + {sign} * Parameters.HolePitch / 2')
    holes.append(h)
f=doc.addObject('Part::MultiFuse','HoleTools'); f.Shapes=holes
cut=doc.addObject('Part::Cut','Bracket');cut.Base=plate;cut.Tool=f
doc.recompute()
def check(thickness,pitch):
    s=cut.Shape
    expected=(32*12-2*math.pi*1.1**2)*thickness
    measured_pitch=(holes[1].Shape.CenterOfMass-holes[0].Shape.CenterOfMass).Length
    assert s.isValid() and len(s.Solids)==1
    assert abs(s.Volume-expected)<1e-6
    assert abs(s.BoundBox.ZLength-thickness)<1e-6
    assert abs(measured_pitch-pitch)<1e-6
    return {'valid':s.isValid(),'solids':len(s.Solids),'volume_mm3':s.Volume,'thickness_mm':s.BoundBox.ZLength,'hole_pitch_mm':measured_pitch}
before=check(2,20)
p.Thickness=3;p.HolePitch=24;doc.recompute();after=check(3,24)
native=OUT/'B02-bracket.FCStd';doc.saveAs(str(native));App.closeDocument(doc.Name)
doc=App.openDocument(str(native));p=doc.getObject('Parameters');cut=doc.getObject('Bracket')
holes=[doc.getObject('HoleTool0'),doc.getObject('HoleTool1')]
reopened=check(3,24)
p.Thickness=2.5;p.HolePitch=22;doc.recompute();reedit=check(2.5,22);doc.save()
step=OUT/'B02-bracket.step';cut.Shape.exportStep(str(step))
roundtrip=Part.Shape();roundtrip.read(str(step))
assert roundtrip.isValid() and len(roundtrip.Solids)==1
assert abs(roundtrip.Volume-cut.Shape.Volume)<1e-6
report={'level':'tool capability sample only','version':App.Version(),'tolerance_mm':1e-6,'before':before,'after':after,'reopened':reopened,'reedit':reedit,'step_volume_mm3':roundtrip.Volume,'status':'PASS'}
(OUT/'B02-freecad.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))

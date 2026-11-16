#!/usr/bin/env python3
"""Datasheet-defined NKK SS12SDP4 nominal body, terminals and ON actuator."""
from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
R=Path(__file__).resolve().parents[1];V=A.Vector
d=A.newDocument('PowerSwitchEnvelope');body=Part.makeBox(10.2,4,4.1,V(-5.1,-2,.4))
# Drawing page640 gives 4.5 mm above-board body height, .4 mm stand-off,
# three .6x.4 leads at2.54pitch extending3.0 below mounting plane, 2mm stem.
solids=[body,Part.makeBox(1.5,1.2,2,V(.25,-.6,4.5))]
for x in (-2.54,0,2.54):solids.append(Part.makeBox(.6,.4,3.4,V(x-.3,-.2,-3)))
o=d.addObject('Part::Feature','SS12SDP4');o.Shape=Part.makeCompound(solids)
o.addProperty('App::PropertyString','Source');o.Source='NKK official Japanese SS catalog page640; gold version has same geometry as illustrated silver version'
o.addProperty('App::PropertyString','Boundary');o.Boundary='Nominal datasheet package envelope, not vendor detailed CAD. Actuator ON position +1 mm. Sample tolerances and contact state require physical verification.'
d.recompute();dest=R/'electrical/aikey_power/libraries/models/NKK_SS12SDP4.step';dest.parent.mkdir(parents=True,exist_ok=True);Part.export([o],str(dest));d.saveAs(str(R/'mechanical/Power_Switch_Envelope.FCStd'))
s=Part.Shape();s.read(str(dest));assert s.isValid();b=s.optimalBoundingBox();assert abs(b.XLength-10.2)<1e-5 and abs(b.YLength-4)<1e-5 and abs(b.ZLength-9.5)<1e-5
(R/'reports/power-component-model.json').write_text(json.dumps({'status':'NOMINAL_STEP_SAVE_READBACK_PASS','source':'reports/nkk-ss-official-jp.pdf page640 (PDF6)','step':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'dimensions_mm':[b.XLength,b.YLength,b.ZLength],'body_above_board_mm':4.5,'actuator_travel_mm':2,'pin_pitch_mm':2.54,'pin_hole_mm':.8,'nominal_envelope_only':True},indent=2)+'\n')
print('PASS')

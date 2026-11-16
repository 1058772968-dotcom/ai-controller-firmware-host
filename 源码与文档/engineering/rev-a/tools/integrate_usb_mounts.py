#!/usr/bin/env python3
"""Removable USB daughter edge clamps, bonded to the finger-side shell geometry."""
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import box,hex_prism
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
source=R/'mechanical/AIKEY_REVA_DESIGN08.FCStd';d=A.openDocument(str(source));base=d.FingerShellSupported.Shape.copy()
history=d.addObject('PartDesign::Feature','FingerShellBeforeUSBMounts');history.Shape=base.copy();d.Construction.addObject(history)
if history.ViewObject:history.ViewObject.Visibility=False
new=[];cavities=[]
def feature(name,shape,description):
    if not shape.isValid() or len(shape.Solids)!=1:raise RuntimeError('Invalid '+name)
    o=d.addObject('PartDesign::Feature',name);o.Shape=shape;o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=description;d.Assembly.addObject(o);new.append(o)
for sign,side in ((-1,'L'),(1,'R')):
    x=sign*9.3;y=6.
    # The clamps are ahead of the battery, with a 0.5 mm laminate-edge land.
    beam=Part.makeBox(20.5,3.6,1.5,V(7.5 if sign>0 else -28,y-1.8,-1.9)).common(d.OuterEnvelope.Shape)
    pedestal=Part.makeCylinder(1.95,.8,V(x,y,-.4)).cut(Part.makeBox(16.3,25,1.,V(-8.15,0,-.4)))
    base=base.fuse(beam.fuse(pedestal),1e-7)
    hole=Part.makeCylinder(.9,8,V(x,y,-3.))
    pocket=hex_prism(3.45,1.4,x,y,-1.91)
    access=box(3.9,3.9,4.,x=x,y=y,z=.4)
    cavities.extend([hole,pocket,access])
    feature('USBClamp'+side,box(3.6,3.6,1.3,x=x,y=y,z=.4).cut(hole),'Removable M1.6 edge clamp; nominal 0.5 mm board edge contact')
    feature('USBNut'+side,hex_prism(3.2,1.3,x,y,-1.9).cut(Part.makeCylinder(.85,2,V(x,y,-2.))),'M1.6 AF3.2 x1.3 captive nut; insert before the battery')
    screw=Part.makeCylinder(.8,4.,V(x,y,-2.3)).fuse(Part.makeCylinder(1.6,1.3,V(x,y,1.7)))
    screw=screw.cut(box(.45,2.3,.5,x=x,y=y,z=2.5).fuse(box(2.3,.45,.5,x=x,y=y,z=2.5)))
    feature('USBScrew'+side,screw,'M1.6 x4 pan-head nominal fastener')
    # Axial stops are outside the PCB. The rear stop starts at PCB-bottom Z,
    # retaining 2.1 mm nominal battery clearance below it.
    for y0 in (1.05,15.15):
        stop=Part.makeBox(20.5,.8,.8,V(7.5 if sign>0 else -28,y0,-.4)).common(d.OuterEnvelope.Shape)
        base=base.fuse(stop,1e-7)
for cavity in cavities:base=base.cut(cavity)
if not base.isValid() or len(base.Solids)!=1:raise RuntimeError('USB supports invalid/disconnected')
d.FingerShellSupported.Shape=base
d.FingerShellSupported.addProperty('App::PropertyLink','BeforeUSBMounts');d.FingerShellSupported.BeforeUSBMounts=history
d.FingerShellSupported.DesignStatus='Key carriers and USB supports integrated; removable USB edge clamps; full assembly check required.'
d.recompute();checks=[]
for o in new+[d.FingerShellSupported]:
    for target in (d.USBPCBAssembly,d.BatteryPack,d.BatteryTray):
        v=overlap_volume(o.Shape,target.Shape);checks.append({'a':o.Name,'b':target.Name,'overlap_mm3':v});print(checks[-1],flush=True)
        if v>1e-5:raise RuntimeError('USB retention collision')
out=R/'mechanical/AIKEY_REVA_DESIGN09.FCStd';d.saveAs(str(out));A.closeDocument(d.Name);d=A.openDocument(str(out));invalid=[o.Name for o in d.Assembly.Group if not o.Shape.isValid()]
if invalid:raise RuntimeError(str(invalid))
report={'status':'USB_MOUNT_LOCAL_PASS_FULL_DELTA_CHECK_PENDING','native_file':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'parts':len(d.Assembly.Group),'fastener_centres_mm':[[-9.3,6],[9.3,6]],'board_envelope_mm':{'x':[-8,8],'y':[2,15],'z':[-.4,.4]},'axial_stop_inner_y_mm':[1.85,15.15],'nominal_end_clearance_mm':.15,'pcb_battery_checks':checks,'assembly':'Insert two captive nuts, seat USB PCB on front ledges between axial stops, install clamps and M1.6x4 screws while the case is open. Install the battery afterwards.','remaining':['Full static/key sweep check','Plug-in force, board flex and printed-fit validation','Harness strain relief','Battery supplier envelope and swelling qualification']}
(R/'reports/mechanical-design09-build.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)

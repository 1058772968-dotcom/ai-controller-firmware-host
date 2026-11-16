#!/usr/bin/env python3
"""Integrate the battery cradle and add a removable, padded keeper beam."""
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import box,hex_prism
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
source=R/'mechanical/AIKEY_REVA_DESIGN09.FCStd';d=A.openDocument(str(source))
base=d.PalmShell.Shape.copy();finger=d.FingerShellSupported.Shape.copy();new=[]
def history(obj,name):
    o=d.addObject('PartDesign::Feature',name);o.Shape=obj.Shape.copy();d.Construction.addObject(o)
    if o.ViewObject:o.ViewObject.Visibility=False
    return o
history(d.PalmShell,'PalmShellBeforeBatteryMounts');history(d.FingerShellSupported,'FingerShellBeforeBatteryMounts')
def feature(name,shape,status):
    if not shape.isValid() or len(shape.Solids)!=1:raise RuntimeError('Invalid '+name)
    o=d.addObject('PartDesign::Feature',name);o.Shape=shape;o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=status;d.Assembly.addObject(o);new.append(o)
# Broad supports below the cradle, clear of both end stops and battery pouch.
for y in (16.,47.):
    rib=box(26,3,15,x=0,y=y,z=-25.8).common(d.OuterEnvelope.Shape)
    base=base.fuse(rib,1e-7)
base=base.fuse(d.BatteryTray.Shape,1e-7)
d.Assembly.removeObject(d.BatteryTray);d.Construction.addObject(d.BatteryTray)
if d.BatteryTray.ViewObject:d.BatteryTray.ViewObject.Visibility=False
beam=box(36.8,6,1.3,x=0,y=20.,z=-1.7).common(d.InteriorEnvelope.Shape)
cavities=[]
for sign,side in ((-1,'L'),(1,'R')):
    x=sign*16.7;y=20.
    foot=box(4.8,6,4.9,x=x,y=y,z=-15).common(d.OuterEnvelope.Shape)
    column=box(4.8,6,8.4,x=x,y=y,z=-10.1).common(d.InteriorEnvelope.Shape)
    column=column.cut(box(30.6,12,10,x=0,y=y,z=-9.8))
    post=foot.fuse(column,1e-7)
    base=base.fuse(post,1e-7)
    hole=Part.makeCylinder(.9,14,V(x,y,-13.))
    # Nut pocket opens laterally for service; the beam takes screw preload,
    # while the low-density pad locates the pack without a rigid pouch clamp.
    pocket=hex_prism(3.45,1.4,x,y,-11.11)
    entry=box(4.2,3.45,1.4,x=x-sign*2.1,y=y,z=-11.11)
    cavities.extend([hole,pocket,entry]);beam=beam.cut(hole)
    feature('BatteryNut'+side,hex_prism(3.2,1.3,x,y,-11.1).cut(Part.makeCylinder(.85,2,V(x,y,-11.4))),'M1.6 AF3.2 x1.3 nut; side-loaded before the beam')
    screw=Part.makeCylinder(.8,12,V(x,y,-12.4)).fuse(Part.makeCylinder(1.6,1.3,V(x,y,-.4)))
    screw=screw.cut(box(.45,2.3,.5,x=x,y=y,z=.4).fuse(box(2.3,.45,.5,x=x,y=y,z=.4)))
    feature('BatteryScrew'+side,screw,'M1.6 x12 pan head; nuts below battery pouch, removable keeper')
for cavity in cavities:base=base.cut(cavity)
for name,shape in [('PalmShell',base),('FingerShellSupported',finger)]:
    if not shape.isValid() or len(shape.Solids)!=1:
        shape.exportBrep(str(R/'reports'/('battery-mount-failed-'+name+'.brep')))
        print(name, 'valid',shape.isValid(),'solids',len(shape.Solids),'checks',shape.check(True),flush=True)
        raise RuntimeError('Invalid/disconnected '+name)
    d.getObject(name).Shape=shape
feature('BatteryKeeper',beam,'Removable 6 mm keeper; 0.8 mm nominal space above maximum target pack')
feature('BatteryLowerPad',box(26,40,.5,x=0,y=31.5,z=-10.0),'0.5 mm closed-cell cushioning pad; adhesive backing included in nominal thickness')
feature('BatteryUpperPad',box(28,6,.8,x=0,y=20.,z=-2.5),'0.8 mm soft foam nominal installed thickness; density/compression and swelling qualification pending')
d.PalmShell.DesignStatus='Key/mainboard mounts and battery cradle/support posts integrated; removable padded keeper'
d.recompute();checks=[]
for o in new:
    outside=o.Shape.cut(d.OuterEnvelope.Shape)
    if not outside.isNull() and (not outside.isValid() or outside.Volume>1e-5):raise RuntimeError("Outside enclosure envelope: "+o.Name+" "+str(outside.Volume))
for o in new:
    for target in (d.BatteryPack,d.USBPCBAssembly,d.MainPCBAssembly):
        if not o.Shape.BoundBox.intersect(target.Shape.BoundBox):continue
        v=overlap_volume(o.Shape,target.Shape);checks.append({'a':o.Name,'b':target.Name,'overlap_mm3':v});print(checks[-1],flush=True)
        if v>1e-5:raise RuntimeError('Battery retention collision')
out=R/'mechanical/AIKEY_REVA_DESIGN12.FCStd';d.saveAs(str(out));A.closeDocument(d.Name);d=A.openDocument(str(out))
invalid=[o.Name for o in d.Assembly.Group if not o.Shape.isValid()]
if invalid:raise RuntimeError(str(invalid))
report={'status':'BATTERY_MOUNT_LOCAL_PASS_FULL_DELTA_CHECK_PENDING','native_file':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'parts':len(d.Assembly.Group),
 'fastener_centres_mm':[[-16.7,20.],[16.7,20.]],'post_section_mm':[4.8,6],'minimum_nominal_nut_pocket_side_wall_mm':.675,'pack_target_mm':[30,43,7],'new_parts_outside_enclosure_mm3':0.,'upper_posts':'Clipped to existing interior cavity; finger-shell skin is preserved','under_pad_mm':.5,'upper_pad_installed_mm':.8,'local_checks':checks,
 'assembly':'Fit USB board first. Load two keeper nuts from the open tray interior; apply lower pad, place protected pack between existing axial stops, fit upper pad and keeper beam, tighten screws onto rigid posts. Close finger shell after wiring. Keeper is removable with the case open.',
 'remaining':['Full native assembly and key sweeps','Protected pack supplier envelope, lead exit, swelling allowance','Foam specification/preload and printed-fit qualification','Wire harness routing']}
(R/'reports/mechanical-design12-build.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)

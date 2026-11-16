#!/usr/bin/env python3
"""Add actual power/reset boards, serviceable mounts and bottom control access."""
from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import box,hex_prism
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
d=A.openDocument(str(R/'mechanical/AIKEY_REVA_DESIGN18.FCStd'));added=[];ops=[]
def plate(w,h,t,x,y,z):return Part.makeBox(w,t,h,V(x-w/2,y,z-h/2))
def along_y(s,x,y,z):
 q=s.copy();q.Placement=A.Placement(V(x,y,z),A.Rotation(V(1,0,0),-90)).multiply(s.Placement);return q
def unite(a,b,label):
 if not b.isValid() or not b.Solids:raise RuntimeError('Invalid tool '+label)
 s=a.fuse(b,1e-7)
 if not s.isValid() or len(s.Solids)!=1:
  for nm,shape in [('FailedUnionBase',a),('FailedUnionTool',b),('FailedUnionResult',s)]:
   item=d.addObject('PartDesign::Feature',nm);item.Shape=shape;d.Construction.addObject(item)
  for nm,var in [('PalmShell','palm'),('FingerShellSupported','finger')]:
   if var in globals():d.getObject(nm).Shape=globals()[var]
  d.recompute();d.saveAs(str(R/'mechanical/AIKEY_REVA_DESIGN19_DIAGNOSTIC.FCStd'))
  raise RuntimeError('Invalid/disconnected union '+label)
 if s.Volume<max(a.Volume,b.Volume)-.05:raise RuntimeError('Unexpected material loss '+label)
 ops.append({'operation':'union','label':label,'before_mm3':a.Volume,'after_mm3':s.Volume});print(ops[-1],flush=True);return s
def cut(a,b,label):
 if overlap_volume(a,b)<1e-8:return a
 s=a.cut(b)
 if not s.isValid() or s.Volume<a.Volume-b.Volume-.05 or s.Volume>a.Volume+.05:raise RuntimeError('Invalid cut '+label)
 if overlap_volume(s,b)>1e-5:raise RuntimeError('Uncleared '+label)
 ops.append({'operation':'cut','label':label,'before_mm3':a.Volume,'after_mm3':s.Volume});print(ops[-1],flush=True);return s
def add(name,s,status):
 if not s.isValid():raise RuntimeError('Invalid '+name)
 o=d.addObject('PartDesign::Feature',name);o.Shape=s;o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=status;d.Assembly.addObject(o);added.append(o);return o
def board(name,file,origin):
 s=Part.Shape();s.read(str(file));p=A.Placement(V(*origin),A.Rotation(V(1,0,0),90));s.Placement=p.multiply(s.Placement)
 o=add(name,s,'Actual saved KiCad STEP assembly; complete nominal 0.8 mm PCB thickness checked separately')
 o.addProperty('App::PropertyString','ECADSource');o.ECADSource=json.dumps({'file':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'origin_mm':origin,'rotation_xyzw':list(p.Rotation.Q)})
 return o
power=board('PowerPCBAssembly',R/'electrical/exchange/review-current/aikey_power.step',[-4,7.3,-8.5])
reset=board('ResetPCBAssembly',R/'electrical/exchange/review-current/aikey_top_key.step',[-12.5,4.1,-.5])
palm=d.PalmShell.Shape.copy();finger=d.FingerShellSupported.Shape.copy()
# Restore only source wall stock at obsolete candidate apertures; never fill
# the full internal envelope. New centre positions are engineering deviations.
palm=unite(palm,plate(7,3,8,10,-3,-9).common(d.HollowShell.Shape),'restore old power aperture')
finger=unite(finger,Part.makeCylinder(.7,9,V(12,-2,0),V(0,1,0)).common(d.HollowShell.Shape),'restore old reset aperture')
# Power board front ledges and independent rear corner clamps.
for side,x,clamp_x in [('L',-5.0,-4.8),('R',11.,10.8)]:
 post=Part.makeCylinder(2.15,6.5,V(x,0,-12),V(0,1,0)).common(d.OuterEnvelope.Shape)
 palm=unite(palm,post,'power support '+side)
 hole=Part.makeCylinder(.95,12,V(x,0,-12),V(0,1,0))
 nutp=along_y(hex_prism(3.45,1.4,0,0,0),x,4.35,-12)
 slot=plate(3.2,3.45,1.4,x+(1.6 if side=='L' else -1.6),4.35,-12)
 for label,c in [('shaft',hole),('nut',nutp),('nut entry',slot)]:palm=cut(palm,c,'power '+side+' '+label)
 clamp=plate(3.2,7.6,.8,clamp_x,7.3,-12).cut(hole)
 # Keep the centre of the board and its three backside wire pads accessible.
 clamp=clamp.cut(plate(14.3,5.6,2,3,7,-12))
 add('PowerClamp'+side,clamp,'Printed removable corner clamp; middle window leaves wire pads clear')
 nut=along_y(hex_prism(3.2,1.3,0,0,0).cut(Part.makeCylinder(.85,2,V(0,0,-.1))),x,4.4,-12)
 add('PowerNut'+side,nut,'M1.6 AF3.2 x1.3; load from central cavity before switch board')
 screw=Part.makeCylinder(.8,4,V(x,4.1,-12),V(0,1,0)).fuse(Part.makeCylinder(1.6,1.3,V(x,8.1,-12),V(0,1,0)))
 screw=screw.cut(plate(.45,2.3,.5,x,8.9,-12).fuse(plate(2.3,.45,.5,x,8.9,-12)))
 add('PowerScrew'+side,screw,'M1.6x4; rear/internal access')
# Bottom-facing component cavity, direct switch stem slot and board end stops.
palm=cut(palm,plate(10.6,4.4,4.9,3,1.8,-12),'power package cavity')
palm=cut(palm,plate(3.9,1.6,4,3,-1,-12),'power 2mm sliding stem travel')
for z in (-16.15,-7.85):
 stop=plate(17.2,.7,7.3,3,0,z).common(d.OuterEnvelope.Shape)
 palm=unite(palm,stop,'power PCB axial stop '+str(z))
# Reset board is captured between the two case halves at the seam. It
# reuses the actual SKQGABE010 board, avoiding a second set of screws in the
# crowded USB region. Its front datum and compressed rear foam frame prevent
# board motion under the pin load. Load board and insulating plunger before
# closing the case; opening the case releases both for service.
frame=plate(10,10,5.2,-8,0,-5).common(d.OuterEnvelope.Shape)
frame=frame.cut(plate(8.3,8.3,1.5,-8,1.8,-5))
frame=frame.cut(plate(9.3,9.3,.95,-8,3.3,-5))
frame=frame.cut(plate(8,8,2,-8,4.25,-5))
frame=frame.cut(Part.makeCylinder(.7,1.7,V(-8,-1,-5),V(0,1,0)))
frame=frame.cut(Part.makeCylinder(1.75,.9,V(-8,.65,-5),V(0,1,0)))
frame=frame.cut(Part.makeCylinder(1.1,1.85,V(-8,1.55,-5),V(0,1,0)))
# Fuse the frame before cutting the same passages through the original walls.
palm_mask=Part.makeBox(100,150,50,V(-50,-10,-55.1))
finger_mask=Part.makeBox(100,150,50,V(-50,-10,-4.9))
palm=unite(palm,frame.common(palm_mask),'reset lower capture frame')
finger=unite(finger,frame.common(finger_mask),'reset upper capture frame')
passages=[plate(8.3,8.3,1.5,-8,1.8,-5),plate(9.3,9.3,.95,-8,3.3,-5),plate(8,8,2,-8,4.25,-5),Part.makeCylinder(.7,1.7,V(-8,-1,-5),V(0,1,0)),Part.makeCylinder(1.75,.9,V(-8,.65,-5),V(0,1,0)),Part.makeCylinder(1.1,1.85,V(-8,1.55,-5),V(0,1,0))]
for i,cavity in enumerate(passages):
 palm=cut(palm,cavity,'reset passage palm '+str(i));finger=cut(finger,cavity,'reset passage finger '+str(i))
foam=plate(9,9,.15,-8,4.1,-5).cut(plate(8,8,.4,-8,4,-5))
add('ResetPCBPad',foam,'Closed-cell silicone foam frame9x9 ID8x8, installed0.15mm, free0.20mm target; preload holds board to front datum. Physical compression and creep qualification pending.')
plunger=Part.makeCylinder(.5,1.05,V(-8,.70,-5),V(0,1,0)).fuse(Part.makeCylinder(1.6,.35,V(-8,.70,-5),V(0,1,0)))
add('ResetPlunger',plunger,'POM insulating pin, Ø1 stem / Ø3.2 captive flange; .05 nominal switch gap, .50mm inward travel to independent annular housing stop. .7mm recessed pin target; physical travel stack and force qualification pending.')
for name,s in [('PalmShell',palm),('FingerShellSupported',finger)]:
 old=d.addObject('PartDesign::Feature',name+'BeforeControls');old.Shape=d.getObject(name).Shape.copy();d.Construction.addObject(old)
 if old.ViewObject:old.ViewObject.Visibility=False
 if not s.isValid() or len(s.Solids)!=1:raise RuntimeError('Final shell invalid '+name)
 d.getObject(name).Shape=s
d.recompute();added_names=[o.Name for o in added];out=R/'mechanical/AIKEY_REVA_DESIGN19.FCStd';d.saveAs(str(out));A.closeDocument(d.Name);d=A.openDocument(str(out))
checks=[]
for name in added_names:
 a=d.getObject(name)
 for b in d.Assembly.Group:
  if a==b or (b.Name in added_names and b.Name<name):continue
  if not a.Shape.BoundBox.intersect(b.Shape.BoundBox):continue
  v=overlap_volume(a.Shape,b.Shape);row={'a':name,'b':b.Name,'overlap_mm3':v};checks.append(row);print(row,flush=True)
fail=[x for x in checks if x['overlap_mm3']>1e-5];outside=[]
for name in added_names:
 v=d.getObject(name).Shape.cut(d.OuterEnvelope.Shape).Volume;outside.append({'part':name,'outside_mm3':v})
 if v>1e-5:fail.append(outside[-1])
report={'status':'FAIL' if fail else 'CONTROL_BOARDS_AND_MOUNTS_LOCAL_PASS_FULL_CHECKS_PENDING','native_file':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'parts':len(d.Assembly.Group),'checks':checks,'outside':outside,'failures':fail,'operations':ops,'controls':{'power_stem_center_xz_mm':[3,-12],'power_travel_mm':2,'reset_pin_center_xz_mm':[-8,-5],'reset_pinhole_diameter_mm':1.4},'remaining':['Full static/motion/finished PCB thickness checks','Continuous power-stem motion and reset pin/tool access','Wire strain relief and assembly sequence','Sample switch forces/clearances and ESD qualification']}
(R/'reports/mechanical-design19-build.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],flush=True)
sys.exit(bool(fail))

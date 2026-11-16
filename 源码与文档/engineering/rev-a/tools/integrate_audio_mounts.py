#!/usr/bin/env python3
"""Attach LRA seat and add a removable mic board clamp plus sealed acoustic duct."""
from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import box,hex_prism
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
d=A.openDocument(str(R/'mechanical/AIKEY_REVA_DESIGN12.FCStd'));new=[]
def unite(a,b,label):
    if b.isNull() or b.Volume<1e-6:raise RuntimeError('Empty added solid '+label)
    s=a.fuse(b,1e-7)
    print('UNION',label,'before',a.Volume,'tool',b.Volume,'after',s.Volume,flush=True)
    if not s.isValid() or s.Volume<max(a.Volume,b.Volume)-.001 or s.Volume>a.Volume+b.Volume+.001:
        raise RuntimeError('Boolean union mass invariant failed: '+label)
    return s
def subtract(a,b,label):
    volume=overlap_volume(a,b)
    if volume<1e-8:return a
    s=a.cut(b)
    print('CUT',label,'before',a.Volume,'intersection',volume,'after',s.Volume,flush=True)
    # Common/cut mass integration of the trimmed source B-splines does not
    # numerically add exactly. Check conservative set-operation bounds, then
    # independently require the requested cutter to be absent from the result.
    tolerance=max(.005,a.Volume*1e-5)
    if not s.isValid() or s.Volume<a.Volume-b.Volume-tolerance or s.Volume>a.Volume+tolerance:
        raise RuntimeError('Boolean cut mass invariant failed: '+label)
    if overlap_volume(s,b)>1e-5:raise RuntimeError('Cut leaves material in its tool: '+label)
    return s
def history(name):
    old=d.getObject(name);o=d.addObject('PartDesign::Feature',name+'BeforeAudioMounts');o.Shape=old.Shape.copy();d.Construction.addObject(o)
    if o.ViewObject:o.ViewObject.Visibility=False
def feature(name,shape,status):
    if not shape.isValid() or len(shape.Solids)!=1:raise RuntimeError('Invalid/disconnected '+name)
    o=d.addObject('PartDesign::Feature',name);o.Shape=shape;o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=status;d.Assembly.addObject(o);new.append(o);return o
def assign(name,shape):
    if not shape.isValid() or len(shape.Solids)!=1:raise RuntimeError('Invalid/disconnected '+name)
    d.getObject(name).Shape=shape
def along_y(s,x,y,z):
    out=s.copy();out.Placement=A.Placement(V(x,y,z),A.Rotation(V(1,0,0),-90)).multiply(out.Placement);return out
history('FingerShellSupported');history('TopCoverSupported');history('PalmShell')
palm=d.PalmShell.Shape.copy()
# LRA seat attaches to the finger half through a transverse, clipped rib.
# The bonded face carries vibration; the side wall has radial assembly space.
seat=d.LRASeat.Shape.copy().cut(box(2.4,4,1.2,y=18.7,z=5.0))
rib=box(60,2,.8,y=24,z=3.7).common(d.OuterEnvelope.Shape)
rib=rib.cut(Part.makeCylinder(5.2,5,V(0,24,4)))
finger=unite(unite(d.FingerShellSupported.Shape,rib,'LRA rib'),seat,'LRA seat')
assign('FingerShellSupported',finger)
d.Assembly.removeObject(d.LRASeat);d.Construction.addObject(d.LRASeat)
if d.LRASeat.ViewObject:d.LRASeat.ViewObject.Visibility=False
feature('LRAAdhesive',Part.makeCylinder(5,.15,V(0,24,4)),'.15 mm installed acrylic transfer adhesive allocation; final grade/retention and vibration qualification required')
# Native top exterior reconstructed from the same source ring dimensions.
base=d.CapBottomProfile.Shape
def ring(s,rx,rz):
    pts=[]
    for v in base.discretize(Number=100)[:-1]:
        x=v.x/24.5*rx;z=v.z/22.8*rz;pts.append(V(x,s-.2*z,z))
    c=Part.BSplineCurve();c.interpolate(pts,PeriodicFlag=True);return Part.Wire(c.toShape())
outer=Part.makeLoft([ring(*v) for v in [(103.7,24.5,22.8),(104.5,25.55,23),(106.2,26,23),(108.1,25.85,22.85),(109.25,25.15,22.2),(109.8,24.5,21.7)]],True,True)
# The PCB body faces -Y. The bottom acoustic port opens +Y at (-13,107.5,-6).
# Rear components and four wire lands remain in the open central window.
cx,cz=-13.68,-6.
frame=along_y(box(10.4,10.4,6,x=0,y=0,z=0).cut(box(6.4,6.4,7,z=-.1)),cx,107.5,cz).common(outer)
duct=Part.makeCylinder(1.5,2.3,V(-13,108,-6),V(0,1,0))
duct=duct.cut(Part.makeCylinder(.7,10,V(-13,107,-6),V(0,1,0)))
topbase=subtract(d.TopCoverSupported.Shape,along_y(box(14.8,9.,1.1),cx+.5,105.8,cz),'original skirt retainer pocket')
top=unite(unite(topbase,frame,'mic frame'),duct,'acoustic duct')
retainer=along_y(box(14.6,8.8,.7,z=0).cut(box(6.4,6.4,2,x=-.5,z=-.1)),cx+.5,106.0,cz)
cavities=[]
for side,sign in (('L',-1),('R',1)):
    x=cx+(-5.2 if sign<0 else 5.8)
    post=along_y(box(4.8,5.,6.1),x,106.7,cz).common(outer)
    post=post.cut(along_y(box(7.2,7.2,.9),cx,106.6,cz))
    top=unite(top,post,'mic post '+side)
    hole=Part.makeCylinder(.9,8,V(x,105.5,cz),V(0,1,0))
    pocket=along_y(hex_prism(3.45,1.4,0,0,0),x,109.0,cz)
    # Both nut-loading channels open toward +X. The right-hand channel must
    # not cut the acoustic duct between this post and the microphone port.
    entry=along_y(box(4.2,3.45,1.4,x=2.1,z=0),x,109.0,cz)
    cavities.extend([hole,pocket,entry]);retainer=retainer.cut(hole)
    nut=along_y(hex_prism(3.2,1.3,0,0,0).cut(Part.makeCylinder(.85,2,V(0,0,-.1))),x,109.05,cz)
    feature('MicNut'+side,nut,'M1.6 AF3.2 x1.3; load along -X before PCB and retainer; right channel opens away from acoustic duct')
    screw=Part.makeCylinder(.8,5,V(0,0,0)).fuse(Part.makeCylinder(1.6,1.3,V(0,0,-1.3)))
    screw=screw.cut(box(.45,2.3,.5,z=-1.3).fuse(box(2.3,.45,.5,z=-1.3)))
    feature('MicScrew'+side,along_y(screw,x,106.,cz),'M1.6 x5; screw heads accessible from inside removed top cover')
    # Relieve the body rim for the head and its +Y cover-removal path. This is
    # inside the assembled top skirt, with .3 mm nominal radial head clearance.
    relief=Part.makeCylinder(1.9,7,V(x,104.4,cz),V(0,1,0))
    palm=subtract(palm,relief,'palm head relief '+side)
    top=subtract(top,Part.makeCylinder(1.9,1.7,V(x,104.4,cz),V(0,1,0)),'top skirt head relief '+side)
for i,cavity in enumerate(cavities):top=subtract(top,cavity,'mic fastener cavity '+str(i))
for i,(x,z) in enumerate([(-10.98,-7.7),(-14.58,-7.7),(-12.78,-8.7),(-16.38,-8.7)],1):
    top=subtract(top,Part.makeCylinder(.6,1.3,V(x,107.5,z),V(0,1,0)),'mic wire solder access '+str(i))
assign('TopCoverSupported',top)
assign('PalmShell',palm)
if abs(top.common(duct).Volume-duct.Volume)>1e-5:raise RuntimeError('Acoustic duct lost during Boolean integration')
feature('MicRetainer',retainer,'Removable perimeter clamp; .8 mm nominal PCB stack, .3 mm edge lips, central component opening')
gasket=Part.makeCylinder(1.5,.5,V(-13,107.5,-6),V(0,1,0)).cut(Part.makeCylinder(.7,1,V(-13,107.4,-6),V(0,1,0)))
feature('MicAcousticGasket',gasket,'Closed-cell silicone foam ring: OD3/ID1.4, .5 mm installed thickness; supplier free thickness/compression and leak test pending')
d.recompute()
checks=[]
for a in new:
    for b in d.Assembly.Group:
        if a==b or (b in new and new.index(b)<new.index(a)):continue
        if not a.Shape.BoundBox.intersect(b.Shape.BoundBox):continue
        v=overlap_volume(a.Shape,b.Shape);checks.append({'a':a.Name,'b':b.Name,'overlap_mm3':v});print(checks[-1],flush=True)
for name,target in [('FingerShellSupported','LRA'),('TopCoverSupported','MicPCBAssembly')]:
    v=overlap_volume(d.getObject(name).Shape,d.getObject(target).Shape);checks.append({'a':name,'b':target,'overlap_mm3':v});print(checks[-1],flush=True)
fail=[c for c in checks if c['overlap_mm3']>1e-5]
out=R/'mechanical/AIKEY_REVA_DESIGN16.FCStd';d.saveAs(str(out));A.closeDocument(d.Name);d=A.openDocument(str(out))
invalid=[o.Name for o in d.Assembly.Group if not o.Shape.isValid()]
report={'status':'FAIL' if fail or invalid else 'AUDIO_MOUNTS_LOCAL_PASS_FULL_DELTA_PENDING','native_file':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'parts':len(d.Assembly.Group),'local_checks':checks,'invalid':invalid,
 'microphone':{'port_mm':[-13,107.5,-6],'board_nominal_thickness_mm':.8,'gasket_od_id_installed_mm':[3,1.4,.5],'duct_diameter_mm':1.4,'retention':'M1.6x5 removable perimeter clamp and captive nuts'},
 'lra':{'seat_id_mm':10.4,'body_nominal_mm':[10,3.7],'datasheet_tolerance_mm':[.1,.15],'adhesive_installed_mm':.15,'wire_exit_mm':[2.4,1.2]},
 'remaining':['Full static and key-motion verification','Acoustic duct continuity and assembly path check','Foam/adhesive specification and physical acoustic/haptic qualification','Lead routing/strain relief']}
(R/'reports/mechanical-design16-build.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],flush=True)
sys.exit(bool(fail or invalid))

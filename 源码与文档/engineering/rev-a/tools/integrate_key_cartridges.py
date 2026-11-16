#!/usr/bin/env python3
"""Design 03: real PCB assemblies and serviceable, split-guide key carriers."""
from pathlib import Path
import json,math,sys,itertools
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import cartridge,rounded,box,thumb
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
d=A.openDocument(str(R/'mechanical/AIKEY_REVA_ECAD_REVIEW.FCStd'))
assembly=d.getObject('Assembly');construction=d.getObject('Construction')
# Move the acoustic port clear of the left key carrier. It was an engineering
# candidate, not a frozen user control location. Preserve inward-facing PDM body.
mic=d.getObject('MicPCBAssembly');mic_shape=mic.Shape.copy();mic_shape.translate(V(-3,1.5,-4));mic.Shape=mic_shape
mic.DesignStatus='Actual KiCad assembly; acoustic port x=-13,z=-6, body faces inward -Y; seal pending'
base=json.loads((R/'reports/mechanical-build.json').read_text())
def item(name,shape,status,visible=True):
    obj=d.addObject('Part::Feature',name);obj.Shape=shape
    obj.addProperty('App::PropertyString','DesignStatus');obj.DesignStatus=status
    (assembly if visible else construction).addObject(obj)
    if obj.ViewObject:obj.ViewObject.Visibility=visible
    return obj
def pose(shape,origin,rot):
    out=shape.copy();out.Placement=A.Placement(origin,rot).multiply(shape.Placement);return out
def capunit(angle):
    arcs=[[(7,-23),(18,-23),(26,-12),(26,0)],[(26,0),(26,12),(17,23),(2,23)],[(2,23),(-12,23),(-26,14),(-26,2)],[(-26,2),(-26,-8),(-7,-23),(7,-23)]]
    boundary=[]
    for arc in arcs:
        for i in range(96):
            t=i/96;boundary.append(tuple(sum(arc[j][k]*v for j,v in enumerate(((1-t)**3,3*(1-t)**2*t,3*(1-t)*t*t,t**3))) for k in (0,1)))
    boundary.append(boundary[0]);dx,dz=math.cos(angle),math.sin(angle);radius=0
    for a,b in zip(boundary,boundary[1:]):
        ex,ez=b[0]-a[0],b[1]-a[1];den=dx*ez-dz*ex
        if abs(den)<1e-10:continue
        rr=(a[0]*ez-a[1]*ex)/den;u=(a[0]*dz-a[1]*dx)/den
        if rr>0 and -1e-8<=u<=1+1e-8:radius=max(radius,rr)
    return dx*radius/26,dz*radius/23
def ring(y,rx,rz):
    points=[]
    for i in range(72):
        u=capunit(2*math.pi*i/72);x=rx*u[0];z=rz*u[1]
        points.append(V(x,y-.2*z,z))
    curve=Part.BSplineCurve();curve.interpolate(points,PeriodicFlag=True)
    return Part.Wire(curve.toShape())
# Reconstruct source cap rings, not an enlarged bounding-box lid.
rings=[(103.7,24.5,22.8),(104.5,25.55,23),(106.2,26,23),(108.1,25.85,22.85),(109.25,25.15,22.2),(109.8,24.5,21.7)]
topouter=Part.makeLoft([ring(*r) for r in rings],True,True)
topinner=Part.makeLoft([ring(y if i<4 else y-1.632,rx-1.6,rz-1.6) for i,(y,rx,rz) in enumerate(rings) if i!=4],True,True)
top=topouter.cut(topinner)
for name in ['VoiceKey','VoicePCB','VoiceSwitch','VoiceGuide','SideKey','SidePCB','SideSwitch','SideGuide','LeftThumbKey','LeftPCB','LeftSwitch','RightThumbKey','RightPCB','RightSwitch','TopCover']:
    obj=d.getObject(name)
    if obj:d.removeObject(obj.Name)
placements=[]
for k in base['keys']:
    placements.append((k['key'],22 if k['key']=='Voice' else 8.5,15 if k['key']=='Voice' else 21,'back',V(*k['contact_mm']),A.Rotation(V(0,0,1),V(*k['normal']))))
rot=A.Rotation(V(1,0,0),math.degrees(math.atan(.2))).multiply(A.Rotation(V(0,1,0),-43)).multiply(A.Rotation(V(1,0,0),-90))
for name,x,z,w,h in [('Left',-8.5,8,24,19),('Right',8.5,-10,20,17)]:
    placements.append((name,w,h,'top',V(x,109.8-.2*z+1.5,z),rot))
records=[];moving=[]
for name,w,h,kind,origin,rot in placements:
    shapes=cartridge(name,w,h,R/f'electrical/exchange/aikey_{kind}_key.step')
    records.append({'key':name,'origin_mm':list(origin),'rotation_xyzw':list(rot.Q),'normal':list(rot.multVec(V(0,0,1))),
        'outline_mm':[w,h],'inward_hard_stop_mm':.55,'nominal_switch_gap_mm':.055,'shim_nominal_mm':.3})
    if kind=='top':
        opening=thumb(name,w+.6,h+.6,16,-12)
        top=top.cut(pose(opening,origin,rot))
    for suffix,shape in shapes.items():
        mapped=pose(shape,origin,rot)
        obj=item(name+suffix,mapped,'prototype nominal; split guide + M1.6 x 4 / M1.6 hex nut; shim selects zero-preload gap')
        obj.addProperty('App::PropertyString','LocalKeyFrame');obj.LocalKeyFrame=json.dumps(records[-1])
        if suffix=='Key':moving.append(obj.Name)
    print('Created '+name+' cartridge',flush=True)
top=top.cut(Part.makeCylinder(.7,16,V(-13,101,-6),V(0,1,0)))
item('TopCover',top.removeSplitter(),'source six cap rings and rotated thumb-key contours; carrier attachment and acoustic duct pending')
d.recompute()
out=R/'mechanical/AIKEY_REVA_DESIGN03.FCStd';d.saveAs(str(out))
A.closeDocument(d.Name);d=A.openDocument(str(out));assembly=d.getObject('Assembly')
parts=list(assembly.Group);invalid=[p.Name for p in parts if not p.Shape.isValid()]
collisions=[]
for a,b in itertools.combinations(parts,2):
    if not a.Shape.BoundBox.intersect(b.Shape.BoundBox):continue
    # Rigid static state has no permitted cross-part overlaps, including nuts.
    volume=overlap_volume(a.Shape,b.Shape)
    if volume>1e-5:
        hit={'a':a.Name,'b':b.Name,'overlap_mm3':volume};collisions.append(hit);print(json.dumps(hit),flush=True)
report={'status':'FAIL' if invalid or collisions else 'NOMINAL_STATIC_PASS_MOUNTS_PENDING','native_file':str(out),
    'parts':len(parts),'invalid':invalid,'collisions':collisions,'keys':records,'moving_objects':moving,
    'remaining':['carrier attachment to shells','all-key movement against complete assembly','tolerance selection with measured switches','other module mounts, fasteners, seams, antenna, wiring, acoustic duct and optical path']}
(R/'reports/mechanical-design03.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
A.closeDocument(d.Name)

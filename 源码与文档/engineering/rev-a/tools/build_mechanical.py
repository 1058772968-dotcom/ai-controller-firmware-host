#!/usr/bin/env python3
"""Rebuild a native FreeCAD assembly from the approved C profile and explicit parameters.

Native Part loft/cut/fuse history is retained. Cross-section B-splines derive from
the reference source, not STL conversion. Remaining parts use constructive B-rep
geometry and this source is the editable/reproducible design definition.
"""
import json
import math
from pathlib import Path
import re
import sys
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as App
import Part
import Mesh

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'mechanical';OUT.mkdir(exist_ok=True)
P=json.loads((ROOT/'spec/mechanical.json').read_text())
source=(ROOT.parents[1]/'prototype/src/reference-product.js').read_text()
PROFILE=json.loads('['+re.search(r'const PROFILE = \[(.*?)\];',source,re.S).group(1).rstrip().rstrip(',')+']')
V=App.Vector
doc=App.newDocument('AIKEY_REVA')
construction=doc.addObject('App::DocumentObjectGroup','Construction')
assembly=doc.addObject('App::DocumentObjectGroup','Assembly')
parts=[]
palette={'shell':(.74,.73,.69),'key':(.20,.24,.25),'pcb':(.08,.4,.30),'metal':(.65,.67,.68),'battery':(.25,.4,.53),'light':(.3,.8,.88),'fixture':(.6,.62,.64)}
params=doc.addObject('Spreadsheet::Sheet','Parameters')
for i,(k,v) in enumerate([(k,v) for k,v in P.items() if isinstance(v,(int,float))],1):
    params.set(f'A{i}',k);params.set(f'B{i}',str(v));params.setAlias(f'B{i}',k)
params.set('D1','Geometry changes: edit spec/mechanical.json and rebuild with tools/build_mechanical.py')
params.set('D2','Native loft/cut history is retained; no manufacture release or physical fit claim')
def section(y):
    if y<=PROFILE[0][0]:return PROFILE[0][1:]
    if y>=PROFILE[-1][0]:return PROFILE[-1][1:]
    i=next(i for i in range(len(PROFILE)-1) if PROFILE[i+1][0]>=y)
    a,b=PROFILE[i:i+2];prev=PROFILE[max(0,i-1)];nxt=PROFILE[min(len(PROFILE)-1,i+2)]
    span=b[0]-a[0];t=(y-a[0])/span
    return [(2*t**3-3*t*t+1)*a[k]+(t**3-2*t*t+t)*span*(b[k]-prev[k])/(b[0]-prev[0])+(-2*t**3+3*t*t)*b[k]+(t**3-t*t)*span*(nxt[k]-a[k])/(nxt[0]-a[0]) for k in (1,2,3)]
def smooth(a,b,y):
    t=max(0,min(1,(y-a)/(b-a)));return t*t*(3-2*t)
def bezier(a,b,c,d,t):return tuple((1-t)**3*a[i]+3*(1-t)**2*t*b[i]+3*(1-t)*t*t*c[i]+t**3*d[i] for i in (0,1))
arcs=[[(7,-23),(18,-23),(26,-12),(26,0)],[(26,0),(26,12),(17,23),(2,23)],[(2,23),(-12,23),(-26,14),(-26,2)],[(-26,2),(-26,-8),(-7,-23),(7,-23)]]
boundary=[bezier(*arc,i/96) for arc in arcs for i in range(96)];boundary.append(boundary[0])
def capunit(angle):
    dx,dz=math.cos(angle),math.sin(angle);r=0
    for a,b in zip(boundary,boundary[1:]):
        ex,ez=b[0]-a[0],b[1]-a[1];den=dx*ez-dz*ex
        if abs(den)<1e-10:continue
        rr=(a[0]*ez-a[1]*ex)/den;u=(a[0]*dz-a[1]*dx)/den
        if rr>0 and -1e-8<=u<=1+1e-8:r=max(r,rr)
    return dx*r/26,dz*r/23
def surface(y,angle,inset=0):
    rx,front,rear=section(y);cz=(front-rear)/2;rz=(front+rear)/2
    pow=lambda x:math.copysign(abs(x)**.86,x)
    x=(rx-inset)*pow(math.cos(angle));z=cz+(rz-inset)*pow(math.sin(angle));blend=smooth(89,103.7,y)
    ux,uz=capunit(angle);x=x*(1-blend)+(rx-inset)*ux*blend;z=z*(1-blend)+(cz+(rz-inset)*uz)*blend
    return V(x,y+P['top_slope']*z*smooth(92,103.7,y),z)
def feature(name,shape,kind='fixture',status='designed',visible=True):
    o=doc.addObject('Part::Feature',name);o.Shape=shape
    o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=status
    if visible:
        assembly.addObject(o);parts.append(o)
    else:construction.addObject(o)
    if o.ViewObject:
        o.ViewObject.ShapeColor=palette[kind];o.ViewObject.Visibility=visible
    return o
def profile(name,y,inset):
    curve=Part.BSplineCurve();curve.interpolate([surface(y,2*math.pi*i/72,inset) for i in range(72)],PeriodicFlag=True)
    return feature(name,Part.Wire(curve.toShape()),visible=False)
def loft(name,ys,inset):
    profiles=[profile(name+f'Section{i:02d}',y,inset) for i,y in enumerate(ys)]
    obj=doc.addObject('Part::Loft',name);obj.Sections=profiles;obj.Solid=True;obj.Ruled=False;obj.Closed=False;construction.addObject(obj);doc.recompute()
    if obj.ViewObject:obj.ViewObject.Visibility=False
    assert obj.Shape.isValid() and len(obj.Shape.Solids)==1,name
    return obj
ys=[0,1,3,7,17,32,48,62,74,82,90,98,103.7]
outer=loft('OuterEnvelope',ys,0)
inner=loft('InteriorEnvelope',[P['wall'],3,7,17,32,48,62,74,82,90,98,103.7],P['wall'])
shell=doc.addObject('Part::Cut','HollowShell');shell.Base=outer;shell.Tool=inner;construction.addObject(shell);doc.recompute()
if shell.ViewObject:shell.ViewObject.Visibility=False
print('Shell loft created',flush=True)

def box(size,center):return Part.makeBox(*size,V(*(center[i]-size[i]/2 for i in range(3))))
def cylinder(r,h,base,direction=V(0,0,1)):return Part.makeCylinder(r,h,V(*base),direction)
def local(shape,origin,normal):
    s=shape.copy();s.Placement=App.Placement(origin,App.Rotation(V(0,0,1),normal));return s
def rounded(w,h,t,r):
    # Union of central bars and four discs avoids topology-dependent fillets.
    s=Part.makeBox(w-2*r,h,t,V(-w/2+r,-h/2,0)).fuse(Part.makeBox(w,h-2*r,t,V(-w/2,-h/2+r,0)))
    for x in (-w/2+r,w/2-r):
        for y in (-h/2+r,h/2-r):s=s.fuse(cylinder(r,t,(x,y,0)))
    return s.removeSplitter()
openings=[];key_metadata=[]
for name,y,w,h,bump in [('Voice',90,22,15,1.2),('Side',40,8.5,21,.6)]:
    surface_point=surface(y,math.pi/2)
    tangent=surface(y+.01,math.pi/2)-surface(y-.01,math.pi/2)
    normal=V(0,-tangent.z,tangent.y);normal.normalize()
    contact=surface_point+V(0,0,bump)
    cutshape=local(rounded(w+.6,h+.6,18,2.5),contact-normal*12,normal);openings.append(cutshape)
    capshape=local(rounded(w,h,.9,2.2),contact-normal*.9,normal)
    stem=local(Part.makeBox(2.8,2.8,3.1,V(-1.4,-1.4,-4.0)),contact,normal)
    flange=local(rounded(6.8,6.8,.7,1),contact-normal*1.6,normal)
    key=feature(name+'Key',capshape.fuse(stem).fuse(flange).removeSplitter(),'key')
    pcb=feature(name+'PCB',local(Part.makeBox(9,9,.8,V(-4.5,-4.5,0)),contact-normal*6.3,normal),'pcb','actual back-key board 9x9x0.8; component solids envelope')
    sw=feature(name+'Switch',local(Part.makeBox(5.2,5.2,1.5,V(-2.6,-2.6,0)),contact-normal*5.5,normal),'metal','SKQGAFE010 manufacturer body envelope; terminals not represented')
    guide=rounded(8.5,8.5,2.2,1).cut(Part.makeBox(3.2,3.2,4,V(-1.6,-1.6,-.5)))
    feature(name+'Guide',local(guide,contact-normal*3.8,normal),'fixture','independent guide; support integration in progress')
    key_metadata.append({'key':name,'contact_mm':list(contact),'normal':list(normal),'travel_mm':P['key_travel'],'stop_review':'manufacturer overtravel and tolerance stack pending'})
for op in openings:shellshape=shell.Shape.cut(op) if 'shellshape' not in locals() else shellshape.cut(op)
usb_opening=box([10,8,4.2],[0,1,2]);shellshape=shellshape.cut(usb_opening)
reset_hole=cylinder(.7,9,(12,-2,0),V(0,1,0));shellshape=shellshape.cut(reset_hole)
power_hole=box([7,8,3],[10,1,-9]);shellshape=shellshape.cut(power_hole)
front=shellshape.common(Part.makeBox(100,140,70,V(-50,-10,P['split_z']+P['seam_gap']/2)))
rear=shellshape.common(Part.makeBox(100,140,70,V(-50,-10,P['split_z']-70-P['seam_gap']/2)))
for x,y in P['screw_centers_xy']:
    boss=cylinder(2.5,18,(x,y,P['split_z']+.1)).common(outer.Shape)
    bore=cylinder(.85,18,(x,y,P['split_z']-.1))
    front=front.fuse(boss.cut(bore))
    clearance=cylinder(1.15,30,(x,y,-30));counterbore=cylinder(2.15,13,(x,y,-30))
    rear=rear.cut(clearance.fuse(counterbore))
feature('FingerShell',front.removeSplitter(),'shell','split shell; fastener bosses included, key supports and seam alignment pending')
feature('PalmShell',rear.removeSplitter(),'shell','split shell; clearance holes included, palm inlay and alignment pending')
print('Shell split, openings and key assemblies created',flush=True)

# Closed sloped top ring. Cross-sections retain the egg-shaped reference deck.
capbottom=profile('CapBottomProfile',103.7,0)
def topwire(y,inset):
    points=[]
    for i in range(72):
        u=capunit(2*math.pi*i/72);x=(26-inset)*u[0];z=(23-inset)*u[1]
        points.append(V(x,y+P['top_slope']*z,z))
    c=Part.BSplineCurve();c.interpolate(points,PeriodicFlag=True);return Part.Wire(c.toShape())
topouter=Part.makeLoft([capbottom.Shape,topwire(P['top_y'],0)],True)
topinner=Part.makeLoft([inner.Sections[-1].Shape,topwire(P['top_y']-P['wall'],P['wall'])],True)
topshape=topouter.cut(topinner)
normal=V(0,1,.2);normal.normalize()
for name,x,z in [('Left',-8.5,8),('Right',8.5,-10)]:
    contact=V(x,P['top_y']+P['top_slope']*z+1.5,z)
    key=local(rounded(20 if name=='Left' else 18,15,1.7,5),contact-normal*1.2,normal)
    stem=local(Part.makeBox(2.8,2.8,2.8,V(-1.4,-1.4,-4.0)),contact,normal)
    feature(name+'ThumbKey',key.fuse(stem),'key')
    topshape=topshape.cut(local(rounded(20.6 if name=='Left' else 18.6,15.6,14,5),contact-normal*10,normal))
    feature(name+'PCB',local(Part.makeBox(9,9,.8,V(-4.5,-4.5,0)),contact-normal*6.3,normal),'pcb','proposed separate 9x9 top switch board')
    feature(name+'Switch',local(Part.makeBox(5.2,5.2,1.5,V(-2.6,-2.6,0)),contact-normal*5.5,normal),'metal','SKQGABE010 body envelope')
mic_origin=V(-10,105,-2)
feature('MicrophonePCB',local(Part.makeBox(7,7,.8,V(-3.5,-3.5,0)),mic_origin,V(0,1,0)),'pcb','7x7 candidate PCB envelope')
feature('Microphone',box([4,1.2,3],[-10,106.4,-2]),'metal','IM69D130 body envelope; bottom acoustic port')
topshape=topshape.cut(cylinder(.7,14,(-10,103,-2),V(0,1,0)))
feature('TopCover',topshape.removeSplitter(),'shell','top switch apertures and microphone aperture; acoustic seal path pending')
for name,kind in [('main_board','pcb'),('battery','battery')]:
    spec=P[name];feature('MainPCB' if name=='main_board' else 'BatteryPack',box(spec['size'],spec['center']),kind,spec['status'])
feature('ESP32Module',box([18,19.2,3.2],[0,86,-5.9]),'metal','ESP32-S3-WROOM-1U-N16R8 body envelope')
feature('USBBoard',box([16,8,.8],[0,6,0]),'pcb','outline candidate')
feature('USBConnector',box([8.94,7.35,3.2],[0,3.675,2]),'metal','GCT USB4105 envelope')
feature('LRA',cylinder(5,3.7,(0,24,4.15)),'metal','C10-100 body envelope')
feature('LRASeat',cylinder(5.8,4.5,(0,24,3.7)).cut(cylinder(5.2,5,(0,24,4.0))),'fixture','seat; attachment to shell and wire routing pending')
bat=P['battery'];size=bat['size'];center=bat['center'];a=P['battery_allowance']
# Open cradle: avoids compressing the pouch with side walls. The floor is
# narrower than the protected pack; end stops and a soft strap locate it.
floor_z=center[2]-size[2]/2-.9
tray=box([28,46,.8],[center[0],center[1],floor_z])
for dy in (-22.6,22.6):
    tray=tray.fuse(box([18,.8,4],[center[0],center[1]+dy,floor_z+1.6]))
feature('BatteryTray',tray.removeSplitter(),'fixture','open cradle; 0.5 mm nominal under-pack gap; foam and retention strap pending; supplier swelling allowance not yet frozen')
doc.recompute()
records=[]
for p in parts:
    s=p.Shape
    records.append({'name':p.Name,'valid':s.isValid(),'solids':len(s.Solids),'volume_mm3':s.Volume,'bbox_mm':[s.BoundBox.XLength,s.BoundBox.YLength,s.BoundBox.ZLength],'status':p.DesignStatus})
native=OUT/'AIKEY_REVA.FCStd';doc.saveAs(str(native))
fail=[r for r in records if not r['valid'] or r['solids']!=1]
report={'status':'FAIL' if fail else 'PART_GEOMETRY_PASS_ASSEMBLY_REVIEW_PENDING','revision':P['revision'],'freecad':App.Version(),'parts':records,'keys':key_metadata,'invalid_parts':fail,'unfinished':['full component placement and ECAD exchange','assembly interference and fastening integration','seam alignment and top cover retention','key stops and support attachment','antenna/coax path and fixtures','wire routing and strain relief','LED optical path','reset actuator isolation','acoustic port/duct/PCB path','battery supplier fit and retention','strap and anchors'],'native_file':str(native)}
(ROOT/'reports/mechanical-build.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'native_file':str(native),'parts':len(parts),'invalid_parts':fail,'status':report['status']}),flush=True)
App.closeDocument(doc.Name)
doc=App.openDocument(str(native))
assert len(doc.getObject('Assembly').Group)==len(parts)
for p in doc.getObject('Assembly').Group:
    assert p.Shape.isValid(),p.Name
print('Native document reopened and part shapes read back',flush=True)

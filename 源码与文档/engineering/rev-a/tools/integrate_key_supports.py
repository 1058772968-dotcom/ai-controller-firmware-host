#!/usr/bin/env python3
"""Attach key carriers to shell ribs and a removable top-cover skirt."""
import sys,json,math
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import box,rounded
R=Path(__file__).resolve().parents[1];V=A.Vector
d=A.openDocument(str(R/'mechanical/AIKEY_REVA_DESIGN03.FCStd'))
g=d.Assembly;c=d.Construction
def hide(o):
    g.removeObject(o);c.addObject(o)
    if o.ViewObject:o.ViewObject.Visibility=False
def feature(name,shape,visible=False,status='prototype native geometry; load and print process require samples'):
    o=d.addObject('Part::Feature',name);o.Shape=shape
    o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=status
    (g if visible else c).addObject(o)
    if o.ViewObject:o.ViewObject.Visibility=visible
    return o
def matrix_scale_xz(shape,f):
    m=A.Matrix();m.A11=f;m.A33=f
    return shape.transformGeometry(m)
def frame(o):
    p=json.loads(o.LocalKeyFrame)
    return A.Placement(V(*p['origin_mm']),A.Rotation(*p['rotation_xyzw']))
def transform(s,p):
    v=s.copy();v.Placement=p.multiply(v.Placement);return v
def merge(name,objects):
    for obj in objects:
        print(json.dumps({'merge_input':obj.Name,'null':obj.Shape.isNull(),'solids':len(obj.Shape.Solids)}),flush=True)
    for o in objects:hide(o)
    shape=objects[0].Shape.copy()
    for obj in objects[1:]:
        shape=shape.fuse(obj.Shape,1e-7)
        print(json.dumps({'union_added':obj.Name,'valid':shape.isValid(),'solids':len(shape.Solids)}),flush=True)
        assert shape.isValid(),(name,obj.Name)
    # Keep boolean faces: OCC refinement of this trimmed sloping cover may
    # produce a shape that fails a fresh native validation after assignment.
    debug=R/'reports/cad-debug';debug.mkdir(exist_ok=True)
    shape.exportBrep(str(debug/(name+'-union.brep')))
    out=feature(name,shape,True)
    print(json.dumps({'assigned':name,'valid':out.Shape.isValid()}),flush=True)
    out.addProperty('App::PropertyLinkList','SourceParts');out.SourceParts=objects
    d.recompute()
    print(json.dumps({'recomputed':name,'valid':out.Shape.isValid(),'state':str(out.State)}),flush=True)
    assert out.Shape.isValid(),name
    assert len(out.Shape.Solids)==1,(name,len(out.Shape.Solids))
    out.DesignStatus='Integrated native B-rep union; source part links retained, rebuild with integrate_key_supports.py; nominal CAD verification only'
    return out
finger_parts=[d.FingerShell]
# Ribs enter the shell wall but end short of the cosmetic outer surface.
# This also avoids coincident B-spline exterior faces during native unions.
rib_limit=matrix_scale_xz(d.OuterEnvelope.Shape,.97)
for name in ('Voice','Side'):
    carrier=d.getObject(name+'Carrier');p=frame(carrier)
    rib=box(70,2.2,1.6,z=-8.65)
    for x in (-6.5,6.5):
        rib=rib.cut(Part.makeCylinder(.9,3,V(x,0,-9))).cut(Part.makeCylinder(1.7,.35,V(x,0,-8.65)))
    rib=transform(rib,p).common(rib_limit)
    finger_parts += [carrier,feature(name+'ShellSupportRib',rib)]
# A flat FPC seat in the front cavity; no RF clearance approval is inferred.
antenna_plate=box(8,48,.5,y=65.5,z=4.25)
for y in (56,85):
    antenna_plate=antenna_plate.fuse(box(60,2,1.2,y=y,z=3.55).common(rib_limit))
finger_parts.append(feature('AntennaCarrier',antenna_plate.removeSplitter()))
feature('AntennaPSA',box(7,47,.15,y=65.5,z=4.75),True,'0.15 mm adhesive allocation; confirm delivered antenna adhesive stack')
feature('AntennaFPC',box(7,47,.1,y=65.5,z=4.9),True,'Taoglas FXP73.07.0100A nominal 47x7x0.1 mm FPC; cable/connector separate, product RF tests pending')
finger=merge('FingerShellSupported',finger_parts)
print('Finger shell and rear key carriers joined',flush=True)

# Use the original cap boundary coordinates, normalized once from its native
# bottom wire; transverse scaling preserves the source asymmetric outline.
base=d.CapBottomProfile.Shape
b=base.BoundBox
def ring(s,rx,rz):
    pts=[]
    # CapBottomProfile is at sloped coordinate Y+0.2Z=103.7.
    for v in base.discretize(Number=100)[:-1]:
        x=v.x/24.5*rx;z=v.z/22.8*rz;pts.append(V(x,s-.2*z,z))
    curve=Part.BSplineCurve();curve.interpolate(pts,PeriodicFlag=True)
    return Part.Wire(curve.toShape())
levels=[(99.5,21.0,19.7),(103.7,22.7,21.0),(104.5,24.8,22.2)]
skirt_outer=Part.makeLoft([ring(*v) for v in levels],True,True)
skirt_inner=Part.makeLoft([ring(s,rx-1.2,rz-1.2) for s,rx,rz in levels],True,True)
skirt=skirt_outer.cut(skirt_inner)
# The native top-cover envelope uses the six source rings, reconstructed from
# its solid exterior by the same ring definition. This volume clips supports
# without removing any actual electronic or moving-key interference.
top_levels=[(103.7,24.5,22.8),(104.5,25.55,23),(106.2,26,23),(108.1,25.85,22.85),(109.25,25.15,22.2),(109.8,24.5,21.7)]
top_volume=Part.makeLoft([ring(*v) for v in top_levels],True,True)
inside=matrix_scale_xz(d.InteriorEnvelope.Shape,.98)
extension=inside.copy();extension.translate(V(0,.2,0));inside=inside.fuse(extension)
constraint=inside.fuse(matrix_scale_xz(top_volume,.99))
# Clearance envelope for the stationary body wall and existing M1.6 screw
# bosses. The 0.3 mm axial seam and 0.3 mm boss radial allowance are modelled
# geometry, not exemptions in the subsequent all-pairs collision check.
outer_extended=d.OuterEnvelope.Shape.copy();outer_extended.translate(V(0,.3,0))
body_keepout=d.OuterEnvelope.Shape.fuse(outer_extended).cut(matrix_scale_xz(d.InteriorEnvelope.Shape,.98))
for x in (-18,18):
    body_keepout=body_keepout.fuse(Part.makeCylinder(2.8,18.6,V(x,98,-5.2)))
voice_clearance=transform(rounded(22.6,15.6,2.4,2.5,z=-1.75),frame(d.VoiceKey))
body_keepout=body_keepout.fuse(voice_clearance)
feature('TopSupportClearanceEnvelope',body_keepout)
skirt=skirt.common(constraint).cut(body_keepout)
top_parts=[d.TopCover,feature('TopSupportSkirt',skirt)]
for name in ('Left','Right'):
    carrier=d.getObject(name+'Carrier');p=frame(carrier)
    rib=box(70,2.2,1.6,z=-8.65)
    for x in (-6.5,6.5):
        rib=rib.cut(Part.makeCylinder(.9,3,V(x,0,-9))).cut(Part.makeCylinder(1.7,.35,V(x,0,-8.65)))
    rib=transform(rib,p).common(constraint).cut(body_keepout)
    top_parts += [carrier,feature(name+'TopSupportRib',rib)]
top=merge('TopCoverSupported',top_parts)
print('Top cover skirt and thumb-key carriers joined',flush=True)
d.recompute();out=R/'mechanical/AIKEY_REVA_DESIGN04.FCStd';d.saveAs(str(out))
A.closeDocument(d.Name);d=A.openDocument(str(out))
for o in d.Assembly.Group:assert o.Shape.isValid(),o.Name
report={'status':'GEOMETRY_VALID_ASSEMBLY_CHECK_PENDING','native_file':str(out),'parts':len(d.Assembly.Group),
        'single_solid_shells':{n:len(d.getObject(n).Shape.Solids) for n in ('FingerShellSupported','TopCoverSupported')},
        'antenna_fpc_bbox_mm':[7,47,.1],'antenna_allocation':'Mechanical fit only; 100 mm cable and connector not yet routed, RF performance untested',
        'remaining':['native full interference and key sweep validation','top cover retention screws','all remaining board and battery retention','wiring and acoustic/optical paths']}
(R/'reports/mechanical-design04-build.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)

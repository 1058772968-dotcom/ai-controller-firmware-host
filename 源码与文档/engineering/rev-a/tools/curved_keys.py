"""Back caps follow the actual native shell, retaining the verified plunger frame.

Within the front-side clipping prism the shell patch is a height field along
the plunger axis. The underside is an exact translated copy of that patch.
Expanding its translation by travel gives the continuous linear swept band;
the planar plunger, retention flange and nib use their exact prism sweeps.
"""
import json,math
import FreeCAD as A,Part
from key_cartridge import box,rounded
V=A.Vector
def pose(shape,placement):
    out=shape.copy();out.Placement=placement.multiply(out.Placement);return out
def key_frame(obj):
    meta=json.loads(obj.LocalKeyFrame)
    return meta,A.Placement(V(*meta['origin_mm']),A.Rotation(*meta['rotation_xyzw']))
def curved_cap(doc,name,travel=0):
    obj=doc.getObject(name+'Key');meta,p=key_frame(obj);w,h=meta['outline_mm']
    lift=1.2 if name=='Voice' else .6
    upper=doc.OuterEnvelope.Shape.copy();upper.translate(V(0,0,lift))
    lower=upper.copy();lower.translate(p.Rotation.multVec(V(0,0,-.9-travel)))
    clip=pose(rounded(w,h,30,2.2,z=-15),p)
    # Clip first: subtracting two complete, almost coincident lofts can produce
    # a topologically valid but geometrically wrong OCC result on the Side cap.
    # The local clipped solid removes distant shell intersections from Boolean
    # classification, then a constant-thickness volume invariant detects loss.
    band=upper.common(clip).cut(lower.common(clip))
    if not band.isValid() or len(band.Solids)!=1:raise RuntimeError('Curved front cap is not a single valid band: '+name)
    projected_area=w*h-(4-math.pi)*2.2**2
    if abs(band.Volume-projected_area*(.9+travel))>.005:
        raise RuntimeError(f'Curved height-field band volume mismatch: {name}: {band.Volume}, expected {projected_area*(.9+travel)}')
    return band
def curved_key_sweep(doc,name,travel=0):
    _,p=key_frame(doc.getObject(name+'Key'))
    stem=box(3,3,3.3+travel,z=-3.8-travel)
    flange=rounded(6.8,6.8,.3+travel,1,z=-4.1-travel)
    nib=Part.makeCylinder(.8,.3+travel,V(0,0,-4.4-travel))
    return curved_cap(doc,name,travel).fuse(pose(stem.fuse(flange).fuse(nib),p))
def curved_guide(doc,name,side):
    original=doc.getObject(name+'Guide'+side).Shape
    _,p=key_frame(doc.getObject(name+'Key'));lift=1.2 if name=='Voice' else .6
    stop=doc.OuterEnvelope.Shape.copy();stop.translate(V(0,0,lift));stop.translate(p.Rotation.multVec(V(0,0,-.9-.55)))
    central=pose(rounded(8.5,8.5,25,1,z=-15),p)
    half=box(30,30,20,x=-15 if side=='L' else 15,z=-10)
    raised=rounded(8.5,8.5,2,1,z=-1.55).cut(box(3.2,3.2,10,z=-5)).common(half)
    new_center=original.common(central).fuse(pose(raised,p)).common(stop)
    result=original.cut(central).fuse(new_center)
    if not result.isValid() or len(result.Solids)!=1:raise RuntimeError('Curved guide invalid: '+name+side)
    return result

#!/usr/bin/env python3
"""Shared top-cover/body screws, captive nuts and two locating sleeves."""
from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import box,hex_prism
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
d=A.openDocument(str(R/'mechanical/AIKEY_REVA_DESIGN16.FCStd'));new=[];operations=[]
def unite(a,b,label):
    assert b.isValid() and b.Volume>1e-6,label
    s=a.fuse(b,1e-7);row={'operation':'union','label':label,'before_mm3':a.Volume,'tool_mm3':b.Volume,'after_mm3':s.Volume,'solids':len(s.Solids)};operations.append(row);print(row,flush=True)
    if not s.isValid():raise RuntimeError('Invalid union '+label)
    # OCC volume integration on trimmed B-splines is not exactly additive.
    # If the integrated mass bounds disagree, check retention of both operands
    # as geometric sets; a relative mass tolerance would hide missing material.
    if s.Volume<max(a.Volume,b.Volume)-.001 or s.Volume>a.Volume+b.Volume+.001:
        retained=[]
        for operand in (a,b):
            loss=operand.cut(s)
            retained.append({'missing_mm3':loss.Volume,'valid':loss.isNull() or loss.isValid()})
        row['operand_retention']=retained
        if any(not x['valid'] or x['missing_mm3']>1e-5 for x in retained):raise RuntimeError('Union material loss '+label)
    return s
def cut(a,b,label):
    v=overlap_volume(a,b)
    if v<1e-8:return a
    s=a.cut(b);row={'operation':'cut','label':label,'before_mm3':a.Volume,'tool_mm3':b.Volume,'after_mm3':s.Volume};operations.append(row);print(row,flush=True)
    tol=max(.005,a.Volume*1e-5)
    if not s.isValid() or s.Volume<a.Volume-b.Volume-tol or s.Volume>a.Volume+tol:raise RuntimeError('Cut integrity '+label)
    if overlap_volume(s,b)>1e-5:raise RuntimeError('Uncleared cutter '+label)
    return s
def feature(name,shape,status):
    if not shape.isValid() or len(shape.Solids)!=1:raise RuntimeError('Invalid '+name)
    o=d.addObject('PartDesign::Feature',name);o.Shape=shape;o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=status;d.Assembly.addObject(o);new.append(o);return o
for n in ('PalmShell','FingerShellSupported','TopCoverSupported'):
    h=d.addObject('PartDesign::Feature',n+'BeforeCaseFasteners');h.Shape=d.getObject(n).Shape.copy();d.Construction.addObject(h)
    if h.ViewObject:h.ViewObject.Visibility=False
palm=d.PalmShell.Shape.copy();finger=d.FingerShellSupported.Shape.copy();top=d.TopCoverSupported.Shape.copy()
# Two integral lid ears are captured by the two upper case screws. Soft pads
# occupy the designed axial clearance; the screw shanks provide positive
# pull-out retention independently of the foam's friction.
for sign,side in ((-1,'L'),(1,'R')):
    x=sign*18
    ear=box(4.4,7,1,x=x,y=100,z=-5.5).common(d.OuterEnvelope.Shape)
    hole=Part.makeCylinder(.95,5,V(x,98,-7))
    top=unite(top,ear,'top retention ear '+side)
    pocket=box(4.7,7.3,1.3,x=x,y=100,z=-5.65)
    palm=cut(palm,pocket,'palm lid-ear pocket '+side)
    finger=cut(finger,pocket,'finger lid-ear pocket '+side)
    top=cut(top,hole,'lid ear screw hole '+side)
    for suffix,z in (('Lower',-5.65),('Upper',-4.5)):
        pad=box(3.0,3.0,.15,x=x,y=98,z=z).cut(hole)
        feature('LidPad'+side+suffix,pad,'.15 mm installed closed-cell silicone foam shim; .20 mm free-thickness target, physical compression/creep qualification pending')
# Palm-side screw seats are raised into the existing cavity. The head is
# recessed inside the nominal outer enclosure at all four native axes.
centres=[(-14,6),(14,6),(-18,98),(18,98)]
for i,(x,y) in enumerate(centres,1):
    column=Part.makeCylinder(2.5,19.9,V(x,y,-25)).common(d.OuterEnvelope.Shape)
    palm=unite(palm,column,'case screw seat '+str(i))
    bore=Part.makeCylinder(.95,35,V(x,y,-30))
    counter=Part.makeCylinder(1.8,23.5,V(x,y,-30))
    palm=cut(palm,bore,'case clearance '+str(i));palm=cut(palm,counter,'case head recess '+str(i))
    finger=cut(finger,bore,'case threaded-axis clearance '+str(i))
    pocket=hex_prism(3.45,1.4,x,y,-3.05)
    # Nuts load from the case interior before PCB/battery insertion.
    entry=box(3.45,4.5,1.4,x=x,y=y+(2.25 if y<50 else -2.25),z=-3.05)
    finger=cut(finger,pocket,'case captive nut '+str(i));finger=cut(finger,entry,'case nut loading slot '+str(i))
    nut=hex_prism(3.2,1.3,x,y,-3.).cut(Part.makeCylinder(.85,2,V(x,y,-3.1)))
    feature('CaseNut'+str(i),nut,'M1.6 hex nut AF3.2 x1.3; no threads cut directly into printed housing')
    screw=Part.makeCylinder(.8,5,V(x,y,-6.5)).fuse(Part.makeCylinder(1.6,1.3,V(x,y,-7.8)))
    screw=screw.cut(box(.45,2.3,.5,x=x,y=y,z=-7.8).fuse(box(2.3,.45,.5,x=x,y=y,z=-7.8)))
    feature('CaseScrew'+str(i),screw,'M1.6 x5 pan-head; underside access, .3 mm diametral shaft clearance, full 1.3 mm nut engagement')
# Two turned locating sleeves share the lower screw axes. The screw heads
# retain the sleeves; their outer diameters align both case halves. These
# replace the rejected disconnected integral seam-key candidate.
tongues=[]
for i,x in enumerate((-14.,14.),1):
    bore=Part.makeCylinder(1.30,3.20,V(x,6,-6.6))
    palm=cut(palm,bore,'lower locating sleeve palm '+str(i))
    finger=cut(finger,bore,'lower locating sleeve finger '+str(i))
    sleeve=Part.makeCylinder(1.25,3.,V(x,6,-6.5)).cut(Part.makeCylinder(.90,3.2,V(x,6,-6.6)))
    feature('CaseLocatingSleeve'+str(i),sleeve,'Turned brass sleeve OD2.50 +/-0.02, ID1.80, length3.00 +/-0.05 mm; mating final bores2.60 +/-0.05, prototype fit qualification required')
    tongues.append({'type':'turned_brass_locating_sleeve','axis_xy_mm':[x,6],'outer_diameter_mm':2.5,'inner_diameter_mm':1.8,'length_mm':3,'nominal_radial_clearance_mm':.05})
# Seat columns were added after the lid-pocket operation. Clear the complete
# final palm union, preserving the intended 1.3 mm ear/foam stack.
for x in (-18,18):palm=cut(palm,box(4.7,7.3,1.3,x=x,y=100,z=-5.65),'final lid-ear pocket '+str(x))
for name,s in [('PalmShell',palm),('FingerShellSupported',finger),('TopCoverSupported',top)]:
    d.getObject(name).Shape=s
d.recompute()
invalid_final=[{'part':n,'valid':s.isValid(),'solid_volumes_mm3':[q.Volume for q in s.Solids]} for n,s in [('PalmShell',palm),('FingerShellSupported',finger),('TopCoverSupported',top)] if not s.isValid() or len(s.Solids)!=1]
if invalid_final:
    d.saveAs(str(R/'mechanical/AIKEY_REVA_DESIGN17_DIAGNOSTIC.FCStd'))
    raise RuntimeError('Disconnected/invalid final '+str(invalid_final))
d.recompute();checks=[]
for a in new:
    for b in d.Assembly.Group:
        if a==b or (b in new and new.index(b)<new.index(a)):continue
        if not a.Shape.BoundBox.intersect(b.Shape.BoundBox):continue
        v=overlap_volume(a.Shape,b.Shape);checks.append({'a':a.Name,'b':b.Name,'overlap_mm3':v});print(checks[-1],flush=True)
fail=[x for x in checks if x['overlap_mm3']>1e-5]
out=R/'mechanical/AIKEY_REVA_DESIGN17.FCStd';d.saveAs(str(out));A.closeDocument(d.Name);d=A.openDocument(str(out))
invalid=[o.Name for o in d.Assembly.Group if not o.Shape.isValid()]
report={'status':'FAIL' if fail or invalid else 'CASE_CLOSURE_LOCAL_PASS_FULL_DELTA_PENDING','native_file':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'parts':len(d.Assembly.Group),'local_checks':checks,'invalid':invalid,'boolean_operations':operations,
 'screws':{'count':4,'part':'M1.6 x5 pan head','axes_xy_mm':centres,'head_seat_z_mm':-6.5,'nut_z_mm':[-3,-1.7]},'lid_retention':'Two integral ears captured by upper case screws; .15 mm installed pads each face','registration':tongues,
 'assembly':'Install captive nuts in finger half first. Install subassemblies and route harnesses. Seat the top cover and its two ears, apply four lid shim pads, then place the two lower locating sleeves and close the palm half over them and tighten the four underside screws. Opening the case releases the top cover. Screw torque/foam compression require physical qualification.',
 'remaining':['Full assembly and key sweeps','Top cover and case removal-path verification','Printed fit, preload, fatigue and foam creep','Wire/coax and remaining power/reset/strap/optical integration']}
(R/'reports/mechanical-design17-build.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],flush=True)
sys.exit(bool(fail or invalid))

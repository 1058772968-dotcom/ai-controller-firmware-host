#!/usr/bin/env python3
"""Eliminate exterior intrusions without altering the source exterior surface."""
from pathlib import Path
import sys,json,hashlib,ast,math
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import box,hex_prism
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
d=A.openDocument(str(R/'mechanical/AIKEY_REVA_DESIGN17.FCStd'));rows=[]
tree=ast.parse((R/'tools/integrate_key_cartridges.py').read_text());ns={'A':A,'Part':Part,'V':V,'math':math}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('capunit','ring')],type_ignores=[]),'source_cap','exec'),ns)
rings=[(103.7,24.5,22.8),(104.5,25.55,23),(106.2,26,23),(108.1,25.85,22.85),(109.25,25.15,22.2),(109.8,24.5,21.7)]
exterior_top=Part.makeLoft([ns['ring'](*p) for p in rings],True,True)
def outside(s):
 q=s.cut(d.OuterEnvelope.Shape)
 return q.cut(exterior_top) if q.Solids else q
def setshape(name,s):
 if not s.isValid() or len(s.Solids)!=1:
  d.getObject(name).Shape=s;d.saveAs(str(R/'mechanical/AIKEY_REVA_DESIGN18_DIAGNOSTIC.FCStd'))
  raise RuntimeError('Invalid/disconnected '+name+' '+str([q.Volume for q in s.Solids]))
 o=d.getObject(name);old=d.addObject('PartDesign::Feature',name+'BeforeClearance');old.Shape=o.Shape.copy();d.Construction.addObject(old)
 if old.ViewObject:old.ViewObject.Visibility=False
 o.Shape=s
 print('Set',name,flush=True)
def cut(a,b,label):
 if overlap_volume(a,b)<1e-8:return a
 s=a.cut(b)
 if not s.isValid() or s.Volume<a.Volume-b.Volume-.02 or s.Volume>a.Volume+.02:raise RuntimeError('Cut integrity '+label)
 if overlap_volume(s,b)>1e-5:raise RuntimeError('Residual cutter '+label)
 return s
# Top-key guide lips extend only about0.021 mm beyond the source cap surface,
# at localZ -1.47087..-1.45. They are covered by the much larger keycap and
# form its existing .55mm hard stop. Removing them would alter that stop.
# Preserve these functional collar interfaces and validate their coverage,
# local height and complete motion separately in check_internal_envelope.py.
# Move the two lower mainboard nuts 1 mm toward the interior. Restore their old
# pocket volume where it intersects the nominal exterior, then create new
# inward-loading pockets. The original 5 mm screw still fully crosses the nut.
palm=d.PalmShell.Shape.copy()
for sign,side in ((-1,'L'),(1,'R')):
 x=sign*14;name='MainNut'+side+'60';o=d.getObject(name);s=o.Shape.copy();s.translate(V(0,0,1.0))
 if outside(s).Volume>1e-5:raise RuntimeError('Moved nut still outside '+name)
 filler=hex_prism(3.45,1.4,x,60,-11.51).common(d.OuterEnvelope.Shape)
 merged=palm.fuse(filler,1e-7)
 if not merged.isValid() or palm.cut(merged).Volume>1e-5:raise RuntimeError('Nut-pocket restoration failure')
 palm=merged
 bore=Part.makeCylinder(.90,8,V(x,60,-12))
 pocket=hex_prism(3.45,1.4,x,60,-10.51)
 entry=box(3.4,3.45,1.4,x=sign*12.7,y=60,z=-10.51)
 for label,c in [('bore',bore),('pocket',pocket),('entry',entry)]:palm=cut(palm,c,name+label)
 setshape(name,s);rows.append({'part':name,'translation_mm':[0,0,1],'nut_z_mm':[-10.5,-9.2],'screw_shaft_z_mm':[-11.2,-6.2],'full_engagement_mm':1.3,'outside_after_mm3':outside(s).Volume})
# Two DIN433 M1.6 washers set the existing screws back by .3 mm without
# cutting the top-cover load path. The clamp stays at its original .7 mm
# thickness; only its nonfunctional outer corner is trimmed to the exterior.
ret=d.MicRetainer.Shape.copy()
for side,x in [('L',-18.88),('R',-7.88)]:
 s=d.getObject('MicScrew'+side).Shape.copy();s.translate(V(0,-.3,0))
 if outside(s).Volume>1e-5:raise RuntimeError('Mic screw still outside')
 setshape('MicScrew'+side,s)
 washer=Part.makeCylinder(1.75,.3,V(x,105.7,-6),V(0,1,0)).cut(Part.makeCylinder(.85,.5,V(x,105.6,-6),V(0,1,0)))
 if not washer.isValid() or outside(washer).Volume>1e-5:raise RuntimeError('Mic washer outside/invalid')
 o=d.addObject('PartDesign::Feature','MicWasher'+side);o.Shape=washer;d.Assembly.addObject(o)
 o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus='DIN433 M1.6 stainless washer, nominal OD3.5 ID1.7 thickness0.3 mm; supplier dimensional tolerances and assembly preload require samples'
 rows.append({'part':'MicScrew'+side,'translation_mm':[0,-.3,0],'screw_end_y_mm':110.7,'nut_far_y_mm':110.35,'full_engagement_mm':1.3,'outside_after_mm3':outside(s).Volume,'washer':'DIN433 M1.6 OD3.5 ID1.7 t0.3'})
ret=ret.cut(outside(ret));setshape('MicRetainer',ret)
setshape('PalmShell',palm)
d.recompute();out=R/'mechanical/AIKEY_REVA_DESIGN18.FCStd';d.saveAs(str(out));A.closeDocument(d.Name);d=A.openDocument(str(out))
invalid=[o.Name for o in d.Assembly.Group if not o.Shape.isValid()]
report={'status':'FAIL' if invalid else 'EXTERIOR_REFINEMENT_LOCAL_PASS_FULL_CHECKS_PENDING','native_file':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'changes':rows,'invalid':invalid,'parts':len(d.Assembly.Group),'assembly_update':'Load lower mainboard nuts from the central interior before seating the PCB. Mic retainer remains0.7mm; fit two DIN433 M1.6x3.5x0.3mm washers under the original M1.6x5 screw heads.'}
(R/'reports/mechanical-design18-build.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
sys.exit(bool(invalid))

#!/usr/bin/env python3
"""Independent exact-volume oracle for added-material collision inheritance."""
import sys,json,random
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
R=Path(__file__).resolve().parents[1];V=A.Vector
rng=random.Random(20261005);rows=[]
old_a=Part.makeBox(2,2,2);old_b=Part.makeBox(2,2,2,V(4,0,0))
assert old_a.common(old_b).Volume==0
cases=[('pure_removal',old_a.cut(Part.makeCylinder(.7,3,V(1,1,-.5))),old_b),('translated_into_other',Part.makeBox(2,2,2,V(3,0,0)),old_b),('both_extend',old_a.fuse(Part.makeBox(2,1,1,V(2,.5,.5))),old_b.fuse(Part.makeBox(1,1,1,V(3,.5,.5)))),('containment',Part.makeBox(8,8,8,V(-1,-1,-1)),old_b)]
for i in range(24):
 a=old_a.copy();b=old_b.copy();a.translate(V(rng.uniform(-2,5),rng.uniform(-1,1),0));b.translate(V(rng.uniform(-3,2),0,rng.uniform(-1,1)));cases.append(('random_translation_'+str(i),a,b))
for name,a,b in cases:
 da=a.cut(old_a);db=b.cut(old_b)
 assert all(s.isNull() or s.isValid() for s in (a,b,da,db))
 upper=da.common(b).Volume+db.common(a).Volume
 oracle=a.common(b).Volume
 assert upper+1e-9>=oracle,(name,upper,oracle)
 decision=oracle if upper>0 else 0
 assert (decision>1e-5)==(oracle>1e-5)
 rows.append({'case':name,'added_region_upper_bound_mm3':upper,'full_exact_pair_mm3':oracle})
(R/'reports/delta-collision-bound-tests.json').write_text(json.dumps({'status':'PASS','cases':rows,'scope':'Set-difference collision bound; all 28 cases compared against full exact common, including pure cuts, motion, overlapping additions and containment.'},indent=2)+'\n')
print('PASS',len(rows))

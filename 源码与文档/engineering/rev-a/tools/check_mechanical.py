#!/usr/bin/env python3
"""Read saved geometry and report real solid intersections. No allow-list omissions."""
from itertools import combinations
import json
from pathlib import Path
import sys
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as App
import Part
ROOT=Path(__file__).resolve().parents[1]
doc=App.openDocument(str(ROOT/'mechanical/AIKEY_REVA.FCStd'))
parts=doc.getObject('Assembly').Group
collisions=[];checked=0
for a,b in combinations(parts,2):
    if not a.Shape.BoundBox.intersect(b.Shape.BoundBox):continue
    checked+=1
    s=a.Shape.common(b.Shape)
    if s.Volume>1e-4:
        record={'a':a.Name,'b':b.Name,'intersection_mm3':s.Volume}
        collisions.append(record);print(json.dumps(record),flush=True)
report={'native_file':str(ROOT/'mechanical/AIKEY_REVA.FCStd'),'scope':'nominal geometry only; no tolerance or assembly-path approval','intersection_threshold_mm3':1e-4,'parts':len(parts),'candidate_pairs_checked':checked,'collisions':collisions,'status':'FAIL' if collisions else 'NOMINAL_INTERSECTION_CHECK_PASS'}
(ROOT/'reports/mechanical-interference.json').write_text(json.dumps(report,indent=2)+'\n')
print(report['status'],flush=True)

#!/usr/bin/env python3
"""Geometric test of physical travel; no claim of switch force/tolerance validation."""
import sys,json,itertools
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import cartridge,box
R=Path(__file__).resolve().parents[1]
records=[]
for name,w,h,kind in [('Voice',22,15,'back'),('Side',8.5,21,'back'),('Left',24,19,'top'),('Right',20,17,'top')]:
    shapes=cartridge(name,w,h,R/f'electrical/exchange/aikey_{kind}_key.step')
    static=[]
    for (a,sa),(b,sb) in itertools.combinations(shapes.items(),2):
        if not sa.BoundBox.intersect(sb.BoundBox):continue
        volume=sa.common(sb).Volume
        if volume>1e-5:static.append({'a':a,'b':b,'mm3':volume})
    motion=[]
    # Local moving actuator swept volume: only the centered 2 mm actuator
    # and its downward compression are excluded from rigid switch interference.
    actuator=Part.makeCylinder(1.01,1.1,A.Vector(0,0,-5.1))
    for travel in (0,.1,.25,.45,.55,.56):
        key=shapes['Key'].copy();key.translate(A.Vector(0,0,-travel))
        hits=[]
        for other,shape in shapes.items():
            if other=='Key':continue
            fixed=shape.cut(actuator) if other=='PCBAssembly' else shape
            if not key.BoundBox.intersect(fixed.BoundBox):continue
            overlap=key.common(fixed).Volume
            if overlap>1e-5:hits.append({'part':other,'mm3':overlap})
        motion.append({'travel_mm':travel,'collisions':hits})
    # Upward flange stop must also work: 0.01 mm outward yields guide contact.
    outward=shapes['Key'].copy();outward.translate(A.Vector(0,0,.01))
    outward_volume=sum(outward.common(shapes[x]).Volume for x in ('GuideL','GuideR'))
    records.append({'name':name,'static':static,'motion':motion,'outward_stop_interference_mm3':outward_volume})
passed=all(not r['static'] and all(not m['collisions'] for m in r['motion'] if m['travel_mm']<=.55)
           and r['motion'][-1]['collisions'] and r['outward_stop_interference_mm3']>1e-5 for r in records)
report={'status':'PASS' if passed else 'FAIL','scope':'nominal geometry, central switch actuator compression is modeled as a moving interface; samples required for return force, friction, overtravel and tolerance fit',
        'switch_top_gap_mm':.055,'inward_hard_stop_mm':.55,'shim_mm':.3,'records':records}
(R/'reports/key-cartridge-motion.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
sys.exit(0 if passed else 1)

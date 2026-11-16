"""Read-only clearance probe for a single-bend top-deck light guide."""
from pathlib import Path
import sys,json
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
d=A.openDocument(str(R/'mechanical/AIKEY_REVA_DESIGN18.FCStd'))
def rod(a,b,r):
    v=b-a;return Part.makeCylinder(r,v.Length,a,v.normalize())
rows=[]
for z in [-12,-13,-14]:
    for x in [-4,-5,-6]:
        a,b,c=V(0,96.2,-9.4),V(0,96.2,z),V(x,116,z)
        q=rod(a,b,1.1).fuse(rod(b,c,1.1)).fuse(Part.makeSphere(1.1,b))
        hits=[]
        for o in d.Assembly.Group:
            if not q.BoundBox.intersect(o.Shape.BoundBox):continue
            v=overlap_volume(q,o.Shape)
            if v>1e-5:hits.append({'part':o.Name,'mm3':v})
        row={'outlet_xz':[x,z],'hits':hits};rows.append(row);print(row,flush=True)
(R/'reports/led-path-probe.json').write_text(json.dumps(rows,indent=2)+'\n')

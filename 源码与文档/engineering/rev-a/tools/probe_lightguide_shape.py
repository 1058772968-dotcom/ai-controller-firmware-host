from pathlib import Path
import sys,json
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from geometry_checks import overlap_volume
from lightguide_geometry import shapes
R=Path(__file__).resolve().parents[1]
d=A.openDocument(str(R/'mechanical/AIKEY_REVA_DESIGN18.FCStd'))
guide,cavity,shield,pads=shapes();rows=[]
for name,shape in [('guide',guide),('shield',shield)]:
    hits=[]
    for o in d.Assembly.Group:
        if not shape.BoundBox.intersect(o.Shape.BoundBox):continue
        v=overlap_volume(shape,o.Shape)
        if v>1e-5:hits.append({'part':o.Name,'mm3':v})
    row={'part':name,'valid':shape.isValid(),'solids':len(shape.Solids),'hits':hits}
    rows.append(row);print(row,flush=True)
(R/'reports/lightguide-shape-probe.json').write_text(json.dumps(rows,indent=2)+'\n')

#!/usr/bin/env python3
"""Check internal components against the original body and top exterior volumes."""
from pathlib import Path
import sys,json,hashlib,argparse,ast,math
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import thumb,key_sweep
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
ap=argparse.ArgumentParser();ap.add_argument('--revision',required=True);opt=ap.parse_args()
path=R/f'mechanical/AIKEY_REVA_DESIGN{opt.revision}.FCStd';d=A.openDocument(str(path))
# Load only the two pure geometry definitions from the actual top-cover
# construction source, without executing that script's document mutations.
source=R/'tools/integrate_key_cartridges.py';tree=ast.parse(source.read_text())
definitions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('capunit','ring')]
assert len(definitions)==2
ns={'A':A,'Part':Part,'V':V,'math':math}
exec(compile(ast.Module(body=definitions,type_ignores=[]),str(source),'exec'),ns)
rings=[(103.7,24.5,22.8),(104.5,25.55,23),(106.2,26,23),(108.1,25.85,22.85),(109.25,25.15,22.2),(109.8,24.5,21.7)]
top=Part.makeLoft([ns['ring'](*p) for p in rings],True,True)
excluded={'PalmShell','FingerShellSupported','TopCoverSupported','VoiceKey','SideKey','LeftKey','RightKey'}
rows=[];fail=[]
for o in d.Assembly.Group:
    if o.Name in excluded:continue
    # A contained solid bounding box proves every enclosed component point is
    # contained. This avoids clipping dozens of package solids individually.
    # Corner sampling alone would be insufficient for the concave enclosure.
    b=o.Shape.optimalBoundingBox()
    bound=Part.makeBox(b.XLength,b.YLength,b.ZLength,V(b.XMin,b.YMin,b.ZMin))
    outside=bound.cut(d.OuterEnvelope.Shape)
    if outside.Solids:outside=outside.cut(top)
    method='exact_solid_bounding_box_containment'
    if outside.Volume>1e-5 or (not outside.isNull() and not outside.isValid()):
        outside=o.Shape.cut(d.OuterEnvelope.Shape)
        if outside.Solids:outside=outside.cut(top)
        method='exact_component_shape_containment'
    volume=outside.Volume
    valid=outside.isNull() or outside.isValid()
    row={'part':o.Name,'outside_mm3':volume,'result_valid':valid,'method':method}
    collar_ok=False
    if o.Name in ('LeftGuideL','LeftGuideR','RightGuideL','RightGuideR') and volume>1e-5:
        # These are the existing key hard-stop lips in the key aperture.
        # Classify them only after proving cap coverage, stop height and full
        # travel; do not silently waive protruding internal components.
        keyname='Left' if o.Name.startswith('Left') else 'Right'
        meta=json.loads(o.LocalKeyFrame);p=A.Placement(V(*meta['origin_mm']),A.Rotation(*meta['rotation_xyzw']))
        local=outside.copy();local.Placement=p.inverse().multiply(local.Placement)
        w,h=meta['outline_mm'];covered=thumb(keyname,w-2,h-2,20,-12)
        uncovered=local.cut(covered).Volume;bounds=local.optimalBoundingBox()
        sweep=key_sweep(keyname,w,h,meta['inward_hard_stop_mm']);sweep.Placement=p.multiply(sweep.Placement)
        collision=overlap_volume(sweep,o.Shape)
        collar_ok=valid and uncovered<=1e-5 and bounds.ZMax<=-1.45+1e-5 and collision<=1e-5
        row['functional_key_collar']={'passed':collar_ok,'outside_reduced_cap_planform_mm3':uncovered,'local_z_mm':[bounds.ZMin,bounds.ZMax],'continuous_key_sweep_overlap_mm3':collision,'explanation':'Hard-stop lip within the key opening, hidden under the keycap footprint; not an internal fastener or an unintended exterior intrusion.'}
    rows.append(row)
    print(row,flush=True)
    if not valid or (volume>1e-5 and not collar_ok):fail.append(row)
report={'status':'FAIL' if fail else 'INTERNAL_CONTAINMENT_AND_KEY_COLLAR_INTERFACE_PASS','native_file':str(path),
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_top_geometry_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'checks':rows,'failures':fail,'excluded':sorted(excluded),
        'scope':'Internal component containment only. Primary housings are the exterior itself and keycaps intentionally project beyond it; their preservation/dimensions/motion are checked separately. No tolerance or manufacturing claim.'}
(R/f'reports/internal-envelope-design{opt.revision}.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],flush=True)
sys.exit(bool(fail))

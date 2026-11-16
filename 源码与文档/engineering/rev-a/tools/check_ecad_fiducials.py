#!/usr/bin/env python3
"""Verify exported outlines/holes and placements against a saved FreeCAD file."""
from pathlib import Path
import sys,json,hashlib,argparse
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
ap=argparse.ArgumentParser();ap.add_argument('--revision',required=True);opt=ap.parse_args()
source=R/'reports/ecad-fiducial-source.json';inputs=json.loads(source.read_text())
native=R/f'mechanical/AIKEY_REVA_DESIGN{opt.revision}.FCStd';doc=A.openDocument(str(native))
names={'aikey_main':['MainPCBAssembly'],'aikey_usb':['USBPCBAssembly'],'aikey_mic':['MicPCBAssembly'],
       'aikey_back_key':['VoicePCBAssembly','SidePCBAssembly'],'aikey_top_key':['LeftPCBAssembly','RightPCBAssembly']}
if doc.getObject('PowerPCBAssembly'):names['aikey_power']=['PowerPCBAssembly']
if doc.getObject('ResetPCBAssembly'):names['aikey_top_key'].append('ResetPCBAssembly')
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
rows=[];fail=[]
for b in inputs['boards']:
    if b['board'] not in names:continue
    assert digest(b['native_file'])==b['native_sha256']
    body=Part.Shape();body.read(b['body']['file']);fresh=Part.Shape();fresh.read(b['assembly']['file'])
    assert body.isValid() and fresh.isValid()
    ox,oy=b['aux_origin_mm'];pts=[V(x-ox,-(y-oy),0) for x,y in b['outline_corners_xy_mm']]
    w=(pts[1]-pts[0]).Length;h=(pts[2]-pts[0]).Length;t=b['thickness_mm']
    bb=body.optimalBoundingBox()
    edge_errors=[abs(bb.XMin-pts[0].x),abs(bb.XMax-pts[1].x),abs(bb.YMax-pts[0].y),abs(bb.YMin-pts[2].y)]
    assert max(edge_errors)<1e-5
    # KiCad's default mechanical body leaves outer copper/mask out. Preserve
    # that distinction and check a full-finished-thickness laminate gauge.
    assert abs(bb.ZMin)<1e-5 and 0<t-bb.ZLength<.15
    holes=[]
    for pad in b['pads']:
        dx,dy=pad['drill_mm']
        if not dx or not dy:continue
        x,y=pad['xy_mm'];centre=V(x-ox,-(y-oy),bb.ZLength/2)
        inside=body.isInside(centre,1e-7,False)
        holes.append({'ref':pad['ref'],'pin':pad['pin'],'local_mm':list(centre),'void_at_centre':not inside})
        if inside:fail.append('Missing hole '+b['board']+pad['ref']+'/'+pad['pin'])
    for name in names[b['board']]:
        obj=doc.getObject(name);placement=obj.Shape.Placement
        mapped=[placement.multVec(p) for p in pts]
        distances=[Part.Vertex(p).distToShape(obj.Shape)[0] for p in mapped]
        if max(distances)>1e-5:fail.append('Fiducial '+name)
        placed=fresh.copy();placed.Placement=placement.multiply(fresh.Placement)
        old=obj.Shape
        def sig(s):
            q=s.optimalBoundingBox()
            return [s.Volume,q.XMin,q.XMax,q.YMin,q.YMax,q.ZMin,q.ZMax]
        # Independent STEP re-export may reorder solids. Match actual volume
        # and six bounds, then compare the matching exact B-reps both ways.
        remaining=list(old.Solids);errors=[]
        for solid in placed.Solids:
            a=sig(solid)
            match=next((s for s in remaining if max(abs(x-y) for x,y in zip(a,sig(s)))<1e-4),None)
            if match is None:errors.append('No matching solid bounds/volume');continue
            delta=solid.cut(match).Volume+match.cut(solid).Volume
            if delta>1e-5:errors.append('B-rep symmetric difference '+str(delta))
            remaining.remove(match)
        if remaining:errors.append('Extra stored solids: '+str(len(remaining)))
        if errors:fail.append('STEP differs '+name)
        gauge=Part.makeBox(w,h,t,V(pts[0].x,pts[2].y,0));gauge.Placement=placement
        contacts=[]
        for other in doc.Assembly.Group:
            if other.Name==name or not gauge.BoundBox.intersect(other.Shape.BoundBox):continue
            # Other electrical parts are checked as their true assembly shapes;
            # full rectangular gauge intentionally keeps all copper-edge holes.
            v=overlap_volume(gauge,other.Shape)
            if v>1e-5:contacts.append({'other':other.Name,'overlap_mm3':v})
        if contacts:fail.append('Finished thickness gauge '+name)
        rows.append({'object':name,'board':b['board'],'native_board_sha256':b['native_sha256'],
                     'native_frame_translation_mm':list(placement.Base),'native_frame_rotation_xyzw':list(placement.Rotation.Q),
                     'source_fiducials_mm':[list(p) for p in pts],'assembly_fiducials_mm':[list(p) for p in mapped],
                     'native_fiducial_distances_mm':distances,'finished_board_thickness_mm':t,
                     'exported_body_thickness_mm':bb.ZLength,'step_shape_comparison_errors':errors,
                     'finished_thickness_gauge_collisions':contacts,'holes':holes})
        print(name,'fiducials',max(distances),'shape errors',errors,'thickness contacts',contacts,flush=True)
report={'status':'FAIL' if fail else 'NATIVE_ECAD_MCAD_FIDUCIAL_SHAPE_AND_THICKNESS_GAUGE_PASS',
        'native_file':str(native),'sha256':digest(native),'source_report_sha256':digest(source),'assemblies':rows,'failures':fail,
        'scope':f'{len(rows)} placed PCB assemblies from {len(set(r["board"] for r in rows))} saved KiCad board types. Exact re-exported component shape comparison, three noncollinear outline fiducials, native hole-centre voids and nominal finished-thickness rectangular gauges. Copper/mask topography, finished-board tolerance and physical assembly are not proven.'}
(R/f'reports/ecad-mcad-design{opt.revision}.json').write_text(json.dumps(report,indent=2)+'\n')
print(report['status'],flush=True)
sys.exit(bool(fail))

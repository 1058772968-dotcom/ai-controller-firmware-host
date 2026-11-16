#!/usr/bin/env python3
"""Read saved native boards and export geometry for independent MCAD checks.

Run with the bundled KiCad Python. This never saves or changes a board.
"""
from pathlib import Path
import hashlib,json,os,subprocess,argparse
import wx
app=wx.App(False)
import pcbnew as P
R=Path(__file__).resolve().parents[1]
OUT=R/'electrical/exchange/review-current';OUT.mkdir(exist_ok=True)
CLI='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
env=dict(os.environ,KICAD10_3DMODEL_DIR='/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels')
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
mm=lambda v:P.ToMM(v)
ap=argparse.ArgumentParser();ap.add_argument('--kinds',nargs='+',default=['main','usb','mic','top_key','back_key','power']);ap.add_argument('--append',action='store_true');opt=ap.parse_args()
dest_report=R/'reports/ecad-fiducial-source.json'
rows=json.loads(dest_report.read_text())['boards'] if opt.append else []
rows=[b for b in rows if b['board'] not in ['aikey_'+k for k in opt.kinds]]
for kind in opt.kinds:
    name='aikey_'+kind;path=R/'electrical'/name/(name+'.kicad_pcb')
    before=digest(path);board=P.LoadBoard(str(path))
    # GetBoardEdgesBoundingBox includes half the plotted stroke width. Read
    # centreline endpoints of this project's rectangular routed outlines.
    edges=[e for e in board.GetDrawings() if e.GetLayer()==P.Edge_Cuts]
    if len(edges)!=4 or any(e.GetShape()!=P.SHAPE_T_SEGMENT for e in edges):
        raise RuntimeError('Expected four native rectangular outline segments')
    points=[p for e in edges for p in (e.GetStart(),e.GetEnd())]
    x0,x1=min(mm(p.x) for p in points),max(mm(p.x) for p in points)
    y0,y1=min(mm(p.y) for p in points),max(mm(p.y) for p in points)
    origin=board.GetDesignSettings().GetAuxOrigin()
    corners=[[x0,y0],[x1,y0],[x0,y1]]
    pads=[]
    for f in board.GetFootprints():
        for pad in f.Pads():
            p=pad.GetPosition();hole=pad.GetDrillSize()
            pads.append({'ref':f.GetReference(),'pin':pad.GetNumber(),'net':pad.GetNetname(),
                         'xy_mm':[mm(p.x),mm(p.y)],'drill_mm':[mm(hole.x),mm(hole.y)]})
    item={'board':name,'native_file':str(path),'native_sha256':before,
          'aux_origin_mm':[mm(origin.x),mm(origin.y)],'outline_corners_xy_mm':corners,
          'thickness_mm':mm(board.GetDesignSettings().GetBoardThickness()),'pads':pads}
    for suffix,flags in (('',[]),('-body',['--board-only'])):
        dest=OUT/(name+suffix+'.step')
        cmd=[CLI,'pcb','export','step','--force','--drill-origin','--subst-models',*flags,'-o',str(dest),str(path)]
        proc=subprocess.run(cmd,capture_output=True,text=True,env=env)
        (R/'reports'/(name+suffix+'-exchange.log')).write_text(proc.stdout+proc.stderr)
        if proc.returncode or not dest.exists():raise RuntimeError(name+suffix+' export failed')
        item['body' if suffix else 'assembly']={'file':str(dest),'sha256':digest(dest)}
    if digest(path)!=before:raise RuntimeError('Read/export changed native board')
    rows.append(item);print(name+' exported and native SHA preserved',flush=True)
report={'status':'NATIVE_READBACK_AND_STEP_EXPORT_PASS_MCAD_CHECK_PENDING','boards':rows,
        'scope':'Native board edges, auxiliary origin, laminate thickness and drill centres; STEP excludes copper and fabrication tolerance.'}
(R/'reports/ecad-fiducial-source.json').write_text(json.dumps(report,indent=2)+'\n')

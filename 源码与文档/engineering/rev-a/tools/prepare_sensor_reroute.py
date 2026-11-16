#!/usr/bin/env python3
"""Keep valid routes, remove only reviewed MEMS offenders, export guarded DSN."""
from pathlib import Path
import json,re
from sexpr import parse,dump,children,one
R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_main';file=P/'aikey_main.kicad_pcb'
data=json.loads((R/'reports/sensor-land-review.json').read_text())
bad={v['uuid'] for v in data['under_body_violations']}
# Existing bottom-side-of-package 3V3 bridge crossed the new outward GND
# escapes (native sensor-fanout-drc); reroute it outside the escape fanout.
bad.add('fcea93ad-f7a1-4b9c-92d9-e5fa5b4ca759')
redo={'/IMU_CS','/IMU_INT1','/IMU_MOSI','/IMU_SCLK'}
t=parse(file.read_text());removed=[]
cleanup=R/'reports/sensor-route-drc.json'
if cleanup.exists():
    check=json.loads(cleanup.read_text())
    bad.update(i['uuid'] for v in check['violations'] if v['type']=='track_dangling' for i in v['items'])
def touches_body(item):
    if item[0]!='segment' or one(item,'layer')[1]!='F.Cu':return False
    a=one(item,'start');b=one(item,'end');x0,y0=map(float,a[1:3]);x1,y1=map(float,b[1:3]);dx,dy=x1-x0,y1-y0
    # Segment vs rectangle, expanded by half the 0.15 mm track width.
    lo,hi=0.,1.
    for p,q in [(-dx,x0-60.425),(dx,63.575-x0),(-dy,y0-73.175),(dy,75.825-y0)]:
        if abs(p)<1e-12:
            if q<0:return False
        elif p<0:lo=max(lo,q/p)
        else:hi=min(hi,q/p)
    return lo<=hi
for item in children(t,'segment')+children(t,'via'):
    if one(item,'uuid')[1] in bad or one(item,'net')[1] in redo or touches_body(item):
        removed.append(item);t.remove(item)
file.write_text(dump(t)+'\n')
import wx
app=wx.App(False)
import pcbnew as p
settings=(P/'aikey_main.kicad_pro').read_bytes();b=p.LoadBoard(str(file))
# Native radial escapes avoid the router applying its generic 0.15 mm keepout
# clearance inside a 0.35 mm land corridor. They remain physically contained in
# the approved pad corridors; the native keepout/clearance DRC is authoritative.
imu=next(fp for fp in b.GetFootprints() if fp.GetReference()=='U4')
escapes=[]
for pad in imu.Pads():
    if pad.GetNumber() in ('9','11'):continue
    start=pad.GetPosition();x,y=p.ToMM(start.x),p.ToMM(start.y)
    if x<61:end=(60.1,y)
    elif x>63:end=(63.9,y)
    elif y<74:end=(x,72.9)
    else:end=(x,76.1)
    track=p.PCB_TRACK(b);track.SetNet(pad.GetNet());track.SetLayer(p.F_Cu);track.SetWidth(p.FromMM(.15));track.SetStart(start);track.SetEnd(p.VECTOR2I(p.FromMM(end[0]),p.FromMM(end[1])));b.Add(track)
    escapes.append({'pad':pad.GetNumber(),'net':pad.GetNetname(),'start_mm':[x,y],'end_mm':end})
baseline=parse((R/'reports/history/before-sensor-land-review/aikey_main.kicad_pcb').read_text())
locked={str(one(item,'uuid')[1]) for item in children(baseline,'segment')+children(baseline,'via') if one(item,'locked') is not None}
for item in b.GetTracks():
    # Keep original protected power/USB routes fixed; allow earlier control
    # routes to be pushed aside. The just-created radial escapes stay fixed.
    ident=item.m_Uuid.AsString()
    item.SetLocked(ident in locked or any(item.GetStart()==p.VECTOR2I(p.FromMM(e['start_mm'][0]),p.FromMM(e['start_mm'][1])) and item.GetEnd()==p.VECTOR2I(p.FromMM(e['end_mm'][0]),p.FromMM(e['end_mm'][1])) for e in escapes) if isinstance(item,p.PCB_TRACK) and not isinstance(item,p.PCB_VIA) else ident in locked)
b.BuildConnectivity();p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(file),b)
(P/'aikey_main.kicad_pro').write_bytes(settings)
dsn=P/'aikey_main_sensor.dsn'
if not p.ExportSpecctraDSN(b,str(dsn)):raise RuntimeError('DSN export failed')
s=dsn.read_text().replace('(width 200)','(width 150)').replace('(clearance 200)','(clearance 150)').replace('(clearance 50 (type smd_smd))','(clearance 150 (type smd_smd))')
s=re.sub(r'\(clearance [\d.]+ \(type smd_smd\)\)', '(clearance 150 (type smd_smd))',s)
for name in ('In1.Cu','In2.Cu','In4.Cu'):
    s=s.replace('(layer '+name+'\n      (type signal)','(layer '+name+'\n      (type power)')
a=s.index('    (boundary');e=s.index('    (plane',a)
s=s[:a]+'    (boundary (path pcb 0  73800 -91800  50200 -91800  50200 -50200  73800 -50200  73800 -91800))\n'+s[e:]
dsn.write_text(s)
(R/'reports/sensor-reroute-preparation.json').write_text(json.dumps({'status':'ROUTING_REQUIRED','removed':removed,'radial_escapes':escapes,'dsn':str(dsn),'rules':'0.15 mm trace and clearance retained; reference planes remain reserved; MEMS keepouts exported'},indent=2)+'\n')
print('Removed',len(removed),'reviewed copper items. Native DRC required after routing.',flush=True)

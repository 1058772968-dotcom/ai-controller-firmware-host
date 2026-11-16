#!/usr/bin/env python3
from pathlib import Path
import json,hashlib,shutil
import wx
app=wx.App(False)
import pcbnew as p
R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_main';file=P/'aikey_main.kicad_pcb'
plan=json.loads((R/'reports/cs-route-plan.json').read_text())
if hashlib.sha256(file.read_bytes()).hexdigest()!=plan['source_native_sha256']:raise RuntimeError('Plan source changed')
backup=R/'reports/history/sensor-before-cs-routes';backup.mkdir(exist_ok=True)
if (backup/file.name).exists():raise RuntimeError('CS candidate routes already applied')
shutil.copy2(file,backup/file.name);settings=(P/'aikey_main.kicad_pro').read_bytes();b=p.LoadBoard(str(file))
xy=lambda v:p.VECTOR2I(p.FromMM(v[0]),p.FromMM(v[1]))
layers={'F.Cu':p.F_Cu,'In3.Cu':p.In3_Cu,'B.Cu':p.B_Cu}
for row in plan['plans']:
    net=b.FindNet(row['net'])
    if not net:raise RuntimeError('Missing CS net')
    for s in row['segments']:
        for a,c in zip(s['points'],s['points'][1:]):
            t=p.PCB_TRACK(b);t.SetStart(xy(a));t.SetEnd(xy(c));t.SetWidth(p.FromMM(plan['width_mm']));t.SetLayer(layers[s['layer']]);t.SetNet(net);t.SetLocked(True);b.Add(t)
    for point in row['vias']:
        v=p.PCB_VIA(b);v.SetPosition(xy(point));v.SetWidth(p.FromMM(plan['via_pad_mm']));v.SetDrill(p.FromMM(plan['via_drill_mm']));v.SetViaType(p.VIATYPE_THROUGH);v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetNet(net);v.SetLocked(True);b.Add(v)
b.BuildConnectivity();p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(file),b);(P/'aikey_main.kicad_pro').write_bytes(settings)
print('Applied CS candidate routes; run native DRC.')

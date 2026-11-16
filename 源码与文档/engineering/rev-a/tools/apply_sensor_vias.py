#!/usr/bin/env python3
from pathlib import Path
import json,hashlib,shutil
import wx
app=wx.App(False)
import pcbnew as p
R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_main';file=P/'aikey_main.kicad_pcb';plan=json.loads((R/'reports/sensor-via-plan.json').read_text())
if hashlib.sha256(file.read_bytes()).hexdigest()!=plan['source_native_sha256']:raise RuntimeError('Native board changed after candidate planning')
backup=R/'reports/history/sensor-before-local-vias';backup.mkdir(exist_ok=True)
if (backup/file.name).exists():raise RuntimeError('Local fanout already applied; inspect before repeating')
shutil.copy2(file,backup/file.name);settings=(P/'aikey_main.kicad_pro').read_bytes();b=p.LoadBoard(str(file));xy=lambda v:p.VECTOR2I(p.FromMM(v[0]),p.FromMM(v[1]))
for row in plan['plans']:
 net=b.FindNet(row['net'])
 if not net:raise RuntimeError('Missing net '+row['net'])
 for a,c in zip(row['points_mm'],row['points_mm'][1:]):
  t=p.PCB_TRACK(b);t.SetStart(xy(a));t.SetEnd(xy(c));t.SetWidth(p.FromMM(.15));t.SetLayer(p.F_Cu);t.SetNet(net);t.SetLocked(True);b.Add(t)
 if not row['reuse_via']:
  v=p.PCB_VIA(b);v.SetPosition(xy(row['via_center_mm']));v.SetWidth(p.FromMM(plan['rules']['via_pad_mm']));v.SetDrill(p.FromMM(plan['rules']['via_drill_mm']));v.SetViaType(p.VIATYPE_THROUGH);v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetNet(net);v.SetLocked(True);b.Add(v)
b.BuildConnectivity();p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(file),b);(P/'aikey_main.kicad_pro').write_bytes(settings)
print('Placed reviewed local fanout candidates; native DRC still required')

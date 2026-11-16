#!/usr/bin/env python3
"""Finish the six-layer router result; a new native DRC is mandatory."""
from pathlib import Path
import json
from sexpr import parse,dump,children,one
import wx
app=wx.App(False)
import pcbnew as p
r=Path(__file__).resolve().parents[1];d=r/'electrical/aikey_main';f=d/'aikey_main.kicad_pcb'
report=json.loads((r/'reports/main-board-drc.json').read_text())
ids={v['items'][0]['uuid'] for v in report['violations'] if v['type']=='via_dangling'}
tree=parse(f.read_text());removed=[]
for via in children(tree,'via'):
    if one(via,'uuid')[1] in ids:
        removed.append(str(one(via,'uuid')[1]));tree.remove(via)
f.write_text(dump(tree)+'\n')
settings=(d/'aikey_main.kicad_pro').read_bytes();b=p.LoadBoard(str(f))
net=b.FindNet('/3V3');xy=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y))
start=next(pad.GetPosition() for fp in b.GetFootprints() if fp.GetReference()=='R25' for pad in fp.Pads() if pad.GetNumber()=='1')
end=xy(58.78,76.8)
present=any(isinstance(v,p.PCB_VIA) and v.GetNetname()=='/3V3' and v.GetPosition()==end for v in b.GetTracks())
if not present:
    t=p.PCB_TRACK(b);t.SetNet(net);t.SetStart(start);t.SetEnd(end);t.SetWidth(p.FromMM(.2));t.SetLayer(p.F_Cu);b.Add(t)
    v=p.PCB_VIA(b);v.SetNet(net);v.SetPosition(end);v.SetWidth(p.FromMM(.6));v.SetDrill(p.FromMM(.3));v.SetViaType(p.VIATYPE_THROUGH);v.SetLayerPair(p.F_Cu,p.B_Cu);b.Add(v)
b.BuildConnectivity();p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(f),b)
(d/'aikey_main.kicad_pro').write_bytes(settings)
(r/'reports/main-route-finishing.json').write_text(json.dumps({'removed_redundant_single_layer_via_uuids':removed,'added':'R25 pad1 3V3 local power-plane via at (58.78,76.8)','requires':'native DRC after this mutation'},indent=2)+'\n')
print('Finishing applied; native DRC still required.')

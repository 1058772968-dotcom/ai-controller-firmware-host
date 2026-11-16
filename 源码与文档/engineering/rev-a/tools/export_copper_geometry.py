#!/usr/bin/env python3
"""Conservative placed-pad boxes and exact line/via dimensions for route review."""
from pathlib import Path
import json,hashlib,argparse
import wx
app=wx.App(False)
import pcbnew as p
R=Path(__file__).resolve().parents[1];ap=argparse.ArgumentParser();ap.add_argument('--board',default='aikey_main',choices=['aikey_main','aikey_usb']);opt=ap.parse_args();file=R/'electrical'/opt.board/(opt.board+'.kicad_pcb');b=p.LoadBoard(str(file));items=[]
pt=lambda a:[p.ToMM(a.x),p.ToMM(a.y)]
for fp in b.GetFootprints():
 for pad in fp.Pads():
  bb=pad.GetBoundingBox();items.append({'kind':'pad','ref':fp.GetReference(),'number':pad.GetNumber(),'net':pad.GetNetname(),'center':pt(pad.GetPosition()),'box':[p.ToMM(bb.GetX()),p.ToMM(bb.GetY()),p.ToMM(bb.GetRight()),p.ToMM(bb.GetBottom())],'layers':[b.GetLayerName(l) for l in pad.GetLayerSet().Seq() if p.IsCopperLayer(l)]})
for t in b.GetTracks():
 if isinstance(t,p.PCB_VIA):items.append({'kind':'via','net':t.GetNetname(),'center':pt(t.GetPosition()),'diameter':max(p.ToMM(t.GetWidth(l)) for l in (p.F_Cu,p.In1_Cu,p.In2_Cu,p.In3_Cu,p.In4_Cu,p.B_Cu)),'drill':p.ToMM(t.GetDrillValue()),'uuid':t.m_Uuid.AsString()})
 else:items.append({'kind':'track','net':t.GetNetname(),'start':pt(t.GetStart()),'end':pt(t.GetEnd()),'width':p.ToMM(t.GetWidth()),'layer':b.GetLayerName(t.GetLayer()),'uuid':t.m_Uuid.AsString()})
(R/'reports'/('main-copper-geometry.json' if opt.board=='aikey_main' else 'usb-copper-geometry.json')).write_text(json.dumps({'native_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'items':items},indent=2)+'\n');print('Exported',len(items),'copper features')

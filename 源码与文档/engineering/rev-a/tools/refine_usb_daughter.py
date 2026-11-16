#!/usr/bin/env python3
"""Keep all USB daughter component placements; improve reference planes and crossover."""
from pathlib import Path
import shutil,json,copy,uuid,subprocess
import wx
app=wx.App(False)
import pcbnew as p
from sexpr import parse,dump,one,children,CLI
from stackup_spec import install_stackup
R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_usb';file=P/'aikey_usb.kicad_pcb'
backup=R/'reports/history/before-usb-daughter';backup.mkdir(exist_ok=True)
if (backup/file.name).exists() and file.read_bytes()!=(backup/file.name).read_bytes():raise RuntimeError('Existing refinement requires review before rerun')
for src in (file,P/'aikey_usb.kicad_pro',P/'aikey_usb.kicad_sch'):
    if not (backup/src.name).exists():shutil.copy2(src,backup/src.name)
settings=(P/'aikey_usb.kicad_pro').read_bytes();b=p.LoadBoard(str(file));b.SetCopperLayerCount(4)
xy=lambda v:p.VECTOR2I(p.FromMM(v[0]),p.FromMM(v[1]))
def wire(net,pts,layer=p.F_Cu):
    for a,c in zip(pts,pts[1:]):
        t=p.PCB_TRACK(b);t.SetStart(xy(a));t.SetEnd(xy(c));t.SetWidth(p.FromMM(.23));t.SetLayer(layer);t.SetNet(b.FindNet(net));t.SetLocked(True);b.Add(t)
def via(net,at):
    v=p.PCB_VIA(b);v.SetPosition(xy(at));v.SetWidth(p.FromMM(.5));v.SetDrill(p.FromMM(.3));v.SetViaType(p.VIATYPE_THROUGH);v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetNet(b.FindNet(net));v.SetLocked(True);b.Add(v)
for t in list(b.GetTracks()):
    if t.GetNetname() in ('/USB_DP','/USB_DM'):b.Remove(t)
# D+ connects the mirrored contacts on top. D- crosses this bridge below it;
# its right contact joins at the exit via, eliminating the former third via.
wire('/USB_DP',[(57.25,56.28),(57.25,57.0),(57.1,57.15),(57.1,58.15),(58.4,58.15),(58.4,57.15),(58.25,57.0),(58.25,56.28)])
wire('/USB_DP',[(57.1,58.15),(57.1,59.3),(57.65,59.825)])
wire('/USB_DP',[(57.65,59.825),(56.756,60.45),(56.756,61.1),(57.5,61.1)])
wire('/USB_DM',[(57.75,56.28),(57.75,56.9),(57.7,57.5)])
wire('/USB_DM',[(58.75,56.28),(58.75,56.9),(59.1,57.5),(59.1,58.8)])
via('/USB_DM',(57.7,57.5));via('/USB_DM',(59.1,58.8))
wire('/USB_DM',[(57.7,57.5),(59.1,58.8)],p.B_Cu)
wire('/USB_DM',[(59.1,58.8),(58.35,59.825),(60,61.1)])
p.SaveBoard(str(file),b);(P/'aikey_usb.kicad_pro').write_bytes(settings)
t=parse(file.read_text())
source_zone=next(z for z in children(t,'zone') if one(z,'layer') and one(z,'layer')[1]=='F.Cu')
for layer in ('In1.Cu','In2.Cu'):
    z=copy.deepcopy(source_zone);one(z,'layer')[1]=layer;one(z,'uuid')[1]=str(uuid.uuid4())
    for filled in children(z,'filled_polygon'):z.remove(filled)
    t.append(z)
install_stackup(t,['F.Cu','In1.Cu','In2.Cu','B.Cu'],[.1,.474,.1]);file.write_text(dump(t)+'\n')
# Reopen/refill in the native CLI: this KiCad build returned an unwrapped
# SWIG pointer on the second in-process LoadBoard call.
subprocess.run([CLI,'pcb','drc','--refill-zones','--save-board','--schematic-parity','--severity-all','--format','json','--output',str(R/'reports/usb-daughter-drc.json'),str(file)],check=True)
print('USB daughter: four layers, unchanged 0.8 mm total and component positions; native DRC required.')

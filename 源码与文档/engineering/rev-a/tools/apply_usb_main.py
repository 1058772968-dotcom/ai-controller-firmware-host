#!/usr/bin/env python3
from pathlib import Path
import json,hashlib,shutil
from sexpr import parse,dump
from stackup_spec import install_stackup
import wx
app=wx.App(False)
import pcbnew as p
R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_main';file=P/'aikey_main.kicad_pcb'
plan=json.loads((R/'reports/usb-main-plan.json').read_text())
if hashlib.sha256(file.read_bytes()).hexdigest()!=plan['source_native_sha256']:raise RuntimeError('Native board changed after planning')
backup=R/'reports/history/before-usb-main';backup.mkdir(exist_ok=True)
if (backup/file.name).exists():raise RuntimeError('USB modification already applied')
shutil.copy2(file,backup/file.name);settings=(P/'aikey_main.kicad_pro').read_bytes()
t=parse(file.read_text());install_stackup(t,['F.Cu','In1.Cu','In2.Cu','In3.Cu','In4.Cu','B.Cu'],[.1,.11,.418,.11,.1]);file.write_text(dump(t)+'\n')
b=p.LoadBoard(str(file));xy=lambda v:p.VECTOR2I(p.FromMM(v[0]),p.FromMM(v[1]));usb={'/USB_DP','/USB_DM','/MCU_USB_DP','/MCU_USB_DM'}
for track in list(b.GetTracks()):
    if isinstance(track,p.PCB_VIA) and track.m_Uuid.AsString() in plan.get('resize_via_uuids',[]):track.SetWidth(p.FromMM(plan['edge_control_via_pad_mm']))
    elif track.m_Uuid.AsString()==plan['replace_track_uuid']:b.Remove(track)
    elif not isinstance(track,p.PCB_VIA) and track.GetNetname() in usb:track.SetWidth(p.FromMM(plan['width_mm']))
for a,c in zip(plan['tuning_points_mm'],plan['tuning_points_mm'][1:]):
    t=p.PCB_TRACK(b);t.SetStart(xy(a));t.SetEnd(xy(c));t.SetWidth(p.FromMM(plan['width_mm']));t.SetLayer(p.F_Cu);t.SetNet(b.FindNet('/USB_DP'));t.SetLocked(True);b.Add(t)
for point in plan['ground_vias_mm']:
    v=p.PCB_VIA(b);v.SetPosition(xy(point));v.SetWidth(p.FromMM(plan['via_pad_mm']));v.SetDrill(p.FromMM(plan['via_drill_mm']));v.SetViaType(p.VIATYPE_THROUGH);v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetNet(b.FindNet('/GND'));v.SetLocked(True);b.Add(v)
b.BuildConnectivity();p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(file),b);(P/'aikey_main.kicad_pro').write_bytes(settings)
print('Native USB candidates saved; DRC and stackup readback required.')

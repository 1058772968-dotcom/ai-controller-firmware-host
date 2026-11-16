#!/usr/bin/env python3
from pathlib import Path
import argparse
a=argparse.ArgumentParser();a.add_argument("--session",default="aikey_main.ses");opt=a.parse_args()
import wx
app=wx.App(False)
import pcbnew as p
r=Path(__file__).resolve().parents[1];d=r/'electrical/aikey_main';board=d/'aikey_main.kicad_pcb'
settings=(d/'aikey_main.kicad_pro').read_bytes()
b=p.LoadBoard(str(board));assert p.ImportSpecctraSES(b,str(d/opt.session))
b.BuildConnectivity();p.ZONE_FILLER(b).Fill(b.Zones());p.SaveBoard(str(board),b)
(d/'aikey_main.kicad_pro').write_bytes(settings)
print('Session imported, zones refilled; native DRC is authoritative.')

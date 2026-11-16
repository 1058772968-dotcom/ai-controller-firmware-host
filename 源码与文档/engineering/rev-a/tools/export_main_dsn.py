#!/usr/bin/env python3
"""Export current routing without rebuilding or deleting native board content."""
from pathlib import Path
import argparse,re
import wx
app=wx.App(False)
import pcbnew as p
R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_main'
ap=argparse.ArgumentParser();ap.add_argument('--name',required=True);args=ap.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9_]+',args.name):raise ValueError('Invalid DSN name')
b=p.LoadBoard(str(P/'aikey_main.kicad_pcb'));out=P/(args.name+'.dsn')
if not p.ExportSpecctraDSN(b,str(out)):raise RuntimeError('Native DSN export failed')
s=out.read_text().replace('(width 200)','(width 150)').replace('(clearance 200)','(clearance 150)')
s=re.sub(r'\(clearance [\d.]+ \(type smd_smd\)\)','(clearance 150 (type smd_smd))',s)
for name in ('In1.Cu','In2.Cu','In4.Cu'):s=s.replace('(layer '+name+'\n      (type signal)','(layer '+name+'\n      (type power)')
a=s.index('    (boundary');e=s.index('    (plane',a)
s=s[:a]+'    (boundary (path pcb 0  73800 -91800  50200 -91800  50200 -50200  73800 -50200  73800 -91800))\n'+s[e:]
out.write_text(s);print(out)

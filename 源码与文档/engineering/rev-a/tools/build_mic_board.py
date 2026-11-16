#!/usr/bin/env python3
"""7 x 7 mm PDM microphone board, native Infineon lands and acoustic port."""
from pathlib import Path
import wx
app=wx.App(False)
import pcbnew as pcb
from eda_project import Project
from sexpr import parse,dump,children,one,prop
r=Path(__file__).resolve().parents[1]
p=Project(r,'aikey_mic','AI KEY switched PDM microphone',[7,7],.8)
p.add_symbol('MIC','Sensor_Audio:IM69D130')
# Preserve the official footprint and make a named acoustic-annulus derivative.
# The 0.8 mm hole is unchanged. A 0.30 mm copper ring on radius 0.81 mm
# retains a continuous acoustic seal and >=0.26 mm drill-to-copper space.
original=prop(p.symbols['MIC'],'Footprint').split(':')[1];variant=original+'_AcousticRing03'
import subprocess
subprocess.run(['/usr/bin/python3',str(r/'tools/prepare_mic_land.py'),str(p.fp)],check=True)
for field in children(p.symbols['MIC'],'property'):
 if field[1]=='Footprint':field[2]='AIKEY:'+variant
p.add_symbol('C','Device:C','Capacitor_SMD:C_0402_1005Metric')
p.add_symbol('R','Device:R','Resistor_SMD:R_0402_1005Metric')
p.add_symbol('TP','Connector:TestPoint','TestPoint:TestPoint_Pad_D1.0mm')
p.add_symbol('PWR','power:PWR_FLAG')
p.part('MK1','MIC','IM69D130',{1:'PDM_RAW',2:'MIC_VDD',3:'MIC_CLK',4:'GND',5:'GND'},(101.6,76.2),(53.5,53.5),mpn='IM69D130V01XTSA1')
p.part('C1','C','100nF 10V',{1:'MIC_VDD',2:'GND'},(152.4,76.2),(53,51.4),back=True,mpn='GRM155R71A104KA01D')
p.part('R1','R','33',{1:'PDM_RAW',2:'PDM_DATA'},(203.2,76.2),(51.3,52.8),270,True,mpn='RC0402FR-0733RL')
for i,(net,x,y) in enumerate([('MIC_VDD',56.2,55.2),('MIC_CLK',52.6,55.2),('GND',54.4,56.2),('PDM_DATA',50.8,56.2)],1):
 p.part('TP'+str(i),'TP',net,{1:net},(63.5+(i-1)*40.64,119.38),(x,y),back=True,bom=False)
for i,net in enumerate(['MIC_VDD','GND'],1):p.part('#FLG0'+str(i),'PWR','PWR_FLAG',{1:net},(63.5+i*40.64,157.48),bom=False)
p.note('IM69D130 bottom port: 0.8 mm PCB acoustic hole at (54.18,53.5) mm.\nSELECT grounded; use left PDM slot. Mainboard supplies switched 3V3 and buffered clock.\n16k PCM generated on ESP32-S3 from 3.072 MHz PDM. R1 damps the outgoing data edge.\nAcoustic gasket must seal PCB back face to housing duct without covering port.\nNo conformal coat, glue, cleaning fluid or solder paste in the acoustic port.',50.8,185.42)
p.save();p.board()
def pd(ref,n):
 v=next(v for v in p.fps[ref].Pads() if v.GetNumber()==str(n)).GetPosition();return (pcb.ToMM(v.x),pcb.ToMM(v.y))
p.route('PDM_RAW',[pd('MK1',1),(52,51.6),(51.2,51.6)],width=.15);p.via('PDM_RAW',51.2,51.6)
p.route('PDM_RAW',[(51.2,51.6),(51.4,51.8),pd('R1',1)],pcb.B_Cu,.15)
p.route('PDM_DATA',[pd('R1',2),(51.4,54.6),(50.8,55.2),pd('TP4',1)],pcb.B_Cu,.15)
p.route('MIC_VDD',[pd('MK1',2),(52.7,52),(53.5,52)],width=.2);p.via('MIC_VDD',53.5,52)
p.route('MIC_VDD',[(53.5,52),pd('C1',1)],pcb.B_Cu,.2)
p.route('MIC_VDD',[(53.5,52),(56.2,52),pd('TP1',1)],pcb.B_Cu,.2)
p.route('MIC_CLK',[pd('MK1',3),(52,55.75)],width=.15);p.via('MIC_CLK',52,55.75)
p.route('MIC_CLK',[(52,55.75),pd('TP2',1)],pcb.B_Cu,.15)
p.route('GND',[pd('MK1',4),(54.18,54.35),(54.4,55),(54.4,55.75)],width=.15)
p.via('GND',54.8,51);p.via('GND',54.4,55.75);p.route('GND',[pd('TP3',1),(54.4,55.75)],pcb.B_Cu,.2)
for layer in [pcb.F_Cu,pcb.B_Cu]:
 z=pcb.ZONE(p.b);z.SetLayer(layer);z.SetNet(p.nets['GND']);z.SetLocalClearance(pcb.FromMM(.15));z.SetPadConnection(pcb.ZONE_CONNECTION_FULL)
 poly=z.Outline();poly.NewOutline()
 for x,y in [(50.3,50.3),(56.7,50.3),(56.7,56.7),(50.3,56.7)]:poly.Append(int(pcb.FromMM(x)),int(pcb.FromMM(y)))
 p.b.Add(z)
p.b.BuildConnectivity();pcb.ZONE_FILLER(p.b).Fill(p.b.Zones());p.save_board();print(p.out)

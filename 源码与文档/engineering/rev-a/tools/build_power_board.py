#!/usr/bin/env python3
"""Native 14x7 mm gold-contact power-enable daughterboard; no load-power switch."""
from pathlib import Path
import json,copy
import wx
app=wx.App(False)
import pcbnew as p
from eda_project import Project
from sexpr import Atom,parse,dump,children,one
R=Path(__file__).resolve().parents[1]
P=Project(R,'aikey_power','AI KEY power-enable switch', (14,7),thickness=.8,paper='A4')
fp='NKK_SS12SDP4_2.54mm'
t=parse(f'(footprint "{fp}" (version 20241229) (generator "pcbnew") (layer "F.Cu") (descr "NKK SS12SDP4; official Japanese SS catalog p640; 3 holes dia0.8 pitch2.54, body10.2x4") (attr through_hole) (property "Reference" "REF**" (at 0 -3 0) (layer "F.SilkS") (effects (font (size .8 .8) (thickness .12)))) (property "Value" "SS12SDP4" (at 0 3 0) (layer "F.Fab") (effects (font (size .8 .8) (thickness .12)))) (fp_rect (start -5.1 -2) (end 5.1 2) (stroke (width .1) (type default)) (layer "F.Fab")) (fp_rect (start -5.35 -2.25) (end 5.35 2.25) (stroke (width .05) (type default)) (layer "F.CrtYd")))')
for num,x in [(1,-2.54),(2,0),(3,2.54)]:t.append(parse(f'(pad "{num}" thru_hole {"rect" if num==1 else "circle"} (at {x} 0) (size 1.4 1.4) (drill .8) (layers "*.Cu" "*.Mask"))'))
t.append(parse('(model "${KIPRJMOD}/libraries/models/NKK_SS12SDP4.step" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))'))
(P.fp/(fp+'.kicad_mod')).write_text(dump(t)+'\n')
P.custom_symbol('PowerSwitch',[(1,'OFF_OPEN','passive','left'),(2,'COM_ENABLE','passive','left'),(3,'ON_SYS','passive','right')],'AIKEY:'+fp,'https://www.nkkswitches.co.jp/product/detailed/SS-12SDP4.html','NKK gold SPDT MBB. OFF throw must remain unconnected; do not ground it.')
P.add_symbol('Resistor','Device:R','Resistor_SMD:R_0402_1005Metric')
P.add_symbol('Terminal','Connector:TestPoint','TestPoint:TestPoint_Pad_D1.0mm')
P.part('SW1','PowerSwitch','SS12SDP4',{'1':None,'2':'PWR_EN','3':'SYS'},(101.6,63.5),(57,53.5),mpn='SS12SDP4')
P.part('R1','Resistor','10k 1%',{'1':'PWR_EN','2':'GND'},(101.6,96.52),(57,51),back=True,mpn='RC0402FR-0710KL')
for i,(net,y,sch) in enumerate([('SYS',51.5,(160.02,50.8)),('PWR_EN',53.5,(160.02,76.2)),('GND',55.5,(160.02,101.6))],1):
 P.part('TP'+str(i),'Terminal',net+'_WIRE',{'1':net},sch,(63.2,y),back=True,bom=False)
P.note('Mainboard TP11 -> TP1 SYS; TP10 -> TP2 PWR_EN; TP7 -> TP3 GND.\nOFF: pin1 open. ON: pin2-pin3. MBB must never short SYS to GND.\nR1 provides 0.30..0.44 mA contact load at SYS 3.0..4.4 V;\nmainboard R19 100k is in parallel (total 0.33..0.484 mA).\nSwitch controls TPS63802 EN; charger and fuel gauge remain powered.\nNominal supplied lead envelope extends 3.0 mm behind mounting plane.\n14 x 7 x 0.8 mm, 2-layer FR4; solder wire strain relief required.',50.8,127)
P.save();b=P.board()
def xy(ref,pin):
 v=next(x for x in P.fps[ref].Pads() if x.GetNumber()==str(pin)).GetPosition();return(p.ToMM(v.x),p.ToMM(v.y))
r1=xy('R1',1);r2=xy('R1',2)
P.route('PWR_EN',[xy('SW1',2),(57,52),r1],p.B_Cu)
P.route('PWR_EN',[xy('SW1',2),(57,54.5),(61.5,54.5),xy('TP2',1)],p.B_Cu)
P.route('SYS',[xy('SW1',3),(59.54,51.5),xy('TP1',1)],p.B_Cu)
P.route('GND',[r2,(55.5,51),(55.5,56.1),(62.6,56.1),xy('TP3',1)],p.B_Cu)
P.save_board()
print(json.dumps({'board':str(P.out/(P.name+'.kicad_pcb')),'resistor_pads':[r1,r2],'status':'NATIVE_SAVED_REOPENED_ERC_DRC_PENDING'}))

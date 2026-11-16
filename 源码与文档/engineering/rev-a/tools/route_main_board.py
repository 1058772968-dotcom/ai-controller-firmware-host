#!/usr/bin/env python3
"""Manual power/USB routes and planes before routing remaining control nets."""
from build_main_board import p,r
import pcbnew as pcb
import json
B=pcb.B_Cu;F=pcb.F_Cu
def pd(ref,n):
 a=next(v for v in p.fps[ref].Pads() if v.GetNumber()==str(n)).GetPosition()
 return (pcb.ToMM(a.x),pcb.ToMM(a.y))
def wire(net,pts,width=.2,layer=F):p.route(net,pts,layer,width)
def vi(net,xy):p.via(net,*xy)
# Short series resistors at the MCU; paired full-speed traces down left edge.
for net,n,y,ref,x in [('MCU_USB_DP',14,69.1,'R3',54.7),('MCU_USB_DM',13,67.83,'R4',55.8)]:
 wire(net,[pd('U1',n),(54.3,y)],.15);vi(net,(54.3,y))
 wire(net,[(54.3,y),(x,y+.4),pd(ref,1)],.15,B)
for net,ref,x in [('USB_DP','R3',54.7),('USB_DM','R4',55.8)]:
 wire(net,[pd(ref,2),(x,71.8)],.15,B);vi(net,(x,71.8))
wire('USB_DP',[(54.7,71.8),(51.2,71.8),(51.2,89),(51.6,89.4),(55.4,89.4),(56,90),pd('TP3',1)],.15)
wire('USB_DM',[(55.8,71.8),(55.8,72.4),(51.55,72.4),(51.55,88.6),(51.95,89),(57.4,89),(58,89.6),pd('TP4',1)],.15)
# Buck-boost switching loop: no via on either switch node.
wire('SW_L1',[pd('U3',9),(68.5,82.5)],.25)
wire('SW_L1',[(68.5,82.5),(69.2,81.815)],.25)
wire('SW_L1',[(69.2,81.815),pd('L1',1)],.5)
wire('SW_L2',[pd('U3',7),(68.5,83.5)],.25)
wire('SW_L2',[(68.5,83.5),(69.2,84.185)],.25)
wire('SW_L2',[(69.2,84.185),pd('L1',2)],.5)
wire('SYS',[pd('U3',10),(67.75,81.3)],.25)
wire('SYS',[(67.75,81.3),(67.5,81.05),pd('C7',1)],.5)
wire('3V3',[pd('U3',6),(67.75,84.8)],.25)
wire('3V3',[(67.75,84.8),(67.5,85.05),pd('C8',1)],.5)
for pt in [(66.8,85.8),(68.2,85.8)]:
 vi('3V3',pt);wire('3V3',[pd('C8',1),pt],.5)
wire('GND',[pd('U3',8),(70,83)],.25);vi('GND',(70,83))
wire('GND',[pd('U3',2),(65.3,82.5),(65.3,82.85),pd('U3',3)],.2);vi('GND',(65.3,82.85))
for ref,pt in [('C7',(67.5,78)),('C8',(67.5,88))]:
 wire('GND',[pd(ref,2),pt],.5);vi('GND',pt)
# Local Kelvin feedback stays clear of the inductor switching nodes.
wire('REG_FB',[pd('R17',2),(64,83.5),pd('R18',1)],.15)
wire('REG_FB',[(64,83.5),pd('U3',4)],.15)
wire('GND',[pd('R18',2),(64,85.65)],.2);vi('GND',(64,85.65))
vi('3V3',(64,80.5));wire('3V3',[pd('R17',1),(64,80.5)],.2)
# Charger input, battery and system rails. USB defaults to 100 mA in hardware.
wire('VBUS',[pd('U2',13),(56.75,77.7),(57.9,77.7),(58,76.8)],.2);vi('VBUS',(58,76.8))
wire('VBUS',[pd('C4',1),(52.5,77.2)],.5);vi('VBUS',(52.5,77.2))
wire('VBUS',[(58,76.8),(57.2,76.8),(57.2,75.2),(53.8,75.2),(52.5,77.2)],.5,pcb.In3_Cu)
wire('VBUS',[(52.5,77.2),(52.5,89.5),pd('TP1',1)],.5,B)
for n in [10,11]:wire('SYS',[pd('U2',n),(58.65,pd('U2',n)[1]),(58.65,80)],.25)
wire('SYS',[pd('C5',1),(58.65,78.5),(58.65,80)],.3);vi('SYS',(58.65,80))
wire('SYS',[(58.65,80),(58.65,82.5),(63,82.5),(65.5,80)],.5,B);vi('SYS',(65.5,80))
wire('SYS',[(65.5,80),pd('C7',1)],.5)
for n in [2,3]:wire('VBAT',[pd('U2',n),(53.8,pd('U2',n)[1]),(53.8,81.5)],.25)
wire('VBAT',[(53.8,81.5),pd('C6',1),(54.2,84.5)],.5);vi('VBAT',(54.2,84.5))
wire('VBAT',[(54.2,84.5),(54.2,87.7),(56.5,89.3),(60,89.3),pd('TP5',1)],.5,B)
for n in [2,3]:wire('VBAT',[pd('U6',n),(53.2,pd('U6',n)[1]),(53.2,87.775)],.2)
wire('VBAT',[pd('C13',1),(53.2,87.775),(53.2,88.3)],.3);vi('VBAT',(53.2,88.3))
wire('VBAT',[(53.2,88.3),(54.2,87.7)],.3,B)
# Explicit escape fanouts at the charger avoid routing traps around PowerPath.
for net,start,path in [
 ('CHG_ILIM',pd('U2',12),[(57.8,79.25),(57.8,78.85)]),
 ('CHG_TMR',pd('U2',14),[(56.25,77.7),(56.1,77.45),(56.35,76.8)]),
 ('PGOOD_N',pd('U2',7),[(56.25,81.95),(57,82.7)]),
 ('CHG_EN2',pd('U2',5),[(55.25,81.8),(54.95,82.1)]),
 ('CHG_EN1',pd('U2',6),[(55.8,82.5)]),
 ('CHG_ITERM',pd('U2',15),[(55.75,78),(55.5,77.6)])]:
 wire(net,[start]+path,.15);vi(net,path[-1])
for net,ref,num,pt,layer in [
 ('CHG_ILIM','R12',1,(60.3,81.1),F),
 ('CHG_TMR','R14',1,(58,76),F),
 ('PGOOD_N','R16',1,(60.6,85.5),B)]:
 wire(net,[pd(ref,num),pt],.15,layer);vi(net,pt)
wire('CHG_ITERM',[pd('R13',1),(61.2,81.3)],.15,B);vi('CHG_ITERM',(61.2,81.3))
wire('KEY_VOICE',[pd('U1',6),(54.35,58.94)],.15);vi('KEY_VOICE',(54.35,58.94))
wire('KEY_VOICE',[pd('R23',2),(60.9,65.8)],.15,B);vi('KEY_VOICE',(60.9,65.8))
for net,ref,num,pt,layer in [('GND','C10',2,(65.8,73.8),F),('3V3','C10',1,(64.8,76.2),F),('GND','C9',2,(60,72),F),('3V3','C9',1,(58.2,71.9),F),('3V3','U5',6,(64.5,73.3),B)]:
 wire(net,[pd(ref,num),pt],.2,layer);vi(net,pt)
# ESP32 supply and local bulk capacitor have two parallel through vias.
wire('3V3',[pd('U1',2),(55.3,53.86)],.5)
for pt in [(54.5,53.86),(55.3,53.86)]:vi('3V3',pt)
wire('3V3',[pd('C2',1),(55.3,52.5),(55.3,53.86)],.5,B)
wire('GND',[pd('C2',2),(53.7,51.2)],.3,B);vi('GND',(53.7,51.2))
wire('GND',[pd('C3',2),(53.7,53),(54.3,52.6)],.3,B);vi('GND',(54.3,52.6))
# Thermal vias in exposed ground pads and local capacitor returns.
for xy in [(55.6,79.6),(55.6,80.4),(56.4,79.6),(56.4,80.4),(55,87)]:vi('GND',xy)
for ref,xy in [('C4',(52.5,73.9)),('C5',(60.3,76.8)),('C6',(57.1,83.5)),('C13',(53.3,85.5))]:
 wire('GND',[pd(ref,2),xy],.3);vi('GND',xy)
# Ground reference plane and 3V3 distribution. Zone clearances retain the
# declared 0.15 mm rule; the router must respect pre-routed power and USB.
for layer,net in [(pcb.In1_Cu,'GND'),(pcb.In2_Cu,'3V3'),(pcb.In4_Cu,'GND')]:
 zone=pcb.ZONE(p.b);zone.SetLayer(layer);zone.SetNet(p.nets[net]);zone.SetLocalClearance(pcb.FromMM(.15));zone.SetThermalReliefGap(pcb.FromMM(.2));zone.SetThermalReliefSpokeWidth(pcb.FromMM(.25));zone.SetPadConnection(pcb.ZONE_CONNECTION_FULL)
 poly=zone.Outline();poly.NewOutline()
 for x,y in [(50.5,50.5),(73.5,50.5),(73.5,91.5),(50.5,91.5)]:poly.Append(int(pcb.FromMM(x)),int(pcb.FromMM(y)))
 p.b.Add(zone)
p.b.BuildConnectivity();pcb.ZONE_FILLER(p.b).Fill(p.b.Zones())
for t in p.b.GetTracks():t.SetLocked(True)
p.save_board()
assert pcb.ExportSpecctraDSN(p.b,str(p.out/'aikey_main.dsn'))
f=p.out/'aikey_main.dsn';s=f.read_text()
s=s.replace('(width 200)','(width 150)').replace('(clearance 200)','(clearance 150)').replace('(clearance 50 (type smd_smd))','(clearance 150 (type smd_smd))')
s=s.replace('    (boundary\n','    (autoroute_settings (fanout on) (autoroute on) (postroute off) (vias on) (layer_rule In1.Cu (active off)))\n    (boundary\n',1)
for reserved in ['In1.Cu','In2.Cu','In4.Cu']:
 s=s.replace('(layer '+reserved+'\n      (type signal)','(layer '+reserved+'\n      (type power)')
# DSN routing boundary is inset from the physical board, so the router's
# generic clearance cannot place vias closer than the native edge rule.
a=s.index('    (boundary');b=s.index('    (plane',a)
s=s[:a]+'    (boundary (path pcb 0  73800 -91800  50200 -91800  50200 -50200  73800 -50200  73800 -91800))\n'+s[b:]
f.write_text(s)
print('Manual routes and planes saved; native DRC required before autorouting.')

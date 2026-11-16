#!/usr/bin/env python3
from pathlib import Path
import wx
app=wx.App(False)
import pcbnew as pcb
from eda_project import Project
from sexpr import parse,dump,children,one,prop,Atom
import json
r=Path(__file__).resolve().parents[1]
p=Project(r,'aikey_usb','AI KEY USB-C full-speed interface',[16,13],.8)
p.add_symbol('USB','Connector:USB_C_Receptacle_USB2.0_16P','Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal')
# Local DFM derivative: preserve hole centers/diameters and signal/power lands.
# Only chamfer the ground-land corner nearest each locating peg. The full
# manufacturer footprint is retained alongside this explicitly named variant.
original=prop(p.symbols['USB'],'Footprint').split(':')[1]
variant=original+'_GroundCornerDFM'
fp=parse((p.fp/(original+'.kicad_mod')).read_text());fp[1]=variant
for padnode in children(fp,'pad'):
    if padnode[1] not in ('A1','B12','A12','B1'):continue
    padnode[3]=Atom('roundrect')
    padnode.append(parse('(chamfer_ratio 0.48)'))
    corner='bottom_right' if padnode[1] in ('A1','B12') else 'bottom_left'
    padnode.append(parse(f'(chamfer {corner})'))
(p.fp/(variant+'.kicad_mod')).write_text(dump(fp)+'\n')
for field in children(p.symbols['USB'],'property'):
    if field[1]=='Footprint':field[2]='AIKEY:'+variant
(r/'reports/usb-footprint-dfm.json').write_text(json.dumps({'source':'KiCad 10.0.6 official GCT USB4105 footprint','manufacturer_drawing':'https://gct.co/files/drawings/usb4105.pdf','variant':variant,'change':'Only peg-facing corners of duplicated GND pads A1/B12/A12/B1 receive a 0.48-width chamfer. NPTH and pad centers, pad size, signal and VBUS lands unchanged.','reason':'Maintain project 0.25 mm drill-to-copper clearance; no DRC exclusions or relaxed clearances.','affected_pad_nominal_area_mm2':.6*1.15,'maximum_removed_triangle_mm2':.5*(.6*.48)**2,'qualification':'Native DRC to be rerun; solder joint assembly validation requires prototype.'},indent=2)+'\n')
p.add_symbol('R','Device:R','Resistor_SMD:R_0402_1005Metric')
p.add_symbol('ESD','Power_Protection:TPD2EUSB30')
p.add_symbol('TP','Connector:TestPoint','TestPoint:TestPoint_Pad_D1.0mm')
nets={n:None for n in ['A8','B8']}
for suffix,net in [('1','GND'),('4','VBUS'),('6','USB_DP'),('7','USB_DM'),('9','VBUS'),('12','GND')]:
    for row in 'AB':nets[row+suffix]=net
nets.update(A5='CC1',B5='CC2',SH='GND')
p.part('J1','USB','USB4105-GF-A',nets,(76.2,66.04),(58,52),180,mpn='USB4105-GF-A',datasheet='https://gct.co/connector/usb4105')
p.part('R1','R','5.1k 1%',{1:'CC1',2:'GND'},(124.46,55.88),(61.4,58),mpn='RC0402FR-075K1L')
p.part('R2','R','5.1k 1%',{1:'CC2',2:'GND'},(149.86,55.88),(54.4,58),180,mpn='RC0402FR-075K1L')
p.part('U1','ESD','TPD2EUSB30DRTR',{1:'USB_DP',2:'USB_DM',3:'GND'},(193.04,66.04),(58,58.8),mpn='TPD2EUSB30DRTR')
for i,(net,x) in enumerate([('VBUS',52.5),('GND',55),('USB_DP',57.5),('USB_DM',60)],1):
    p.part('TP'+str(i),'TP',net,{1:net},(55.88+(i-1)*40.64,109.22),(x,60.5),bom=False)
p.note('USB 2.0 full speed, 12 Mbit/s. USB-C sink, CC1/CC2 each 5.1k.\nVBUS/GND/DP/DM solder terminals to mainboard.\nShield directly grounded. SBU1/SBU2 not connected.\nPaired 90-ohm USB cable <= 100 mm; strain relief required.\nNo USB PD, video Alt Mode, or USB 3.x support.',50.8,137.16)
p.save();p.board()
# D+ stays on the component layer. D- crosses its mirror pair on the back.
p.route('USB_DP',[(57.25,55.68),(57.25,56.4),(57.1,56.55),(57.1,57.55),(58.4,57.55),(58.4,56.55),(58.25,56.4),(58.25,55.68)],width=.15)
p.route('USB_DP',[(57.1,57.55),(57.1,58.7),(57.65,59.225),(57.5,60.5)],width=.15)
p.route('USB_DM',[(57.75,55.68),(57.75,56.3),(57.7,56.9)],width=.15)
p.route('USB_DM',[(58.75,55.68),(58.75,56.3),(59.1,56.9)],width=.15)
for x,y in [(57.7,56.9),(59.1,56.9),(59.1,58.8)]:p.via('USB_DM',x,y)
p.route('USB_DM',[(57.7,56.9),(59.1,56.9),(59.1,58.8)],pcb.B_Cu,.15)
p.route('USB_DM',[(59.1,58.8),(58.35,59.225),(59,59.225),(60,60.5)],width=.15)
# Power is deliberately routed around the differential pair, not across it.
for x in [55.6,60.4]:
    p.route('VBUS',[(x,55.68),(x,56.8)],width=.4);p.via('VBUS',x,56.8)
p.route('VBUS',[(55.6,56.8),(53.3,59.1),(52.5,59.1)],pcb.B_Cu,.4)
p.route('VBUS',[(60.4,56.8),(62.5,58.9),(62.5,61.2),(52.5,61.2),(52.5,59.1)],pcb.B_Cu,.4)
p.via('VBUS',52.5,59.1);p.route('VBUS',[(52.5,59.1),(52.5,60.5)],width=.4)
def pad(ref,num):
    a=next(a for a in p.fps[ref].Pads() if a.GetNumber()==str(num)).GetPosition()
    return (pcb.ToMM(a.x),pcb.ToMM(a.y))
p.route('CC1',[(59.25,55.68),(59.25,56.3),(59.85,56.65),(59.85,57.5),pad('R1',1)],width=.15)
p.route('CC2',[(56.25,55.68),(56.25,56.4),(56.4,56.55),(56.4,57.3),pad('R2',1)],width=.15)
p.via('GND',58,58.3);p.route('GND',[(58,58.3),pad('U1',3)],width=.2)
# Leave copper margin below the connector shell slots.
for obj in list(p.b.GetFootprints())+list(p.b.GetTracks()):obj.Move(p.xy(0,.6))
for component in p.parts:
    if component['pcb'] is not None:
        component['pcb']=(component['pcb'][0],component['pcb'][1]+.6)
for layer in [pcb.F_Cu,pcb.B_Cu]:
    zone=pcb.ZONE(p.b);zone.SetLayer(layer);zone.SetNet(p.nets['GND']);zone.SetLocalClearance(pcb.FromMM(.15));zone.SetThermalReliefGap(pcb.FromMM(.2));zone.SetThermalReliefSpokeWidth(pcb.FromMM(.2));zone.SetPadConnection(pcb.ZONE_CONNECTION_FULL)
    poly=zone.Outline();poly.NewOutline()
    for x,y in [(50.3,50.3),(65.7,50.3),(65.7,62.7),(50.3,62.7)]:poly.Append(int(pcb.FromMM(x)),int(pcb.FromMM(y)))
    p.b.Add(zone)
p.b.BuildConnectivity();pcb.ZONE_FILLER(p.b).Fill(p.b.Zones());p.save_board()
print(p.out)

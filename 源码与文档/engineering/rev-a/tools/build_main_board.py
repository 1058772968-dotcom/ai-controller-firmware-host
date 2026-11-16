#!/usr/bin/env python3
"""Mainboard native schematic and component placement. Routing is separate."""
from pathlib import Path
import json
import wx
app=wx.App(False)
from eda_project import Project
from custom_components import add_custom,footprint
from sexpr import children,one,prop,parse,dump
r=Path(__file__).resolve().parents[1]
p=Project(r,'aikey_main','AI KEY ESP32-S3 controller, power and sensing',[24,42],1,6,'A1')
for alias,source,fp in [
 ('ESP','RF_Module:ESP32-S3-WROOM-1','RF_Module:ESP32-S3-WROOM-1U'),
 ('BQ','Battery_Management:BQ24074RGT',None),
 ('DRV','Driver:DRV2605LDGS','Package_SO:TSSOP-10_3x3mm_P0.5mm'),
 ('LOAD','Power_Management:TPS22919DCK',None),
 ('BUF','74xGxx:74LVC1G125','Package_TO_SOT_SMD:SOT-353_SC-70-5'),
 ('FET','Transistor_FET:2N7002','Package_TO_SOT_SMD:SOT-23'),
 ('R','Device:R','Resistor_SMD:R_0402_1005Metric'),
 ('C','Device:C','Capacitor_SMD:C_0402_1005Metric'),
 ('C6','Device:C','Capacitor_SMD:C_0603_1608Metric'),
 ('L','Device:L',''),
 ('TP','Connector:TestPoint','TestPoint:TestPoint_Pad_D1.0mm'),
 ('PWR','power:PWR_FLAG',None)]:p.add_symbol(alias,source,fp)
add_custom(p)
# Datasheet Document 769-2 (2026-03-10), recommended 0.98 x 3.4
# lands on 2.37 mm centers; body maximum 4.3 mm.
lfp=footprint(p,'Coilcraft_XFL4015',(4.3,4.3),[(1,-1.185,0,.98,3.4),(2,1.185,0,.98,3.4)],'Coilcraft Doc769-2 2026-03-10 recommended land pattern')
for f in children(p.symbols['L'],'property'):
 if f[1]=='Footprint':f[2]=lfp
# Manufacturable thermal-via derivative: 0.3 mm plated drills in unchanged
# 0.6 mm lands. Keep the original official asset for comparison.
base=prop(p.symbols['ESP'],'Footprint').split(':')[1];variant=base+'_ThermalVia03'
fp=parse((p.fp/(base+'.kicad_mod')).read_text());fp[1]=variant
for pad in children(fp,'pad'):
 if one(pad,'drill') is not None:one(pad,'drill')[1]=.3
(p.fp/(variant+'.kicad_mod')).write_text(dump(fp)+'\n')
for f in children(p.symbols['ESP'],'property'):
 if f[1]=='Footprint':f[2]='AIKEY:'+variant
passives=json.loads((r/'spec/passive-parts.json').read_text())
pinplan=json.loads((r/'spec/board.json').read_text())['pins']
gpio={v:k for k,v in pinplan.items()}
esp={}
for sub in children(p.symbols['ESP'],'symbol'):
 for pin in children(sub,'pin'):
  num=str(one(pin,'number')[1]);name=str(one(pin,'name')[1])
  if name=='GND':net='GND'
  elif name=='3V3':net='3V3'
  elif name=='EN':net='MCU_EN'
  elif name=='USB_D-':net='MCU_USB_DM'
  elif name=='USB_D+':net='MCU_USB_DP'
  elif name=='TXD0':net='UART_TX'
  elif name=='RXD0':net='UART_RX'
  elif name=='IO0':net='BOOT_N'
  elif name.startswith('IO'):net=gpio.get(int(name[2:]))
  else:raise ValueError(name)
  esp[num]=net
p.part('U1','ESP','ESP32-S3-WROOM-1U-N16R8',esp,(101.6,91.44),(62,61),mpn='ESP32-S3-WROOM-1U-N16R8',datasheet='https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf')
p.part('U2','BQ','BQ24074RGTR',{1:'BATT_NTC',2:'VBAT',3:'VBAT',4:'GND',5:'CHG_EN2',6:'CHG_EN1',7:'PGOOD_N',8:'GND',9:'CHG_N',10:'SYS',11:'SYS',12:'CHG_ILIM',13:'VBUS',14:'CHG_TMR',15:'CHG_ITERM',16:'CHG_ISET',17:'GND'},(284.48,76.2),(55.5,79),mpn='BQ24074RGTR')
p.part('U3','TPS63802','TPS63802DLAR',{1:'PWR_EN',2:'GND',3:'GND',4:'REG_FB',5:'REG_PG',6:'3V3',7:'SW_L2',8:'GND',9:'SW_L1',10:'SYS'},(462.28,76.2),(67,85),mpn='TPS63802DLAR')
p.part('U4','LSM6DSV16X','LSM6DSV16XTR',{1:'IMU_MISO',2:'GND',3:'GND',4:'IMU_INT1',5:'3V3',6:'GND',7:'GND',8:'3V3',9:None,10:'3V3',11:None,12:'IMU_CS',13:'IMU_SCLK',14:'IMU_MOSI'},(101.6,251.46),(62,74.5),mpn='LSM6DSV16XTR')
p.part('U5','DRV','DRV2605LDGSR',{1:'HAPTIC_REG',2:'I2C_SCL',3:'I2C_SDA',4:'GND',5:'HAPTIC_EN',6:'3V3',7:'LRA_P',8:'GND',9:'LRA_N',10:'3V3'},(284.48,251.46),(68,76),back=True,mpn='DRV2605LDGSR')
p.part('U6','MAX17048','MAX17048G+T10',{1:'GND',2:'VBAT',3:'VBAT',4:'GND',5:'GAUGE_ALRT_N',6:'GND',7:'I2C_SCL',8:'I2C_SDA',9:'GND'},(462.28,251.46),(55.5,87),mpn='MAX17048G+T10')
p.part('U7','LOAD','TPS22919DCKR',{1:'3V3',2:'GND',3:'MIC_EN',4:None,5:'MIC_QOD',6:'MIC_VDD'},(101.6,411.48),(57,74),back=True,mpn='TPS22919DCKR')
p.part('U8','BUF','SN74LVC1G125DCKR',{1:'GND',2:'PDM_CLK',3:'GND',4:'PDM_CLK_BUFFER',5:'MIC_VDD'},(193.04,411.48),(62,78.5),back=True,mpn='SN74LVC1G125DCKR',datasheet='https://www.ti.com/lit/ds/symlink/sn74lvc1g125.pdf')
p.part('D1','RGB','APTF1616LSEEZGKQBKC',{1:'3V3',2:'LED_R_A',3:'LED_G_A',4:'LED_B_A'},(386.08,411.48),(62,51.8),back=True,mpn='APTF1616LSEEZGKQBKC',datasheet='https://www.kingbrightusa.com/images/catalog/spec/aptf1616lseezgkqbkc.pdf')
p.part('L1','L','0.47uH 5.4A',{1:'SW_L1',2:'SW_L2'},(508,76.2),(67,80.7),mpn='XFL4015-471MEC',datasheet='https://www.coilcraft.com/getmedia/84927b8b-f089-421b-a7f4-a0fa23afe908/xfl4015.pdf')
resistors=[
 ('R1','10k','3V3','MCU_EN',(55,70.5)),('R2','10k','3V3','BOOT_N',(57,70.5)),
 ('R3','22','MCU_USB_DP','USB_DP',(65,70.5)),('R4','22','MCU_USB_DM','USB_DM',(67,70.5)),
 ('R5','68k','VBUS','USB_VBUS',(53.5,72.5)),('R6','100k','USB_VBUS','GND',(55.5,72.5)),
 ('R7','4.7k','3V3','I2C_SDA',(59,70.5)),('R8','4.7k','3V3','I2C_SCL',(61,70.5)),
 ('R9','100k','CHG_EN1','GND',(52.5,78)),('R10','100k','CHG_EN2','GND',(52.5,80)),
 ('R11','2.55k 1%','CHG_ISET','GND',(55.5,81.8)),('R12','3.16k 1%','CHG_ILIM','GND',(57.5,81.8)),
 ('R13','3.01k 1%','CHG_ITERM','GND',(53.5,83.5)),('R14','49.9k 1%','CHG_TMR','GND',(55.5,83.5)),
 ('R15','10k','3V3','CHG_N',(59.5,81.8)),('R16','10k','3V3','PGOOD_N',(59.5,83.5)),
 ('R17','511k 1%','3V3','REG_FB',(63.5,85)),('R18','91k 1%','REG_FB','GND',(63.5,86.7)),
 ('R19','100k','PWR_EN','GND',(70,87)),('R20','100k','3V3','REG_PG',(70,85)),
 ('R21','10k','3V3','KEY_L',(54,65)),('R22','10k','3V3','KEY_R',(56,65)),
 ('R23','10k','3V3','KEY_VOICE',(58,65)),('R24','10k','3V3','KEY_SIDE',(60,65)),
 ('R25','10k','3V3','IMU_CS',(59,75)),('R26','10k','3V3','GAUGE_ALRT_N',(55.5,88.8)),
 ('R27','100k','HAPTIC_EN','GND',(68,79.5)),('R28','100k','MIC_EN','GND',(54,74)),
 ('R29','100','MIC_QOD','MIC_VDD',(56,76)),('R30','33','PDM_CLK_BUFFER','MIC_CLK',(62,80.5)),
 ('R31','1k','LED_R_A','LED_R_D',(59,55)),('R32','680','LED_G_A','LED_G_D',(62,55)),('R33','680','LED_B_A','LED_B_D',(65,55)),
 ('R34','100k','LED_R','GND',(59,59.5)),('R35','100k','LED_G','GND',(62,59.5)),('R36','100k','LED_B','GND',(65,59.5))]
for i,(ref,value,a,b,pos) in enumerate(resistors):
    # Separate schematic banks below each relevant functional block.
    bank=i//12;offset=i%12;sch=(50.8+bank*177.8+(offset%4)*38.1,157.48+(offset//4)*25.4)
    p.part(ref,'R',value,{1:a,2:b},sch,pos,back=i>=20,mpn=passives['resistors'][value.split()[0]])
caps=[
 ('C1','1uF 25V','MCU_EN',(53.5,68),False,'C'),('C2','22uF 6.3V','3V3',(57,68),False,'C6'),('C3','100nF 10V','3V3',(59,68),False,'C'),
 ('C4','4.7uF 10V','VBUS',(53,76),False,'C6'),('C5','4.7uF 10V','SYS',(57.5,77),False,'C6'),('C6','4.7uF 10V','VBAT',(58,79.5),False,'C6'),
 ('C7','10uF 6.3V','SYS',(70,83.3),False,'C6'),('C8','22uF 6.3V','3V3',(70,88.5),False,'C6'),
 ('C9','100nF 10V','3V3',(60,73),False,'C'),('C10','100nF 10V','3V3',(63.5,73),False,'C'),
 ('C11','1uF 25V','HAPTIC_REG',(67,73),True,'C'),('C12','1uF 25V','3V3',(70,73),True,'C'),
 ('C13','100nF 10V','VBAT',(53,87),False,'C'),('C14','1uF 25V','3V3',(56,71.5),True,'C'),
 ('C15','1uF 25V','MIC_VDD',(58,76),True,'C'),('C16','100nF 10V','MIC_VDD',(63,76),True,'C')]
for i,(ref,value,rail,pos,back,typ) in enumerate(caps):
    sch=(50.8+(i%8)*63.5,320.04+(i//8)*30.48)
    p.part(ref,typ,value,{1:rail,2:'GND'},sch,pos,back=back,mpn=passives["capacitors"][value]["mpn"])
for i,letter in enumerate('RGB'):
    p.part('Q'+str(i+1),'FET','AO3400A',{1:'LED_'+letter,2:'GND',3:'LED_'+letter+'_D'},(320.04+i*50.8,457.2),(59+i*3,57.5),back=True,mpn='AO3400A',datasheet='https://www.aosmd.com/res/data_sheets/AO3400A.pdf')
# All solder terminals are physical pads, listed in the assembly harness map.
terminals=[('VBUS',52,90.5),('GND',54,90.5),('USB_DP',56,90.5),('USB_DM',58,90.5),('VBAT',60,90.5),('BATT_NTC',62,90.5),('GND',64,90.5),('LRA_P',66,90.5),('LRA_N',68,90.5),('PWR_EN',70,90.5),('SYS',72,90.5)]
terminals += [(net,51.1,53+i*2.3) for i,net in enumerate(['KEY_L','GND','KEY_R','GND','KEY_VOICE','GND','KEY_SIDE','GND','MCU_EN','GND','BOOT_N','UART_TX','UART_RX'])]
terminals += [(net,72.9,53+i*2.3) for i,net in enumerate(['MIC_VDD','GND','MIC_CLK','PDM_DATA','3V3','GND'])]
for i,(net,x,y) in enumerate(terminals,1):p.part('TP'+str(i),'TP',net,{1:net},(50.8+((i-1)%10)*50.8,510.54+((i-1)//10)*20.32),(x,y),bom=False)
for i,net in enumerate(['GND','VBUS'],1):p.part('#FLG0'+str(i),'PWR','PWR_FLAG',{1:net},(584.2,66.04+i*20.32),bom=False)
p.note('MCU: GPIO 35/36/37 unavailable on N16R8. USB 19/20 only. EN restart preserves NVS.\nCHARGER: 2.55k sets 349mA nominal; 3.01k ITERM approx 35mA in USB500 mode.\nBQ24074 TS requires the specified protected pack with 10k NTC; open TS blocks charge.\nEN1/EN2: 00=USB100 default, 10=USB500 after enumeration, 11=suspend.\nMechanical slide switch connects SYS to PWR_EN; charger remains powered while off.\nMic clock buffer is supplied by MIC_VDD and supports Ioff, avoiding clock back-power.\nUART and BOOT pads are service access, not external exposed connectors.',571.5,121.92)
p.note('DESIGN IN PROGRESS: mainboard routing and sensor package orientation,\ncomponent placement/courtyard review and ECAD/MCAD exchange pending.\nDo not fabricate from this intermediate placement.',571.5,284.48)
# Placement coordinates are shared with assembly and routing tools. Intentional
# functional grouping precedes any autorouting; power and USB routes are manual.
placements=json.loads((r/'spec/main-placement.json').read_text())
for c in p.parts:
 if c['ref'] in placements:
  v=placements[c['ref']];c['pcb']=v[:2];c['angle']=v[2];c['back']=v[3]
from attach_component_models import attach
attach(p)
p.save();p.board();p.save_board()
(r/'spec/main-harness.json').write_text(json.dumps({'terminals':[{'reference':'TP'+str(i),'net':n,'pcb_mm':[x,y]} for i,(n,x,y) in enumerate(terminals,1)],'status':'candidate, harness electrical/assembly validation pending'},indent=2)+'\n')
print(p.out)

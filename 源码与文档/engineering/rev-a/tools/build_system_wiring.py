#!/usr/bin/env python3
"""Native system harness drawing, pins reconciled to actual board netlists."""
from pathlib import Path
import json,xml.etree.ElementTree as E
from eda_project import Project
R=Path(__file__).resolve().parents[1]
P=Project(R,'aikey_system','AI KEY complete system wiring / harness',(0,0),paper='A2')
main=json.loads((R/'spec/main-harness.json').read_text())['terminals']
def block(name,ref,ports,nets,pos,mpn='',bom=False):
 P.custom_symbol(name,[(str(i),label,'passive','left' if i<=len(ports)//2 else 'right') for i,label in enumerate(ports,1)],'','','Physical board solder terminals / harness endpoints, not replacement circuitry')
 P.part(ref,name,mpn or name,{str(i):nets[i-1] for i in range(1,len(ports)+1)},pos,mpn=mpn,bom=bom)
used={v['reference']:v['net'] for v in main}
for n in ('TP22','TP23','TP24','TP29','TP30'):used[n]=None
block('Mainboard_Terminals','MB1',[p['reference']+'_'+p['net'] for p in main],[used[p['reference']] for p in main],(142.24,93.98),'aikey_main')
block('USB_Daughterboard','USB1',['TP1_VBUS','TP2_GND','TP3_DP','TP4_DM'],['VBUS','GND','USB_DP','USB_DM'],(66.04,40.64),'aikey_usb')
for name,ref,net,y,mpn in [('Left_Key','KL1','KEY_L',81.28,'aikey_top_key'),('Right_Key','KR1','KEY_R',116.84,'aikey_top_key'),('Voice_Key','KV1','KEY_VOICE',152.4,'aikey_back_key'),('Side_Key','KS1','KEY_SIDE',187.96,'aikey_back_key'),('Reset_Key','RST1','MCU_EN',223.52,'aikey_top_key')]:
 block(name,ref,['TP1_KEY','TP2_GND'],[net,'GND'],(66.04,y),mpn)
block('PDM_Microphone','MIC1',['TP1_VDD','TP2_CLK','TP3_GND','TP4_DATA'],['MIC_VDD','MIC_CLK','GND','PDM_DATA'],(246.38,45.72),'aikey_mic')
block('Power_Enable_Board','PWR1',['TP1_SYS','TP2_EN','TP3_GND'],['SYS','PWR_EN','GND'],(246.38,93.98),'aikey_power')
block('Protected_1S_Pack','BAT1',['PACK_POS','PACK_NEG','NTC'],['VBAT','GND','BATT_NTC'],(246.38,144.78),'Protected 1S 700mAh target; max30x43x7 mm; 10k NTC',True)
block('LRA','M1',['RED_POS','BLUE_NEG'],['LRA_P','LRA_N'],(246.38,187.96),'Precision Microdrives C10-100',True)
# Radio cable belongs to the main module IPEX port; represented separately
# because it is not a GPIO wire or a mainboard solder terminal.
block('Module_RF_Port','RF1',['U1_IPEX'],['RF_50OHM'],(142.24,236.22),'ESP32-S3-WROOM-1U RF connector')
block('Flexible_Antenna','ANT1',['IPEX_PLUG'],['RF_50OHM'],(246.38,236.22),'Taoglas FXP73.07.0100A',True)
P.note('Assembly wire schedule is generated from these actual terminal nets.\nUSB: use shielded 90-ohm differential cable; length/geometry require channel qualification.\nKeys and reset: paired signal/GND, active low; reset only drives MCU_EN low.\nMicrophone: four conductors, switched MIC_VDD only; CLK/DATA routed with adjacent GND.\nBattery: protected output only; NTC must be pack temperature, never substituted by fixed resistor.\nPower switch controls EN; OFF leaves charging and gauge supplied.\nUnused mainboard TP22/23/24/29/30 remain accessible test points; no permanent harness.\nWire routes and strain relief await native mechanical integration.\nNo sample connected; continuity, polarity, EMC and RF qualification require hardware.',330.2,40.64)
P.save()
# Source comparison confirms names and numbers used in the native wiring sheet.
rows=[]
for name,expected in [('aikey_main',{v['reference']:v['net'] for v in main}),('aikey_power',{'TP1':'SYS','TP2':'PWR_EN','TP3':'GND'}),('aikey_usb',{'TP1':'VBUS','TP2':'GND','TP3':'USB_DP','TP4':'USB_DM'}),('aikey_mic',{'TP1':'MIC_VDD','TP2':'MIC_CLK','TP3':'GND','TP4':'PDM_DATA'}),('aikey_back_key',{'TP1':'KEY','TP2':'GND'}),('aikey_top_key',{'TP1':'KEY','TP2':'GND'})]:
 root=E.parse(R/'reports'/f'{name}-current.xml').getroot();actual={node.get('ref'):net.get('name').lstrip('/') for net in root.findall('nets/net') for node in net if node.get('ref') in expected}
 if actual!=expected:raise RuntimeError((name,expected,actual))
 rows.append({'board':name,'terminal_nets':actual})
(R/'reports/system-wiring-build.json').write_text(json.dumps({'status':'SCHEMATIC_SAVED_SOURCE_TERMINALS_MATCH_ERC_PENDING','source_boards':rows,'battery':'Supplier pack and NTC grade remain qualification items'},indent=2)+'\n')
print(P.out)

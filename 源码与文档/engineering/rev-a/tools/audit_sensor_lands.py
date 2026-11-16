#!/usr/bin/env python3
"""Saved-native sensor land/net readback against the reviewed manufacturer tables."""
from pathlib import Path
import json,hashlib,math,shutil
from sexpr import parse,children,one,prop
R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_main';file=P/'aikey_main.kicad_pcb'
t=parse(file.read_text());nets={n[1]:n[2] for n in children(t,'net')};rows=[]
expected={'U4':{1:'IMU_MISO',2:'GND',3:'GND',4:'IMU_INT1',5:'3V3',6:'GND',7:'GND',8:'3V3',9:None,10:'3V3',11:None,12:'IMU_CS',13:'IMU_SCLK',14:'IMU_MOSI'},'U6':{1:'GND',2:'VBAT',3:'VBAT',4:'GND',5:'GAUGE_ALRT_N',6:'GND',7:'I2C_SCL',8:'I2C_SDA',9:'GND'}}
for ref,netmap in expected.items():
    fp=next(f for f in children(t,'footprint') if prop(f,'Reference')==ref)
    copper=[pad for pad in children(fp,'pad') if 'F.Cu' in one(pad,'layers')[1:]]
    assert len(copper)==len(netmap),(ref,'pad count')
    values=[]
    for pad in copper:
        n=int(pad[1]);size=list(map(float,one(pad,'size')[1:3]));at=list(map(float,one(pad,'at')[1:3]));entry=one(pad,'net');net=(entry[1] if len(entry)==2 else nets.get(entry[1],entry[2] if len(entry)>2 else '')) if entry else ''
        # Unconnected schematic pins have an explicitly generated net name.
        want=netmap[n]
        assert net=='/'+want if want else ('unconnected' in net or not net),(ref,n,net)
        target=[.8,1.38] if ref=='U6' and n==9 else [.7,.3] if ref=='U6' else [.575,.35] if n in (1,2,3,4,8,9,10,11) else [.35,.575]
        assert all(abs(a-b)<1e-7 for a,b in zip(size,target)),(ref,n,size,target)
        if ref=='U6' and n!=9:assert abs(abs(at[0])-.99)<1e-7
        values.append({'number':n,'net':net,'local_center_mm':at,'land_mm':size})
    rows.append({'ref':ref,'footprint':fp[1],'pads':values})
drc=R/'reports/main-board-drc.json';erc=R/'reports/sensor-main-erc.json'
d=json.loads(drc.read_text());assert not any(d[k] for k in ('violations','unconnected_items','schematic_parity'))
e=json.loads(erc.read_text());assert all(not s['violations'] for s in e['sheets'])
archive=R/'reports/history/sensors-reviewed-pass';archive.mkdir(exist_ok=True)
for f in (file,P/'aikey_main.kicad_sch',P/'aikey_main.kicad_pro',drc,erc):
    out=archive/f.name
    if out.exists() and out.read_bytes()!=f.read_bytes():raise RuntimeError('Refuse to replace prior milestone')
    shutil.copy2(f,out)
report={'status':'MANUFACTURER_LAND_NET_READBACK_ERC_DRC_PASS','native_board_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'readback':rows,'sources':'reports/sensor-land-sources.json','drc_sha256':hashlib.sha256(drc.read_bytes()).hexdigest(),'erc_sha256':hashlib.sha256(erc.read_bytes()).hexdigest(),'scope':'Nominal lands, pin/net mapping and native rule checks. Solder process and MEMS performance remain physical tests.'}
(R/'reports/sensor-land-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'])

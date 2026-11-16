#!/usr/bin/env python3
"""Read USB descriptor bytes from the actual Xtensa ELF, not the source template."""
from pathlib import Path
import json,hashlib,struct,sys
from elftools.elf.elffile import ELFFile
root=Path(__file__).resolve().parents[1]
path=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/Users/linxiansheng/.cache/ai-key-rev-a/build/aikey_rev_a.elf')
with path.open('rb') as stream:
    elf=ELFFile(stream);symbols=elf.get_section_by_name('.symtab')
    def read(name):
        sym=next(s for s in symbols.iter_symbols() if s.name==name)
        section=elf.get_section(sym['st_shndx']);offset=sym['st_value']-section['sh_addr']
        return section.data()[offset:offset+sym['st_size']]
    device=read('device');config=read('configuration');hid=read('reports')
    for name in ['ak_imu_init','ak_imu_read','ak_audio_init','tud_audio_get_req_entity_cb','tud_audio_set_req_entity_cb']:
        assert symbols.get_symbol_by_name(name),name+' was not linked into the firmware'
assert device[0]==18 and device[1]==1 and tuple(device[4:7])==(0xef,2,1)
assert config[0]==9 and config[1]==2 and struct.unpack_from('<H',config,2)[0]==len(config)
assert config[4]==3 and config[7]&0x40 and config[8]==250
descriptors=[];i=0
while i<len(config):
    length=config[i];assert length>=2 and i+length<=len(config)
    d=config[i:i+length];descriptors.append(d);i+=length
interfaces=[{'number':d[2],'alt':d[3],'endpoints':d[4],'class':d[5],'subclass':d[6],'protocol':d[7]} for d in descriptors if d[1]==4]
assert [(x['number'],x['alt'],x['class']) for x in interfaces]==[(0,0,3),(1,0,1),(2,0,1),(2,1,1)]
endpoints=[{'address':d[2],'type':d[3]&3,'max_packet':struct.unpack_from('<H',d,4)[0],'interval':d[6]} for d in descriptors if d[1]==5]
assert endpoints==[{'address':0x81,'type':3,'max_packet':64,'interval':4},{'address':0x82,'type':1,'max_packet':34,'interval':1}]
# HID report descriptor parser: collect the report bit counts by report ID.
pos=0;state={};sizes={};report_id=0;bits=count=0
while pos<len(hid):
    prefix=hid[pos];pos+=1;assert prefix!=0xfe
    n=prefix&3;n=4 if n==3 else n;value=int.from_bytes(hid[pos:pos+n],'little');pos+=n
    kind=(prefix>>2)&3;tag=prefix>>4
    if kind==1:
        if tag==7:bits=value
        elif tag==8:report_id=value
        elif tag==9:count=value
    elif kind==0 and tag in (8,9):
        key=(report_id,'input' if tag==8 else 'output');sizes[key]=sizes.get(key,0)+bits*count
assert sizes=={(1,'input'):40,(2,'input'):256,(2,'output'):256,(3,'input'):256,(3,'output'):256},sizes
report={'status':'ELF_DESCRIPTOR_CHECK_PASS','physical_enumeration':False,'elf':str(path),'elf_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'device_hex':device.hex(),'configuration_hex':config.hex(),'interfaces':interfaces,'endpoints':endpoints,'hid_reports_bits':{f'{k[0]}-{k[1]}':v for k,v in sizes.items()},'linked_drivers':['LSM6DSV16X SPI','PDM capture and FIR','USB Audio 2.0 controls'],'production_usb_identity':'not allocated; development identity only'}
(root/'reports/usb-descriptor-check.json').write_text(json.dumps(report,indent=2)+'\n')
print(report['status'],interfaces,endpoints)

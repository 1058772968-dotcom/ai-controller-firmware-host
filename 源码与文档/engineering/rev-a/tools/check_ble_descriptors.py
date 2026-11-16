#!/usr/bin/env python3
"""Verify HOGP bytes and transport symbols in the actual linked Xtensa ELF."""
from pathlib import Path
import hashlib,json,sys,uuid
from elftools.elf.elffile import ELFFile
ROOT=Path(__file__).resolve().parents[1]
path=Path(sys.argv[1]) if len(sys.argv)>1 else Path.home()/'.cache/ai-key-rev-a/build/aikey_rev_a.elf'
required=['ak_ble_init','ak_ble_mouse','ak_ble_state','ak_link_update','ble_gatts_notify_custom','ble_gap_security_initiate','ble_store_config_init']
with path.open('rb') as stream:
    elf=ELFFile(stream);symbols=elf.get_section_by_name('.symtab')
    def read(name):
        matches=symbols.get_symbol_by_name(name)
        assert matches and len(matches)==1,name
        sym=matches[0];section=elf.get_section(sym['st_shndx'])
        offset=sym['st_value']-section['sh_addr']
        return section.data()[offset:offset+sym['st_size']]
    for name in required:assert symbols.get_symbol_by_name(name),name
    hid=read('mouse_map');service=read('control_service');control=read('control_uuid')
    for data,expected in ((service,'98f32a0e-79bc-4d5b-9f84-dcce6f807291'),(control,'98f32a0e-79bc-4d5b-9f84-dcce6f807292')):
        assert data[0]==128 and data[1:17]==uuid.UUID(expected).bytes[::-1],(data.hex(),expected)
pos=0;bits=count=report=0;sizes={}
while pos<len(hid):
    prefix=hid[pos];pos+=1;assert prefix!=0xfe
    n=prefix&3;n=4 if n==3 else n
    assert pos+n<=len(hid)
    value=int.from_bytes(hid[pos:pos+n],'little');pos+=n
    kind=(prefix>>2)&3;tag=prefix>>4
    if kind==1:
        if tag==7:bits=value
        elif tag==8:report=value
        elif tag==9:count=value
    elif kind==0 and tag in (8,9,11):
        key=(report,{8:'input',9:'output',11:'feature'}[tag]);sizes[key]=sizes.get(key,0)+bits*count
assert sizes=={(1,'input'):40},sizes
result={'status':'ELF_BLE_DESCRIPTOR_AND_LINKED_SYMBOLS_PASS','elf':str(path),'elf_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'hid_report_map_hex':hid.hex(),'hid_reports_bits':{f'{k[0]}-{k[1]}':v for k,v in sizes.items()},
        'service_uuid':'98f32a0e-79bc-4d5b-9f84-dcce6f807291','control_uuid':'98f32a0e-79bc-4d5b-9f84-dcce6f807292','linked_symbols':required,
        'physical_pairing':False,'scope':'Static final-ELF verification; no radio, host pairing, notification delivery or power measurements.'}
(ROOT/'reports/ble-descriptor-check.json').write_text(json.dumps(result,indent=2)+'\n')
print(result['status'])

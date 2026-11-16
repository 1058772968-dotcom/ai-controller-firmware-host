#!/usr/bin/env python3
"""Audit current native netlists, PCB pad nets, shared firmware GPIOs and values."""
from pathlib import Path
import hashlib,json,re,subprocess,xml.etree.ElementTree as X
R=Path(__file__).resolve().parents[1];CLI='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source=json.loads((R/'reports/ecad-fiducial-source.json').read_text());trees={};nets={};provenance=[];checked=0
for b in source['boards']:
    name=b['board'];pcb=Path(b['native_file']);sch=pcb.with_suffix('.kicad_sch');out=R/'reports'/(name+'-current.xml')
    assert sha(pcb)==b['native_sha256'],'Re-export PCB readback after a mutation'
    proc=subprocess.run([CLI,'sch','export','netlist','--format','kicadxml','-o',str(out),str(sch)],capture_output=True,text=True)
    if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
    root=X.parse(out).getroot();trees[name]=root;nm={}
    for net in root.findall('./nets/net'):
        for node in net.findall('node'):nm[(node.get('ref'),node.get('pin'))]=(net.get('name'),node.get('pinfunction'),node.get('pintype'))
    nets[name]=nm
    for pad in b['pads']:
        if not pad['pin']:continue
        expected=nm.get((pad['ref'],pad['pin']))
        if expected is None:raise AssertionError((name,pad,'Absent schematic pin'))
        net=expected[0]
        if 'no_connect' in expected[2]:assert not pad['net'] or pad['net'].startswith('unconnected-')
        else:assert pad['net']==net,(name,pad,expected)
        checked+=1
    provenance.append({'board':name,'pcb_sha256':sha(pcb),'schematic_sha256':sha(sch),'netlist_sha256':sha(out)})
nm=nets['aikey_main'];root=trees['aikey_main'];components={c.get('ref'):c for c in root.findall('./components/comp')}
config=json.loads((R/'spec/board.json').read_text());header=(R/'firmware/core/board_config.h').read_text()
gpio=[]
special={'USB_D-':19,'USB_D+':20,'TXD0':43,'RXD0':44}
for (ref,pin),(net,function,typ) in nm.items():
    if ref!='U1':continue
    function=function.rsplit('_',1)[0]
    number=int(function[2:]) if re.fullmatch(r'IO\d+',function) else special.get(function)
    if number is None:continue
    if number in config['pins'].values():
        signal=next(k for k,v in config['pins'].items() if v==number)
        expected='/'+('MCU_'+signal if signal in ('USB_DM','USB_DP') else signal)
        assert net==expected,(signal,net,expected)
        assert re.search(r'#define\s+AK_PIN_'+signal+r'\s+'+str(number)+r'\b',header)
        gpio.append({'signal':signal,'gpio':number,'module_pin':pin,'schematic_net':net,'firmware_define_matches':True})
    elif number==0:assert net=='/BOOT_N'
    else:assert 'no_connect' in typ,(number,net)
assert len(gpio)==len(config['pins'])
expected={
 'U2':{1:'BATT_NTC',2:'VBAT',3:'VBAT',4:'GND',5:'CHG_EN2',6:'CHG_EN1',7:'PGOOD_N',8:'GND',9:'CHG_N',10:'SYS',11:'SYS',12:'CHG_ILIM',13:'VBUS',14:'CHG_TMR',15:'CHG_ITERM',16:'CHG_ISET',17:'GND'},
 'U3':{1:'PWR_EN',2:'GND',3:'GND',4:'REG_FB',5:'REG_PG',6:'3V3',7:'SW_L2',8:'GND',9:'SW_L1',10:'SYS'},
 'U7':{1:'3V3',2:'GND',3:'MIC_EN',5:'MIC_QOD',6:'MIC_VDD'},
 'U8':{1:'GND',2:'PDM_CLK',3:'GND',4:'PDM_CLK_BUFFER',5:'MIC_VDD'},
 'R1':{1:'3V3',2:'MCU_EN'},'C1':{1:'MCU_EN',2:'GND'},
 'R9':{1:'CHG_EN1',2:'GND'},'R10':{1:'CHG_EN2',2:'GND'},
 'R11':{1:'CHG_ISET',2:'GND'},'R12':{1:'CHG_ILIM',2:'GND'},'R13':{1:'CHG_ITERM',2:'GND'},'R14':{1:'CHG_TMR',2:'GND'},
 'R17':{1:'3V3',2:'REG_FB'},'R18':{1:'REG_FB',2:'GND'},'R19':{1:'PWR_EN',2:'GND'},
 'R27':{1:'HAPTIC_EN',2:'GND'},'R28':{1:'MIC_EN',2:'GND'},'R29':{1:'MIC_QOD',2:'MIC_VDD'},
 'L1':{1:'SW_L1',2:'SW_L2'},'C7':{1:'SYS',2:'GND'},'C8':{1:'3V3',2:'GND'}}
pinchecks=[]
for ref,pins in expected.items():
    for pin,net in pins.items():
        actual=nm[(ref,str(pin))];assert actual[0]=='/'+net,(ref,pin,actual,net)
        pinchecks.append({'ref':ref,'pin':pin,'pin_function':actual[1],'net':net})
def value(ref):return components[ref].findtext('value')
def ohms(ref):
    text=value(ref).split()[0];return float(text.rstrip('k'))*(1000 if text.endswith('k') else 1)
ri,rt,rterm,rilim=ohms('R11'),ohms('R14'),ohms('R13'),ohms('R12')
calculations={'charge_current_A':890/ri,'charge_with_factor_and_1pct_resistor_extremes_A':[797/(ri*1.01),975/(ri*.99)],
 'resistor_programmed_input_A':1550/rilim,'input_mode_note':'External ILIM mode is not selected by firmware; USB100 default, USB500 only after enumeration, suspend=11.',
 'termination_usb500_A':.03*rterm/ri,'termination_usb100_A':.01*rterm/ri,
 'fast_charge_timer_hours':10*48*(rt/1000)/3600,'precharge_timer_minutes':48*(rt/1000)/60,
 'regulator_nominal_V':.5*(1+ohms('R17')/ohms('R18')),'vbus_sense_5V_V':5*ohms('R6')/(ohms('R5')+ohms('R6')),
 'inductor_mpn':components['L1'].find("./fields/field[@name='MPN']").text,
 'input_cap_mpn':components['C7'].find("./fields/field[@name='MPN']").text,
 'output_cap_mpn':components['C8'].find("./fields/field[@name='MPN']").text}
assert 0.34<calculations['charge_current_A']<.36
assert 3.28<calculations['regulator_nominal_V']<3.34
assert ohms('R18')<=100000 and 1100<=rilim<=8000 and rterm<15000
assert calculations['input_cap_mpn']=='GRM188R60J106ME84D' and calculations['output_cap_mpn']=='GRM188R60J226MEA0D'
power=nets['aikey_power'];power_root=trees['aikey_power']
assert power[('SW1','2')][0]=='/PWR_EN' and power[('SW1','3')][0]=='/SYS'
assert 'no_connect' in power[('SW1','1')][2]
assert power[('R1','1')][0]=='/PWR_EN' and power[('R1','2')][0]=='/GND'
assert power_root.find("./components/comp[@ref='SW1']/fields/field[@name='MPN']").text=='SS12SDP4'
assert power_root.findtext("./components/comp[@ref='R1']/value")=='10k 1%'
calculations['power_switch']={'mpn':'SS12SDP4','contact':'gold logic-level; MBB unused throw left open','added_pulldown_ohm':10000,'main_pulldown_ohm':ohms('R19'),'contact_current_A_at_3V_and_4V4':[v*(1/10000+1/ohms('R19')) for v in (3,4.4)],'datasheet_applicable_minimum_A':.0001,'off_state':'Regulator EN off; charger and gauge remain powered'}
assert calculations['power_switch']['contact_current_A_at_3V_and_4V4'][0]>.0001
report={'status':'NATIVE_NET_PIN_GPIO_AND_NOMINAL_POWER_CALCULATIONS_PASS_QUALIFICATION_PENDING',
 'provenance':provenance,'native_pads_matched':checked,'gpio_count':len(gpio),'gpio_mapping':gpio,'reviewed_pin_nets':pinchecks,'calculations':calculations,
 'sources':{'BQ24074':'https://www.ti.com/lit/ds/symlink/bq24074.pdf','TPS63802':'https://www.ti.com/lit/ds/symlink/tps63802.pdf',
 'mic_switch':'https://www.ti.com/lit/ds/symlink/tps22919.pdf','clock_buffer':'https://www.ti.com/lit/ds/symlink/sn74lvc1g125.pdf','power_switch':'https://www.nkkswitches.co.jp/product/detailed/SS-12SDP4.html'},
 'remaining':['Protected pack must permit worst-case charge current, include correct 10k NTC curve/protection/lead polarity; supplier not frozen',
 'Nominal capacitors match TI recommended parts; exact bias/temperature/lot and transient response require validation',
 'Copper current capacity, converter/charger layout thermals and simultaneous radio/haptic peak load require detailed review and prototype measurements',
 'External power/reset switch and final harness/strain relief still under mechanical integration',
 'Manufacturing outputs, assembler review, controlled impedance and physical ESD/USB/radio qualification pending'],
 'scope':'Saved native schematic netlists, independently read PCB pad nets and compiled-source GPIO definitions. Component calculations are not measured electrical performance.'}
(R/'reports/native-interface-power-review.json').write_text(json.dumps(report,indent=2)+'\n')
print(report['status'],checked,'PCB pad nets;',len(gpio),'GPIOs;',len(pinchecks),'reviewed pin nets',flush=True)

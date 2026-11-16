#!/usr/bin/env python3
"""Create a native 9x9 mm rear-key daughterboard using the real SKQG footprint.

The mainboard supplies the pull-up and firmware debounce. Both duplicate switch
pads are explicitly routed. Two backside solder pads receive the strain-relieved
wire pair. No custom DRC exclusions or relaxed footprint keepouts.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
from sexpr import Atom, parse, dump, children, one, prop, uid, SHARE
import wx
app=wx.App(False)
import pcbnew as pcb

ROOT=Path(__file__).resolve().parents[1]
arg=argparse.ArgumentParser();arg.add_argument('--kind',choices=['back','top'],default='back');kind=arg.parse_args().kind
NAME='aikey_'+kind+'_key'
MPN='SKQGAFE010' if kind=='back' else 'SKQGABE010'
FORCE='0.98' if kind=='back' else '1.57'
OUT=ROOT/'electrical'/NAME
LIB=OUT/'libraries'
FP=LIB/'AIKEY.pretty'
FP.mkdir(parents=True,exist_ok=True)
symbols=[]
definitions=[('SW_SPST','Switch:SW_SPST','Button_Switch_SMD:SW_SPST_SKQG_WithStem'),
             ('TestPoint','Connector:TestPoint','TestPoint:TestPoint_Pad_D1.0mm')]
for dest,source,footprint in definitions:
    lib,name=source.split(':')
    tree=parse((SHARE/'symbols'/f'{lib}.kicad_sym').read_text())
    s=copy.deepcopy(next(x for x in children(tree,'symbol') if x[1]==name));s[1]=dest
    for sub in children(s,'symbol'): sub[1]=dest+sub[1][len(name):]
    flib,fpname=footprint.split(':')
    shutil.copy2(SHARE/'footprints'/f'{flib}.pretty'/f'{fpname}.kicad_mod', FP/f'{fpname}.kicad_mod')
    for p in children(s,'property'):
        if p[1]=='Footprint':p[2]='AIKEY:'+fpname
    symbols.append(s)
(LIB/'AIKEY.kicad_sym').write_text(dump([Atom('kicad_symbol_lib'),[Atom('version'),Atom('20250114')],[Atom('generator'),'kicad_symbol_editor']]+symbols)+'\n')
for libkind,typ,suffix in [('sym','KiCad','kicad_sym'),('fp','KiCad','pretty')]:
    (OUT/f'{libkind}-lib-table').write_text(f'({libkind}_lib_table (version 7) (lib (name "AIKEY") (type "{typ}") (uri "${{KIPRJMOD}}/libraries/AIKEY.{suffix}") (options "") (descr "Pinned official KiCad 10.0.6 library")))\n')
rootid=uid(NAME+'/root')
tree=parse(f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "10.0") (uuid "{rootid}") (paper "A4") (title_block (title "AI KEY {kind} key daughterboard") (rev "A.1") (comment 1 "{MPN}; 9 x 9 x 0.8 mm; pull-up on main board")) (lib_symbols) (sheet_instances (path "/" (page "1"))))')
for s in symbols:
    t=copy.deepcopy(s);t[1]='AIKEY:'+s[1];one(tree,'lib_symbols').append(t)
components=[('SW1','SW_SPST',MPN,105.41,76.2,{'1':'KEY','2':'GND'}),
            ('TP1','TestPoint','KEY_WIRE',76.2,63.5,{'1':'KEY'}),
            ('TP2','TestPoint','GND_WIRE',134.62,88.9,{'1':'GND'})]
for ref,id,value,x,y,nets in components:
    s=next(t for t in symbols if t[1]==id)
    in_bom='yes' if ref=='SW1' else 'no'
    inst=parse(f'(symbol (lib_id "AIKEY:{id}") (at {x} {y} 0) (unit 1) (in_bom {in_bom}) (on_board yes) (dnp no) (uuid "{uid(NAME+ref)}"))')
    fields={'Reference':ref,'Value':value,'Footprint':prop(s,'Footprint'),'Datasheet':prop(s,'Datasheet'),'Description':prop(s,'Description')}
    if ref=='SW1':fields['Datasheet']=f'https://tech.alpsalpine.com/e/products/detail/{MPN}/'
    for k,v in fields.items():
        ypos=y-6.35 if k=='Reference' else y-3.81
        hidden='' if k in ('Reference','Value') else ' (hide yes)'
        inst.append(parse(f'(property {json.dumps(k)} {json.dumps(v)} (at {x} {ypos} 0) (effects (font (size 1.27 1.27)){hidden}))'))
    for sub in children(s,'symbol'):
        for pin in children(sub,'pin'):
            num=str(one(pin,'number')[1]);at=one(pin,'at');px=x+float(at[1]);py=y-float(at[2]);angle=int(at[3])
            dx,dy={0:(-5.08,0),90:(0,5.08),180:(5.08,0),270:(0,-5.08)}[angle]
            ex,ey=round(px+dx,4),round(py+dy,4)
            tree.append(parse(f'(wire (pts (xy {px} {py}) (xy {ex} {ey})) (stroke (width 0) (type default)) (uuid "{uid(NAME+ref+num+"wire")}"))'))
            tree.append(parse(f'(label "{nets[num]}" (at {ex} {ey} 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "{uid(NAME+ref+num+"label")}"))'))
            inst.append(parse(f'(pin "{num}" (uuid "{uid(NAME+ref+num)}"))'))
    inst.append(parse(f'(instances (project "{NAME}" (path "/{rootid}" (reference "{ref}") (unit 1))))'));tree.append(inst)
note=f'Mainboard: 10k pull-up to 3V3. GPIO active low.\nSW1: ALPS {MPN}, {FORCE} N, 0.25 mm nominal.\nTP1/TP2: backside solder terminals; no connector fitted.\nProvide wire strain relief in enclosure. No battery voltage on KEY.'
tree.append(parse(f'(text {json.dumps(note)} (at 63.5 114.3 0) (effects (font (size 1.27 1.27)) (justify left top)) (uuid "{uid(NAME+"note")}"))'))
(OUT/f'{NAME}.kicad_sch').write_text(dump(tree)+'\n')
settings={'meta':{'version':1,'filename':NAME+'.kicad_pro'},'board':{'design_settings':{'rules':{'min_clearance':.15,'min_track_width':.15,'min_copper_edge_clearance':.3,'min_hole_clearance':.25,'min_hole_to_hole':.25,'min_via_diameter':.5,'min_through_hole_diameter':.3,'min_via_annular_width':.1,'min_text_height':.7,'min_text_thickness':.1},'drc_exclusions':[]}},'net_settings':{'meta':{'version':3},'classes':[{'name':'Default','clearance':.15,'track_width':.2,'via_diameter':.6,'via_drill':.3}]}}
(OUT/f'{NAME}.kicad_pro').write_text(json.dumps(settings,indent=2)+'\n')
pt=lambda x,y:pcb.VECTOR2I(pcb.FromMM(x),pcb.FromMM(y))
b=pcb.BOARD();b.SetCopperLayerCount(2);b.GetDesignSettings().SetBoardThickness(pcb.FromMM(.8));b.GetDesignSettings().SetAuxOrigin(pt(50,50))
for a,z in [((50,50),(59,50)),((59,50),(59,59)),((59,59),(50,59)),((50,59),(50,50))]:
    l=pcb.PCB_SHAPE();l.SetShape(pcb.SHAPE_T_SEGMENT);l.SetStart(pt(*a));l.SetEnd(pt(*z));l.SetLayer(pcb.Edge_Cuts);l.SetWidth(pcb.FromMM(.05));b.Add(l)
nets={n:pcb.NETINFO_ITEM(b,'/'+n) for n in ('KEY','GND')}
for n in nets.values():b.Add(n)
fps={}
for ref,id,value,x,y,pinmap in components:
    s=next(t for t in symbols if t[1]==id);fpname=prop(s,'Footprint').split(':')[1]
    f=pcb.FootprintLoad(str(FP),fpname);f.SetReference(ref);f.SetValue(value);f.SetFPID(pcb.LIB_ID('AIKEY',fpname));b.Add(f)
    path=pcb.KIID_PATH();path.push_back(pcb.KIID(rootid));path.push_back(pcb.KIID(uid(NAME+ref)));f.SetPath(path)
    f.SetPosition(pt(54.5,54.5) if ref=='SW1' else pt(53.1 if ref=='TP1' else 55.9,57.7))
    if ref!='SW1': f.Flip(f.GetPosition(),False)
    for pad in f.Pads():pad.SetNet(nets[pinmap[pad.GetNumber()]])
    f.Reference().SetVisible(False);f.Value().SetVisible(False)
    f.SetField('Datasheet',f'https://tech.alpsalpine.com/e/products/detail/{MPN}/' if ref=='SW1' else prop(s,'Datasheet'))
    f.SetField('Description',prop(s,'Description'));fps[ref]=f
    for field in f.GetFields():field.SetVisible(False)
def route(net,points,layer=pcb.F_Cu):
    for a,z in zip(points,points[1:]):
        t=pcb.PCB_TRACK(b);t.SetStart(pt(*a));t.SetEnd(pt(*z));t.SetWidth(pcb.FromMM(.2));t.SetLayer(layer);t.SetNet(nets[net]);b.Add(t)
def via(net,x,y):
    v=pcb.PCB_VIA(b);v.SetPosition(pt(x,y));v.SetWidth(pcb.FromMM(.6));v.SetDrill(pcb.FromMM(.3));v.SetViaType(pcb.VIATYPE_THROUGH);v.SetLayerPair(pcb.F_Cu,pcb.B_Cu);v.SetNet(nets[net]);b.Add(v)
route('KEY',[(51.4,52.65),(57.6,52.65)])
route('GND',[(51.4,56.35),(57.6,56.35)])
route('KEY',[(51.4,52.65),(51.4,51.5)]);via('KEY',51.4,51.5)
route('GND',[(57.6,56.35),(57.6,57.5)]);via('GND',57.6,57.5)
route('KEY',[(51.4,51.5),(51.4,56),(53.1,57.7)],pcb.B_Cu)
route('GND',[(57.6,57.5),(57.4,57.7),(55.9,57.7)],pcb.B_Cu)
pcb.SaveBoard(str(OUT/f'{NAME}.kicad_pcb'),b)
(OUT/f'{NAME}.kicad_pro').write_text(json.dumps(settings,indent=2)+'\n')
reopen=pcb.LoadBoard(str(OUT/f'{NAME}.kicad_pcb'))
assert len(list(reopen.GetFootprints()))==3
assert abs(pcb.ToMM(reopen.GetDesignSettings().GetBoardThickness())-.8)<1e-9
print(str(OUT))

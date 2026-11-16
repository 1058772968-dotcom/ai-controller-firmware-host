"""Native KiCad project generator with pinned library assets and explicit nets.

This is a file authoring utility, not an ERC/DRC substitute. Validation is run
with the installed kicad-cli against the saved native schematic and board.
"""
from pathlib import Path
import copy,json,shutil
from sexpr import Atom,parse,dump,children,one,prop,uid,SHARE

class Project:
    def __init__(self,root,name,title,size,thickness=1,layers=2,paper='A3'):
        self.root=Path(root);self.name=name;self.title=title;self.size=size
        self.out=self.root/'electrical'/name;self.lib=self.out/'libraries';self.fp=self.lib/'AIKEY.pretty'
        self.fp.mkdir(parents=True,exist_ok=True);self.symbols={};self.parts=[];self.notes=[]
        self.thickness=thickness;self.layers=layers;self.paper=paper;self.rootid=uid(name+'/root')
    def add_symbol(self,alias,source,footprint=None):
        lib,name=source.split(':');tree=parse((SHARE/'symbols'/f'{lib}.kicad_sym').read_text())
        allsymbols={s[1]:s for s in children(tree,'symbol')}
        s=copy.deepcopy(allsymbols[name]);ext=one(s,'extends')
        if ext:
            base=copy.deepcopy(allsymbols[ext[1]])
            if one(base,'extends'):raise ValueError('Nested inheritance requires explicit review')
            inherited=[v for v in base[2:] if not(isinstance(v,list) and v[0]=='property')]
            existing={p[1] for p in children(s,'property')}
            s=[Atom('symbol'),name]+inherited+[copy.deepcopy(p) for p in children(base,'property') if p[1] not in existing]+children(s,'property')
        s[1]=alias
        for sub in children(s,'symbol'):
            suffix=str(sub[1]).rsplit('_',2)[-2:];sub[1]=alias+'_'+'_'.join(suffix)
        footprint=footprint if footprint is not None else prop(s,'Footprint')
        if footprint:
            flib,fn=footprint.split(':');shutil.copy2(SHARE/'footprints'/f'{flib}.pretty'/f'{fn}.kicad_mod',self.fp/f'{fn}.kicad_mod')
            for p in children(s,'property'):
                if p[1]=='Footprint':p[2]='AIKEY:'+fn
        self.symbols[alias]=s
    def part(self,ref,symbol,value,nets,sch,pcb=None,angle=0,back=False,mpn='',datasheet=None,bom=True):
        assert symbol in self.symbols
        self.parts.append(dict(ref=ref,symbol=symbol,value=value,nets={str(k):v for k,v in nets.items()},sch=sch,pcb=pcb,angle=angle,back=back,mpn=mpn,datasheet=datasheet,bom=bom))
    def custom_symbol(self,name,pins,footprint,datasheet,description):
        """pins: explicit (number, name, electrical_type, left/right) tuples."""
        left=[v for v in pins if v[3]=='left'];right=[v for v in pins if v[3]=='right'];height=(max(len(left),len(right))+1)*2.54
        s=parse(f'(symbol "{name}" (pin_names (offset 0.508)) (in_bom yes) (on_board yes) (property "Reference" "U" (at 0 {height/2+2.54} 0) (effects (font (size 1.27 1.27)))) (property "Value" "{name}" (at 0 {height/2} 0) (effects (font (size 1.27 1.27)))) (property "Footprint" {json.dumps(footprint)} (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (property "Datasheet" {json.dumps(datasheet)} (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))) (property "Description" {json.dumps(description)} (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes))))')
        graphic=parse(f'(symbol "{name}_0_1" (rectangle (start -10.16 {height/2-1.27}) (end 10.16 {-height/2+1.27}) (stroke (width 0.254) (type default)) (fill (type background))))')
        body=[Atom('symbol'),name+'_1_1']
        for side,group in [('left',left),('right',right)]:
            for i,(num,label,typ,_) in enumerate(group):
                x=-12.7 if side=='left' else 12.7;y=(len(group)-1)*1.27-i*2.54;angle=0 if side=='left' else 180
                body.append(parse(f'(pin {typ} line (at {x} {y} {angle}) (length 2.54) (name {json.dumps(label)} (effects (font (size 1 1)))) (number "{num}" (effects (font (size 1 1)))))'))
        s.extend([graphic,body]);self.symbols[name]=s
    def copy_footprint(self,source):
        lib,name=source.split(':');shutil.copy2(SHARE/'footprints'/f'{lib}.pretty'/f'{name}.kicad_mod',self.fp/f'{name}.kicad_mod');return 'AIKEY:'+name
    def note(self,text,x,y):self.notes.append((text,x,y))
    def save(self):
        n=self.name
        for kind,suffix in [('sym','kicad_sym'),('fp','pretty')]:
            (self.out/f'{kind}-lib-table').write_text(f'({kind}_lib_table (version 7) (lib (name "AIKEY") (type "KiCad") (uri "${{KIPRJMOD}}/libraries/AIKEY.{suffix}") (options "") (descr "Pinned KiCad library; native source")))\n')
        (self.lib/'AIKEY.kicad_sym').write_text(dump([Atom('kicad_symbol_lib'),[Atom('version'),Atom('20250114')],[Atom('generator'),'kicad_symbol_editor']]+list(self.symbols.values()))+'\n')
        t=parse(f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "10.0") (uuid "{self.rootid}") (paper "{self.paper}") (title_block (title {json.dumps(self.title)}) (rev "A.2")) (lib_symbols) (sheet_instances (path "/" (page "1"))))')
        for s in self.symbols.values():
            v=copy.deepcopy(s);v[1]='AIKEY:'+s[1];one(t,'lib_symbols').append(v)
        for c in self.parts:
            ref=c['ref'];s=self.symbols[c['symbol']];x,y=c['sch'];onboard=bool(prop(s,'Footprint'))
            inst=parse(f'(symbol (lib_id "AIKEY:{c["symbol"]}") (at {x} {y} 0) (unit 1) (in_bom {"yes" if c["bom"] else "no"}) (on_board {"yes" if onboard else "no"}) (dnp no) (uuid "{uid(n+ref)}"))')
            fields={'Reference':ref,'Value':c['value'],'Footprint':prop(s,'Footprint'),'Datasheet':c['datasheet'] or prop(s,'Datasheet'),'Description':prop(s,'Description'),'MPN':c['mpn']}
            for k,v in fields.items():
                p=next((p for p in children(s,'property') if p[1]==k),None);a=one(p,'at') if p else None
                xx=x+float(a[1]) if a else x;yy=y-float(a[2]) if a else y
                hide='' if k in ('Reference','Value') else ' (hide yes)'
                inst.append(parse(f'(property {json.dumps(k)} {json.dumps(v)} (at {xx} {yy} 0) (effects (font (size 1.0 1.0)){hide}))'))
            emitted=set()
            for sub in children(s,'symbol'):
                for p in children(sub,'pin'):
                    num=str(one(p,'number')[1]);a=one(p,'at');px=round(x+float(a[1]),4);py=round(y-float(a[2]),4);angle=int(a[3]);net=c['nets'].get(num)
                    if num not in c['nets']:raise ValueError(f'{ref} pin {num} has no explicit assignment')
                    inst.append(parse(f'(pin "{num}" (uuid "{uid(n+ref+num)}"))'))
                    key=(px,py,net)
                    if key in emitted:continue
                    emitted.add(key)
                    if net is None:
                        t.append(parse(f'(no_connect (at {px} {py}) (uuid "{uid(n+ref+num+"nc")}"))'));continue
                    dx,dy={0:(-5.08,0),90:(0,5.08),180:(5.08,0),270:(0,-5.08)}[angle]
                    ex,ey=round(px+dx,4),round(py+dy,4)
                    t.append(parse(f'(wire (pts (xy {px} {py}) (xy {ex} {ey})) (stroke (width 0) (type default)) (uuid "{uid(n+ref+num+"wire")}"))'))
                    # Local labels intentionally produce /NET board names.
                    justify='right' if dx<0 else 'left'
                    t.append(parse(f'(label {json.dumps(net)} (at {ex} {ey} 0) (effects (font (size 1 1)) (justify {justify} bottom)) (uuid "{uid(n+ref+num+"label")}"))'))
            inst.append(parse(f'(instances (project "{n}" (path "/{self.rootid}" (reference "{ref}") (unit 1))))'));t.append(inst)
        for i,(text,x,y) in enumerate(self.notes):t.append(parse(f'(text {json.dumps(text)} (at {x} {y} 0) (effects (font (size 1.27 1.27)) (justify left top)) (uuid "{uid(n+"note"+str(i))}"))'))
        (self.out/f'{n}.kicad_sch').write_text(dump(t)+'\n')
        settings={'meta':{'version':1,'filename':n+'.kicad_pro'},'board':{'design_settings':{'rules':{'min_clearance':.15,'min_track_width':.15,'min_copper_edge_clearance':.3,'min_hole_clearance':.25,'min_hole_to_hole':.25,'min_via_diameter':.5,'min_through_hole_diameter':.3,'min_via_annular_width':.1,'min_text_height':.7,'min_text_thickness':.1},'drc_exclusions':[]}},'net_settings':{'meta':{'version':3},'classes':[{'name':'Default','clearance':.15,'track_width':.2,'via_diameter':.6,'via_drill':.3}]}}
        (self.out/f'{n}.kicad_pro').write_text(json.dumps(settings,indent=2)+'\n')
        (self.out/'design-input.json').write_text(json.dumps({'title':self.title,'size_mm':self.size,'parts':self.parts,'status':'routing and ERC/DRC must be checked separately'},indent=2)+'\n')
    def board(self):
        import pcbnew as p
        self.p=p;self.xy=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y));b=p.BOARD();self.b=b
        b.SetCopperLayerCount(self.layers);b.GetDesignSettings().SetBoardThickness(p.FromMM(self.thickness));b.GetDesignSettings().SetAuxOrigin(self.xy(50,50))
        w,h=self.size
        for a,z in [((50,50),(50+w,50)),((50+w,50),(50+w,50+h)),((50+w,50+h),(50,50+h)),((50,50+h),(50,50))]:
            line=p.PCB_SHAPE();line.SetShape(p.SHAPE_T_SEGMENT);line.SetStart(self.xy(*a));line.SetEnd(self.xy(*z));line.SetLayer(p.Edge_Cuts);line.SetWidth(p.FromMM(.05));b.Add(line)
        names={net for c in self.parts for net in c['nets'].values() if net is not None};self.nets={net:p.NETINFO_ITEM(b,'/'+net) for net in sorted(names)}
        nc={}
        for c in self.parts:
            for sub in children(self.symbols[c['symbol']],'symbol'):
                for pin in children(sub,'pin'):
                    num=str(one(pin,'number')[1])
                    if c['nets'][num] is None:
                        name=f'unconnected-({c["ref"]}-{one(pin,"name")[1]}-Pad{num})'
                        self.nets[name]=p.NETINFO_ITEM(b,name);nc[c['ref'],num]=name
        for net in self.nets.values():b.Add(net)
        self.fps={}
        for c in self.parts:
            s=self.symbols[c['symbol']];fp=prop(s,'Footprint')
            if not fp:continue
            assert c['pcb'] is not None,c['ref']
            fn=fp.split(':')[1];f=p.FootprintLoad(str(self.fp),fn);b.Add(f);f.SetReference(c['ref']);f.SetValue(c['value']);f.SetFPID(p.LIB_ID('AIKEY',fn))
            f.SetPosition(self.xy(*c['pcb']));f.SetOrientationDegrees(c['angle'])
            if c['back']:f.Flip(f.GetPosition(),False)
            path=p.KIID_PATH();path.push_back(p.KIID(self.rootid));path.push_back(p.KIID(uid(self.name+c['ref'])));f.SetPath(path)
            for pad in f.Pads():
                num=pad.GetNumber()
                if not num:continue
                net=c['nets'].get(num) or nc.get((c['ref'],num))
                if net is not None:pad.SetNet(self.nets[net])
            f.Reference().SetVisible(False);f.Value().SetVisible(False)
            for k,v in {'Datasheet':c['datasheet'] or prop(s,'Datasheet'),'Description':prop(s,'Description'),'MPN':c['mpn']}.items():f.SetField(k,v)
            for field in f.GetFields():field.SetVisible(False)
            self.fps[c['ref']]=f
        return b
    def route(self,net,points,layer=None,width=.2):
        p=self.p
        for a,z in zip(points,points[1:]):
            t=p.PCB_TRACK(self.b);t.SetStart(self.xy(*a));t.SetEnd(self.xy(*z));t.SetWidth(p.FromMM(width));t.SetLayer(p.F_Cu if layer is None else layer);t.SetNet(self.nets[net]);self.b.Add(t)
    def via(self,net,x,y):
        p=self.p;v=p.PCB_VIA(self.b);v.SetPosition(self.xy(x,y));v.SetWidth(p.FromMM(.6));v.SetDrill(p.FromMM(.3));v.SetViaType(p.VIATYPE_THROUGH);v.SetLayerPair(p.F_Cu,p.B_Cu);v.SetNet(self.nets[net]);self.b.Add(v)
    def save_board(self):
        dest=self.out/(self.name+'.kicad_pcb');self.p.SaveBoard(str(dest),self.b)
        check=self.p.LoadBoard(str(dest));assert len(list(check.GetFootprints()))==len(self.fps)
        # pcbnew.BOARD() starts with application defaults and SaveBoard may
        # overwrite the project. Restore the declared rules after this write.
        self.save()

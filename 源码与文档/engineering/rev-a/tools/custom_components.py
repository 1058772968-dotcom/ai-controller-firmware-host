"""Datasheet-defined native library items absent from installed KiCad library."""
from sexpr import parse,dump,children,one,prop,Atom
import json
def footprint(project,name,body,pads,description):
    w,h=body
    t=parse(f'(footprint "{name}" (version 20241229) (generator "pcbnew") (layer "F.Cu") (descr {json.dumps(description)}) (attr smd) (property "Reference" "REF**" (at 0 {-h/2-1} 0) (layer "F.SilkS") (effects (font (size 0.8 0.8) (thickness 0.12)))) (property "Value" "{name}" (at 0 {h/2+1} 0) (layer "F.Fab") (effects (font (size 0.8 0.8) (thickness 0.12)))) (fp_rect (start {-w/2} {-h/2}) (end {w/2} {h/2}) (stroke (width 0.1) (type default)) (layer "F.Fab")))')
    extent_x=max(w/2,max(abs(p[1])+p[3]/2 for p in pads))+.25
    extent_y=max(h/2,max(abs(p[2])+p[4]/2 for p in pads))+.25
    t.append(parse(f'(fp_rect (start {-extent_x} {-extent_y}) (end {extent_x} {extent_y}) (stroke (width 0.05) (type default)) (layer "F.CrtYd"))'))
    for n,x,y,pw,ph in pads:t.append(parse(f'(pad "{n}" smd roundrect (at {x} {y}) (size {pw} {ph}) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.15))'))
    (project.fp/(name+'.kicad_mod')).write_text(dump(t)+'\n')
    return 'AIKEY:'+name
def add_custom(project):
    pads=[(i,-.9,(i-3)*.5,.6,.25) for i in range(1,6)]
    pads += [(i,.55 if i==8 else .75,(8-i)*.5,1.3 if i==8 else .9,.25) for i in range(6,11)]
    fp=footprint(project,'TI_DLA0010A_TPS63802',(2,3),pads,'TI TPS63802 Rev D p36: recommended land pattern, no separate exposed pad')
    project.custom_symbol('TPS63802',[(1,'EN','input','left'),(2,'MODE','input','left'),(3,'AGND','power_in','left'),(4,'FB','input','left'),(5,'PG','open_collector','left'),(6,'VOUT','power_out','right'),(7,'L2','passive','right'),(8,'GND','power_in','right'),(9,'L1','passive','right'),(10,'VIN','power_in','right')],fp,'https://www.ti.com/lit/ds/symlink/tps63802.pdf','2A buck-boost; DLA0010A asymmetric power pads')
    fp=project.copy_footprint('Package_DFN_QFN:TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm')
    from sensor_lands import derivative
    fp=derivative(project.fp,fp.split(':')[1])
    project.custom_symbol('MAX17048',[(1,'CTG','power_in','left'),(2,'CELL','passive','left'),(3,'VDD','power_in','left'),(4,'GND','power_in','left'),(5,'ALRT_N','open_collector','right'),(6,'QSTRT','input','right'),(7,'SCL','input','right'),(8,'SDA','bidirectional','right'),(9,'EP','passive','left')],fp,'https://www.analog.com/media/en/technical-documentation/data-sheets/MAX17048-MAX17049.pdf','Single-cell ModelGauge; CELL tied to protected pack positive per datasheet')
    fp=project.copy_footprint('Package_LGA:LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y')
    fp=derivative(project.fp,fp.split(':')[1])
    project.custom_symbol('LSM6DSV16X',[(1,'SDO','output','right'),(2,'SDx_AH1','input','left'),(3,'SCx_AH2','input','left'),(4,'INT1','output','right'),(5,'VDDIO','power_in','left'),(6,'GND','power_in','left'),(7,'GND','passive','left'),(8,'VDD','power_in','left'),(9,'INT2','output','right'),(10,'OCS_AUX','input','left'),(11,'SDO_AUX','output','right'),(12,'CS_N','input','left'),(13,'SCLK','input','left'),(14,'SDI','input','left')],fp,'https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf','Mode 1, 4-wire SPI. AH/Qvar disabled. Package orientation review required before release.')
    fp=footprint(project,'Kingbright_APTF1616LSEEZGKQBKC',(1.6,1.6),[(1,.875,.5,.85,.5),(2,-.875,.5,.85,.5),(3,-.875,-.5,.85,.5),(4,.875,-.5,.85,.5)],'Kingbright V9B p1: 2.6x1.5 land span, 0.9 horizontal gap, 0.5 vertical gap; top-view pins')
    project.add_symbol('RGB','Device:LED_ARGB','')
    for p in children(project.symbols['RGB'],'property'):
        if p[1]=='Footprint':p[2]=fp
    return project

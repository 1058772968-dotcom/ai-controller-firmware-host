"""Manufacturer-defined derivatives; original installed-library assets retained."""
from pathlib import Path
from sexpr import parse,dump,children,one,Atom

VARIANTS = {
 'LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y':'ST_LSM6DSV16X_TN0018',
 'TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm':'ADI_MAX17048_90-0065_RevE',
}

def derivative(folder, original):
    folder=Path(folder); source=folder/(original+'.kicad_mod')
    if not source.exists():source=folder.parent/'reference-footprints'/(original+'.kicad_mod')
    t=parse(source.read_text())
    new=VARIANTS[original];t[1]=new
    for field in children(t,'property'):
        if field[1]=='Value':field[2]=new
    imu=original.startswith('LGA')
    one(t,'descr')[1]=('ST DS13510 Fig33 + TN0018 Rev8: .575x.35 equal copper lands; 80% paste area, .05 mask expansion. Native board MEMS keepout required.' if imu else 'ADI/Maxim land 90-0065 RevE: .70x.30 lands on 1.98 row pitch, .50 pin pitch; .80x1.38 EP. Four reduced paste windows.')
    for pad in children(t,'pad'):
        num=pad[1];at=one(pad,'at');size=one(pad,'size')
        if imu:
            size[1:]=[.575,.35] if abs(float(at[1]))>1 else [.35,.575]
            one(pad,'roundrect_rratio')[1]=.10
            pad.append([Atom('solder_mask_margin'),.05])
            # Scaling each dimension by sqrt(.8) gives 80% copper area.
            pad.append([Atom('solder_paste_margin_ratio'),-.0527864045])
        elif num=='9':size[1:]=[.8,1.38]
        elif num:
            at[1]=-.99 if float(at[1])<0 else .99
            size[1:]=[.70,.30]
            one(pad,'roundrect_rratio')[1]=.10
        else:
            at[1]=-.2 if float(at[1])<0 else .2
            at[2]=-.345 if float(at[2])<0 else .345
            size[1:]=[.32,.552]
    (folder/(new+'.kicad_mod')).write_text(dump(t)+'\n')
    return 'AIKEY:'+new

#!/usr/bin/env python3
"""Update only U4/U6 land geometry; audit saved-native traces against MEMS rules."""
from pathlib import Path
import json,copy,shutil,hashlib
from shapely.geometry import box,LineString,Point
from shapely.ops import unary_union
from sexpr import parse,dump,children,one,prop,Atom,uid
from sensor_lands import derivative,VARIANTS

R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_main';B=P/'aikey_main.kicad_pcb';L=P/'libraries/AIKEY.pretty'
archive=R/'reports/history/before-sensor-land-review';archive.mkdir(parents=True,exist_ok=True)
for file in [B,P/'aikey_main.kicad_sch',P/'aikey_main.kicad_pro',P/'libraries/AIKEY.kicad_sym',R/'reports/main-board-drc.json']:
    target=archive/file.name
    if not target.exists():shutil.copy2(file,target)
for old in VARIANTS:derivative(L,old)
for file in [P/'aikey_main.kicad_sch',P/'libraries/AIKEY.kicad_sym']:
    data=file.read_text()
    for old,new in VARIANTS.items():data=data.replace('AIKEY:'+old,'AIKEY:'+new)
    file.write_text(data)
t=parse(B.read_text());updated=[]
for fp in children(t,'footprint'):
    ref=prop(fp,'Reference')
    if ref not in ('U4','U6'):continue
    old=next(old for old,new in VARIANTS.items() if fp[1] in ('AIKEY:'+old,'AIKEY:'+new))
    new=VARIANTS[old];lib=parse((L/(new+'.kicad_mod')).read_text());fp[1]='AIKEY:'+new
    oldpads=children(fp,'pad');newpads=children(lib,'pad')
    if [v[1] for v in oldpads]!=[v[1] for v in newpads]:raise RuntimeError('Pad correspondence changed')
    for target,source in zip(oldpads,newpads):
        for key in ('at','size','roundrect_rratio','solder_mask_margin','solder_paste_margin_ratio'):
            for n in children(target,key):target.remove(n)
            value=one(source,key)
            if value:target.append(copy.deepcopy(value))
    one(fp,'descr')[1]=one(lib,'descr')[1]
    updated.append({'ref':ref,'footprint':fp[1]})

imu=next(fp for fp in children(t,'footprint') if prop(fp,'Reference')=='U4')
a=one(imu,'at');cx,cy=map(float,a[1:3])
if len(a)>3 and float(a[3])!=0:raise RuntimeError('Review keepout transform for rotated IMU')
body=box(cx-1.5,cy-1.25,cx+1.5,cy+1.25)
escapes=[]
for pad in children(imu,'pad'):
    x,y=map(float,one(pad,'at')[1:3]);w,h=map(float,one(pad,'size')[1:3])
    if abs(x)>1:
        escapes.append(box(cx+(x-w/2 if x>0 else -1.5),cy+y-h/2,cx+(1.5 if x>0 else x+w/2),cy+y+h/2))
    else:
        escapes.append(box(cx+x-w/2,cy+(y-h/2 if y>0 else -1.25),cx+x+w/2,cy+(1.25 if y>0 else y+h/2)))
forbidden=body.difference(unary_union(escapes))
polygons=list(forbidden.geoms) if forbidden.geom_type=='MultiPolygon' else [forbidden]
for z in children(t,'zone'):
    if one(z,'name') and str(one(z,'name')[1]).startswith('MEMS_'):t.remove(z)
def keepout(name,polygon,tracks,vias,pour):
    if polygon.interiors:raise RuntimeError('Unexpected keepout hole')
    pts=' '.join(f'(xy {x:.6f} {y:.6f})' for x,y in list(polygon.exterior.coords)[:-1])
    return parse(f'(zone (net 0) (net_name "") (layer "F.Cu") (uuid "{uid(name)}") (name "{name}") (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.1) (keepout (tracks {tracks}) (vias {vias}) (pads allowed) (copperpour {pour}) (footprints allowed)) (fill (thermal_gap 0.3) (thermal_bridge_width 0.3)) (polygon (pts {pts})))')
for i,polygon in enumerate(polygons):t.append(keepout('MEMS_TOP_'+str(i),polygon,'not_allowed','allowed','not_allowed'))
t.append(keepout('MEMS_NO_VIA',body,'allowed','not_allowed','allowed'))
violations=[]
for item in children(t,'segment')+children(t,'via'):
    via=item[0]=='via'
    if not via and one(item,'layer')[1]!='F.Cu':continue
    if via:
        a=one(item,'at');geom=Point(float(a[1]),float(a[2])).buffer(float(one(item,'size')[1])/2)
    else:
        a=one(item,'start');b=one(item,'end');geom=LineString([(float(a[1]),float(a[2])),(float(b[1]),float(b[2]))]).buffer(float(one(item,'width')[1])/2)
    overlap=geom.intersection(body if via else forbidden).area
    if overlap>1e-9:violations.append({'uuid':one(item,'uuid')[1],'type':item[0],'net':one(item,'net')[1],'overlap_mm2':overlap})
B.write_text(dump(t)+'\n')
report={'status':'LANDS_UPDATED_ROUTING_REPAIR_REQUIRED' if violations else 'LANDS_UPDATED_NATIVE_DRC_REQUIRED','native_board':str(B),'sha256':hashlib.sha256(B.read_bytes()).hexdigest(),
 'updated':updated,'under_body_violations':violations,'keepout':'Entire 3x2.5 mm body excludes via annuli. Top copper excludes everything except the fourteen radial pad/escape corridors.',
 'sources':{'MAX17048':'https://mds.analog.com/api/public/content/tdfn_90-0065.pdf','LSM6DSV16X':'https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf','MEMS':'https://www.st.com/resource/en/technical_note/CD00134799.pdf'},
 'requires':['repair native keepout violations','native ERC and DRC including schematic parity','readback pad dimensions and package orientation']}
(R/'reports/sensor-land-review.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

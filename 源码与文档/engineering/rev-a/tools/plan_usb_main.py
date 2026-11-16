#!/usr/bin/env python3
"""Plan length tuning and return vias from the current native copper snapshot."""
from pathlib import Path
import json,math
from shapely.geometry import Point,LineString,box
from shapely.ops import unary_union
from shapely.prepared import prep
R=Path(__file__).resolve().parents[1];d=json.loads((R/'reports/main-copper-geometry.json').read_text());items=d['items']
usb={'/USB_DP','/USB_DM','/MCU_USB_DP','/MCU_USB_DM'}
lengths={n:sum(math.dist(i['start'],i['end']) for i in items if i['kind']=='track' and i['net']==n) for n in usb}
delta=lengths['/USB_DM']+lengths['/MCU_USB_DM']-lengths['/USB_DP']-lengths['/MCU_USB_DP']
amplitude=(delta/4+.8-.4*math.sqrt(2))/2
assert .4<amplitude<.79
points=[(51.2,71.8)]
for y in (77.8,79.8,81.8,83.8):points += [(51.2,y),(51.,y+.2),(51.2-amplitude,y+.2),(51.2-amplitude,y+.7),(51.,y+.7),(51.2,y+.9)]
points.append((51.2,89.))
old=next(i for i in items if i['kind']=='track' and i['net']=='/USB_DP' and sorted([i['start'],i['end']])==sorted([[51.2,71.8],[51.2,89.]]))
def geom(i):
 if i['kind']=='pad':return box(*i['box'])
 if i['kind']=='via':return Point(i['center']).buffer(i['diameter']/2,resolution=24)
 return LineString([i['start'],i['end']]).buffer((.19 if i['net'] in usb else i['width'])/2,resolution=24)
# Grounded copper pours are not obstacles; other signal copper and every drill are.
obstacles=prep(unary_union([geom(i).buffer(.40001,resolution=16) for i in items if i['net']!='/GND']))
holes=[Point(i['center']).buffer(.15+i['drill']/2+.25001,resolution=16) for i in items if i['kind']=='via']
vias=[];readback=[]
for s in [i for i in items if i['kind']=='via' and i['net'] in usb]:
 ground=[i['center'] for i in items if i['kind']=='via' and i['net']=='/GND']+vias
 nearest=min(ground,key=lambda x:math.dist(x,s['center']))
 if math.dist(nearest,s['center'])>1.5:
  blocked=prep(unary_union(holes));cx,cy=s['center'];found=None
  candidates=sorted(((i*.025,j*.025) for i in range(-72,73) for j in range(-72,73) if i or j),key=lambda q:math.hypot(*q))
  for dx,dy in candidates:
   q=(round(cx+dx,6),round(cy+dy,6));p=Point(q)
   if not (50.56<q[0]<73.44 and 50.56<q[1]<91.44):continue
   if not obstacles.intersects(p) and not blocked.intersects(p):found=q;break
  if found is None:raise RuntimeError('No ground return via near USB transition')
  vias.append(found);holes.append(Point(found).buffer(.55001));nearest=found
 readback.append({'signal_via':s['center'],'net':s['net'],'ground_via':nearest,'distance_mm':math.dist(nearest,s['center'])})
resize=[i['uuid'] for i in items if i['kind']=='via' and abs(i['center'][0]-50.6675)<.0001 and any(abs(i['center'][1]-y)<.0001 for y in (72.3206,74.85,77.2355,85.5825))]
report={'edge_control_via_pad_mm':.55,'resize_via_uuids':resize,'status':'CANDIDATES_NATIVE_DRC_REQUIRED','source_native_sha256':d['native_sha256'],'original_lengths_mm':lengths,'original_skew_mm':delta,'width_mm':.19,'pair_gap_mm':.16,'replace_track_uuid':old['uuid'],'tuning_points_mm':points,'tuning_extra_length_mm':sum(math.dist(a,b) for a,b in zip(points,points[1:]))-17.2,'ground_vias_mm':vias,'return_distances':readback,'via_pad_mm':.5,'via_drill_mm':.3}
(R/'reports/usb-main-plan.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

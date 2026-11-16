#!/usr/bin/env python3
"""Find short native-DRC candidates outside MEMS body; never a DRC substitute."""
from pathlib import Path
import json,math,heapq
from shapely.geometry import box,Point,LineString,Polygon
from shapely.ops import unary_union
from shapely.prepared import prep
from sexpr import parse,children,one
R=Path(__file__).resolve().parents[1];data=json.loads((R/'reports/main-copper-geometry.json').read_text());items=data['items']
t=parse((R/'electrical/aikey_main/aikey_main.kicad_pcb').read_text())
keepouts=[Polygon([(float(p[1]),float(p[2])) for p in children(one(one(z,'polygon'),'pts'),'xy')]) for z in children(t,'zone') if one(z,'name') and str(one(z,'name')[1]).startswith('MEMS_TOP')]
body=box(60.5,73.25,63.5,75.75)
def geom(i):
 if i['kind']=='pad':return box(*i['box'])
 if i['kind']=='via':return Point(i['center']).buffer(i['diameter']/2,resolution=24)
 return LineString([i['start'],i['end']]).buffer(i['width']/2,resolution=24)
plans=[]
# Existing project fabrication rules allow 0.50 mm lands, 0.30 mm drilled vias,
# and 0.10 mm annuli. Use that documented minimum in this dense local fanout;
# do not reduce any copper, drill or annular-ring design rule.
via_diameter=.50;via_drill=.30;via_radius=via_diameter/2
for num in ('4','12','2','3','6','7','5','8','10'):
 pad=next(i for i in items if i['kind']=='pad' and i['ref']=='U4' and i['number']==num);net=pad['net'];x,y=pad['center']
 start=(60.1,y) if x<61 else (63.9,y) if x>63 else (x,72.9) if y<74 else (x,76.1)
 other=[i for i in items if i['net']!=net]
 fobs=[geom(i).buffer(.22501,resolution=16) for i in other if i['kind']=='via' or i['kind']=='pad' and 'F.Cu' in i['layers'] or i['kind']=='track' and i['layer']=='F.Cu']
 fobs += [k.buffer(.07501,resolution=16) for k in keepouts]
 wire_block=prep(unary_union(fobs))
 viaobs=[geom(i).buffer(via_radius+.15001,resolution=16) for i in other]
 viaobs += [Point(i['center']).buffer(.15+i['drill']/2+.25001,resolution=16) for i in items if i['kind']=='via']
 viaobs += [body.buffer(via_radius+.00001,resolution=16)]
 via_block=prep(unary_union(viaobs))
 same=[tuple(i['center']) for i in items if i['kind']=='via' and i['net']==net]
 # Nodes are 0.05 mm relative to the already reviewed radial escape endpoint.
 grid=.05;front=[(0.,(0,0))];dist={(0,0):0.};prev={};finish=None;reuse=None;expanded=0
 coords=lambda n:(round(start[0]+n[0]*grid,6),round(start[1]+n[1]*grid,6))
 while front:
  cost,n=heapq.heappop(front)
  if cost>dist[n]+1e-8:continue
  point=coords(n);expanded+=1
  for old in same:
   if math.dist(point,old)<.3 and not wire_block.intersects(LineString([point,old])):finish=n;reuse=old;break
  if finish is not None:break
  if not via_block.intersects(Point(point)) and math.dist(point,start)>=.05:finish=n;break
  if expanded>18000:break
  for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,-1),(1,-1),(-1,1)):
   m=(n[0]+dx,n[1]+dy)
   if abs(m[0])>50 or abs(m[1])>50:continue
   target=coords(m);newcost=cost+math.hypot(dx,dy)*grid
   if newcost>=dist.get(m,float('inf')):continue
   if wire_block.intersects(LineString([point,target])):continue
   dist[m]=newcost;prev[m]=n;heapq.heappush(front,(newcost,m))
 if finish is None:
  blockers=[i for i in other if geom(i).distance(Point(start))<.226 and (i['kind']=='via' or i['kind']=='pad' and 'F.Cu' in i['layers'] or i['kind']=='track' and i['layer']=='F.Cu')]
  print('Start blockers',blockers,flush=True)
  raise RuntimeError('No safe local via path for U4 pad '+num)
 nodes=[finish]
 while nodes[-1]!=(0,0):nodes.append(prev[nodes[-1]])
 points=[coords(n) for n in reversed(nodes)]
 if reuse:points.append(reuse)
 # Coalesce collinear grid edges without changing the searched path.
 out=[]
 for q in points:
  if len(out)>1:
   a,b=out[-2:];cross=(b[0]-a[0])*(q[1]-b[1])-(b[1]-a[1])*(q[0]-b[0])
   if abs(cross)<1e-9:out.pop()
  out.append(q)
 plan={'pad':num,'net':net,'points_mm':out,'via_center_mm':out[-1],'reuse_via':bool(reuse),'search_expanded':expanded};plans.append(plan);print(plan,flush=True)
 for a,b in zip(out,out[1:]):items.append({'kind':'track','net':net,'start':a,'end':b,'width':.15,'layer':'F.Cu'})
 if not reuse:items.append({'kind':'via','net':net,'center':out[-1],'diameter':via_diameter,'drill':via_drill})
(R/'reports/sensor-via-plan.json').write_text(json.dumps({'status':'CANDIDATES_NATIVE_DRC_REQUIRED','source_native_sha256':data['native_sha256'],'plans':plans,'rules':{'track_width_mm':.15,'copper_clearance_mm':.15,'via_pad_mm':via_diameter,'via_drill_mm':via_drill,'hole_to_hole_clearance_mm':.25},'method':'Shortest local 45-degree escape paths; conservative placed-pad bounding boxes, exact straight traces and circular vias, explicit MEMS keepouts. All native layers checked for proposed via copper. Native DRC remains authoritative.'},indent=2)+'\n')

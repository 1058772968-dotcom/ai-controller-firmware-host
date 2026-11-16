#!/usr/bin/env python3
"""Conservative local three-layer route candidates; native DRC is authoritative."""
from pathlib import Path
import json,math,heapq,functools
from shapely.geometry import box,Point,LineString,Polygon
from shapely.ops import unary_union
from shapely.prepared import prep
from sexpr import parse,children,one
R=Path(__file__).resolve().parents[1]
data=json.loads((R/'reports/main-copper-geometry.json').read_text());items=data['items']
tree=parse((R/'electrical/aikey_main/aikey_main.kicad_pcb').read_text())
keepouts=[Polygon([(float(p[1]),float(p[2])) for p in children(one(one(z,'polygon'),'pts'),'xy')]) for z in children(tree,'zone') if one(z,'name') and str(one(z,'name')[1]).startswith('MEMS_TOP')]
layers=['F.Cu','In3.Cu','B.Cu'];net='/IMU_CS';grid=.05
def geom(i):
    if i['kind']=='pad':return box(*i['box'])
    if i['kind']=='via':return Point(i['center']).buffer(i['diameter']/2,resolution=24)
    return LineString([i['start'],i['end']]).buffer(i['width']/2,resolution=24)
def on(i,l):return i['kind']=='via' or i['kind']=='pad' and l in i['layers'] or i['kind']=='track' and i['layer']==l
def xy(n):return (round(n[0]*grid,6),round(n[1]*grid,6))
plans=[]
for ref,num in [('U1','18'),('R25','2')]:
    pad=next(i for i in items if i['kind']=='pad' and i['ref']==ref and i['number']==num)
    other=[i for i in items if i['net']!=net]
    obs={l:prep(unary_union([geom(i).buffer(.22501,resolution=16) for i in other if on(i,l)]+([g.buffer(.07501) for g in keepouts] if l=='F.Cu' else []))) for l in layers}
    viaobs=prep(unary_union([geom(i).buffer(.40001,resolution=16) for i in other]+[Point(i['center']).buffer(.15+i['drill']/2+.25001,resolution=16) for i in items if i['kind']=='via']+[box(60.5,73.25,63.5,75.75).buffer(.25001)]))
    # The reviewed CS fanout terminates in an existing through via.
    gx,gy=[round(v/grid) for v in (63.1,71.6)]
    start=(*[round(v/grid) for v in pad['center']],0)
    if obs['F.Cu'].intersects(LineString([pad['center'],xy(start)])):raise RuntimeError('Pad grid-entry collision')
    @functools.lru_cache(None)
    def valid_via(x,y):
        pt=xy((x,y));return not viaobs.intersects(Point(pt)) and all(not o.intersects(Point(pt)) for o in obs.values())
    @functools.lru_cache(None)
    def edge(a,b):return not obs[layers[a[2]]].intersects(LineString([xy(a),xy(b)]))
    def heuristic(n):return math.hypot(n[0]-gx,n[1]-gy)*grid
    heap=[(heuristic(start),0.,start)];dist={start:0.};prev={};end=None;count=0
    while heap:
        _,cost,n=heapq.heappop(heap)
        if cost>dist[n]+1e-8:continue
        count+=1
        if n[:2]==(gx,gy) or any(s['layer']==layers[n[2]] and LineString(s['points']).distance(Point(xy(n)))<1e-7 for prior in plans for s in prior['segments']):end=n;break
        if count>300000:break
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,-1),(1,-1),(-1,1)):
            m=(n[0]+dx,n[1]+dy,n[2]);px,py=xy(m)
            if not (50.4<=px<=73.6 and 65.<=py<=82.):continue
            nc=cost+math.hypot(dx,dy)*grid
            if nc>=dist.get(m,float('inf')) or not edge(n,m):continue
            dist[m]=nc;prev[m]=n;heapq.heappush(heap,(nc+heuristic(m),nc,m))
        # Through-hole vias are kept out of the source SMD land.
        if box(*pad['box']).distance(Point(xy(n)))>.25001 and valid_via(n[0],n[1]):
            for l in range(3):
                if l==n[2]:continue
                m=(*n[:2],l);nc=cost+1.5
                if nc<dist.get(m,float('inf')):dist[m]=nc;prev[m]=n;heapq.heappush(heap,(nc+heuristic(m),nc,m))
    if end is None:
        (R/'reports/cs-route-failed-region.json').write_text(json.dumps({'pad':pad,'visited':[list(n) for n in dist],'ref':ref}))
        raise RuntimeError('No local CS route for '+ref+' after '+str(count)+' nodes')
    nodes=[end]
    while nodes[-1]!=start:nodes.append(prev[nodes[-1]])
    nodes.reverse();segments=[];vias=[]
    if tuple(pad['center'])!=xy(start):segments.append({'layer':'F.Cu','points':[pad['center'],xy(start)]})
    for a,b in zip(nodes,nodes[1:]):
        if a[2]!=b[2]:vias.append(xy(a));continue
        layer=layers[a[2]];p1,p2=xy(a),xy(b)
        if segments and segments[-1]['layer']==layer and tuple(segments[-1]['points'][-1])==p1:
            pts=segments[-1]['points']
            if len(pts)>1:
                aa,bb=pts[-2:]
                if abs((bb[0]-aa[0])*(p2[1]-bb[1])-(bb[1]-aa[1])*(p2[0]-bb[0]))<1e-9:pts.pop()
            pts.append(p2)
        else:segments.append({'layer':layer,'points':[p1,p2]})
    # Collapse raster stairs only when the whole replacement segment clears every obstacle.
    for segment in segments:
        raw=segment['points'];smooth=[raw[0]];at=0
        while at<len(raw)-1:
            far=len(raw)-1
            while far>at+1 and obs[segment['layer']].intersects(LineString([raw[at],raw[far]])):far-=1
            smooth.append(raw[far]);at=far
        segment['points']=smooth
    plan={'source_pad':[ref,num],'net':net,'segments':segments,'vias':vias,'expanded_nodes':count};plans.append(plan);print(json.dumps(plan),flush=True)
    for s in segments:
        for a,b in zip(s['points'],s['points'][1:]):items.append({'kind':'track','net':net,'start':a,'end':b,'width':.15,'layer':s['layer']})
    for v in vias:items.append({'kind':'via','net':net,'center':v,'diameter':.5,'drill':.3})
(R/'reports/cs-route-plan.json').write_text(json.dumps({'status':'CANDIDATES_NATIVE_DRC_REQUIRED','source_native_sha256':data['native_sha256'],'plans':plans,'width_mm':.15,'via_pad_mm':.5,'via_drill_mm':.3,'clearance_mm':.15},indent=2)+'\n')

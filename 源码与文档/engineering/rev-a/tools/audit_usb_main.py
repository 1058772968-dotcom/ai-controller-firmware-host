#!/usr/bin/env python3
"""Read saved routing as a graph, including layer transitions and actual pad centres."""
import json,math,heapq,hashlib,shutil
from pathlib import Path
from collections import defaultdict
from sexpr import parse,one,children
R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_main';file=P/'aikey_main.kicad_pcb'
j=json.loads((R/'reports/main-copper-geometry.json').read_text());items=j['items'];sha=hashlib.sha256(file.read_bytes()).hexdigest()
assert sha==j['native_sha256']
tree=parse(file.read_text());stack=one(one(tree,'setup'),'stackup');layers=children(stack,'layer')
z=0.;copper_z={};readback=[]
for l in layers:
    thickness=float(one(l,'thickness')[1]) if one(l,'thickness') else 0.
    if str(l[1]).endswith('.Cu'):copper_z[l[1]]=z+thickness/2
    readback.append({'name':l[1],'thickness_mm':thickness,'type':one(l,'type')[1]});z+=thickness
assert abs(z-1.)<1e-9
def node(layer,p):return (layer,round(p[0]*1e6),round(p[1]*1e6))
def pad(ref,num):return next(i for i in items if i['kind']=='pad' and i['ref']==ref and i['number']==str(num))
def path_length(net,source,dest):
    graph=defaultdict(list);segments=[i for i in items if i['kind']=='track' and i['net']==net]
    def link(a,b,w):graph[a].append((b,w));graph[b].append((a,w))
    for i in segments:
        assert abs(i['width']-.19)<1e-8
        link(node(i['layer'],i['start']),node(i['layer'],i['end']),math.dist(i['start'],i['end']))
    for i in items:
        if i['kind']=='via' and i['net']==net:
            for a,b in zip(list(copper_z),list(copper_z)[1:]):link(node(a,i['center']),node(b,i['center']),abs(copper_z[a]-copper_z[b]))
    a=pad(*source);b=pad(*dest);start=node(a['layers'][0],a['center']);end=node(b['layers'][0],b['center'])
    q=[(0.,start)];dist={start:0.};prev={}
    while q:
        d,n=heapq.heappop(q)
        if d>dist[n]+1e-8:continue
        if n==end:break
        for m,w in graph[n]:
            x=d+w
            if x<dist.get(m,float('inf')):dist[m]=x;prev[m]=n;heapq.heappush(q,(x,m))
    assert end in dist,(net,'not connected')
    path=[end]
    while path[-1]!=start:path.append(prev[path[-1]])
    via_count=sum(a[0]!=b[0] for a,b in zip(path,path[1:]))//(len(copper_z)-1)
    return {'net':net,'source_pad':source,'destination_pad':dest,'centerline_3d_mm':dist[end],'planar_track_sum_mm':sum(math.dist(i['start'],i['end']) for i in segments),'through_vias':via_count,'path_nodes':len(path)}
routes=[path_length('/MCU_USB_DP',('U1',14),('R3',1)),path_length('/USB_DP',('R3',2),('TP3',1)),path_length('/MCU_USB_DM',('U1',13),('R4',1)),path_length('/USB_DM',('R4',2),('TP4',1))]
lengths=[sum(v['centerline_3d_mm'] for v in routes[:2]),sum(v['centerline_3d_mm'] for v in routes[2:])]
assert abs(lengths[0]-lengths[1])<.001
drc=R/'reports/usb-main-drc.json';d=json.loads(drc.read_text());assert not any(d[k] for k in ('violations','unconnected_items','schematic_parity'))
report={'status':'MAIN_USB_GEOMETRY_DRC_PASS_CHANNEL_SI_PENDING','native_board_sha256':sha,'routes':routes,'dp_dm_3d_centerlines_excluding_equal_resistor_bodies_mm':lengths,'skew_mm':abs(lengths[0]-lengths[1]),'width_mm':.19,'parallel_center_pitch_mm':.35,'parallel_gap_mm':.16,'stackup':readback,'stackup_total_including_mask_mm':z,'signal_reference_layers':{'F.Cu':'In1.Cu GND','B.Cu':'In4.Cu GND'},'return_vias':'reports/usb-main-plan.json','impedance_model':'reports/usb-impedance-calculation.json','drc_sha256':hashlib.sha256(drc.read_bytes()).hexdigest(),'limitations':['This graph measures PCB copper centreline and through-via barrel lengths. Equal resistor body electrical delay is not modelled.','Width/gap impedance calculation covers ideal uniform paired microstrip only; tuning, fanouts, solder pads, finite ground edges and the inter-board harness need whole-channel review.','Controlled-impedance fabrication and USB electrical compliance require actual boards. No physical acceptance is claimed.']}
(R/'reports/usb-main-acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
archive=R/'reports/history/main-usb-geometry-pass';archive.mkdir(exist_ok=True)
for f in (file,P/'aikey_main.kicad_sch',P/'aikey_main.kicad_pro',drc,R/'reports/usb-main-acceptance.json'):
    target=archive/f.name
    if target.exists() and target.read_bytes()!=f.read_bytes():raise RuntimeError('Milestone already exists with different content')
    shutil.copy2(f,target)
print(report['status'], 'DP/DM',lengths,'skew',report['skew_mm'])

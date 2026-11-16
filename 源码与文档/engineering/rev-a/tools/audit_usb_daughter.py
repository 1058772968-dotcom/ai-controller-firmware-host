#!/usr/bin/env python3
import json,math,heapq,hashlib,shutil
from pathlib import Path
from collections import defaultdict
from sexpr import parse,one,children,prop
R=Path(__file__).resolve().parents[1];P=R/'electrical/aikey_usb';file=P/'aikey_usb.kicad_pcb';backup=R/'reports/history/before-usb-daughter'/file.name
j=json.loads((R/'reports/usb-copper-geometry.json').read_text());items=j['items'];sha=hashlib.sha256(file.read_bytes()).hexdigest();assert sha==j['native_sha256']
t=parse(file.read_text());old=parse(backup.read_text())
for fp in children(t,'footprint'):
    before=next(o for o in children(old,'footprint') if prop(o,'Reference')==prop(fp,'Reference'))
    assert one(fp,'at')==one(before,'at') and one(fp,'layer')==one(before,'layer')
layers=children(one(one(t,'setup'),'stackup'),'layer');z=0.;cuz={}
for l in layers:
    h=float(one(l,'thickness')[1]) if one(l,'thickness') else 0.
    if str(l[1]).endswith('.Cu'):cuz[l[1]]=z+h/2
    z+=h
assert abs(z-.8)<1e-9
def node(l,p):return (l,round(p[0]*1e6),round(p[1]*1e6))
def pad(r,n):return next(i for i in items if i['kind']=='pad' and i['ref']==r and i['number']==n)
def measure(net,pin,target):
    g=defaultdict(list)
    def link(a,b,w):g[a].append((b,w));g[b].append((a,w))
    for i in items:
        if i['net']!=net:continue
        if i['kind']=='track':
            assert abs(i['width']-.23)<1e-8
            link(node(i['layer'],i['start']),node(i['layer'],i['end']),math.dist(i['start'],i['end']))
        if i['kind']=='via':link(node('F.Cu',i['center']),node('B.Cu',i['center']),cuz['B.Cu']-cuz['F.Cu'])
    a=pad('J1',pin);b=pad(target,'1');start=node('F.Cu',a['center']);end=node('F.Cu',b['center']);q=[(0.,start)];dist={start:0.};prev={}
    while q:
        x,n=heapq.heappop(q)
        if x>dist[n]+1e-8:continue
        if n==end:break
        for m,w in g[n]:
            if x+w<dist.get(m,float('inf')):dist[m]=x+w;prev[m]=n;heapq.heappush(q,(x+w,m))
    assert end in dist
    path=[end]
    while path[-1]!=start:path.append(prev[path[-1]])
    return {'pin':pin,'net':net,'terminal':target,'length_3d_mm':dist[end],'through_vias':sum(a[0]!=b[0] for a,b in zip(path,path[1:]))}
rows=[measure('/USB_DP','A6','TP3'),measure('/USB_DM','A7','TP4'),measure('/USB_DP','B6','TP3'),measure('/USB_DM','B7','TP4')]
skews={orientation:rows[i]['length_3d_mm']-rows[i+1]['length_3d_mm'] for orientation,i in [('A',0),('B',2)]}
assert all(abs(x)<.5 for x in skews.values()),skews
drc=R/'reports/usb-daughter-drc.json';d=json.loads(drc.read_text());assert not any(d[k] for k in ('violations','unconnected_items','schematic_parity'))
report={'status':'DAUGHTER_ROUTING_GEOMETRY_DRC_PASS_CHANNEL_SI_PENDING','native_board_sha256':sha,'total_thickness_including_mask_mm':z,'copper_layers':list(cuz),'reference_planes':['In1.Cu GND','In2.Cu GND'],'placements':'all footprint positions and sides identical to archived board','routing_width_mm':.23,'contact_to_terminal_paths':rows,'dp_minus_dm_skew_mm_by_connector_row':skews,'drc_sha256':hashlib.sha256(drc.read_bytes()).hexdigest(),'limitations':['USB-C duplicated-contact branch lengths differ by plug orientation. Length matching limit here is 0.5 mm including through-via barrel length.','This short crossover is not a uniform coupled transmission line. Pads, fork stubs, via transitions, ground pours and harness require complete-channel review.','No electrical compliance, ESD stress or physical connector test has been run.']}
(R/'reports/usb-daughter-acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
archive=R/'reports/history/usb-daughter-geometry-pass';archive.mkdir(exist_ok=True)
for f in (file,P/'aikey_usb.kicad_sch',P/'aikey_usb.kicad_pro',drc,R/'reports/usb-daughter-acceptance.json'):
    out=archive/f.name
    if out.exists() and out.read_bytes()!=f.read_bytes():raise RuntimeError('Prior milestone differs')
    shutil.copy2(f,out)
print(report['status'],skews)

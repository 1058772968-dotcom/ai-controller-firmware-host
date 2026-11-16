#!/usr/bin/env python3
"""Independently measure acoustic continuity and the maximum LRA body fit."""
from pathlib import Path
import sys,json,math,hashlib,argparse
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
ap=argparse.ArgumentParser();ap.add_argument('--revision',required=True);opt=ap.parse_args()
path=R/f'mechanical/AIKEY_REVA_DESIGN{opt.revision}.FCStd';d=A.openDocument(str(path));fail=[]
# A continuous air gauge runs from the PCB acoustic back face through the
# installed gasket and housing outlet, extending well outside the native lid.
air=Part.makeCylinder(.65,13,V(-13,107.5,-6),V(0,1,0));obstructions=[]
for o in d.Assembly.Group:
    if not air.BoundBox.intersect(o.Shape.BoundBox):continue
    v=overlap_volume(air,o.Shape)
    if v>1e-5:obstructions.append({'part':o.Name,'mm3':v})
if obstructions:fail.append('Acoustic path blocked')
gasket=d.MicAcousticGasket.Shape;expected=math.pi*(1.5**2-.7**2)*.5
assert len(gasket.Solids)==1 and abs(gasket.Volume-expected)<1e-6
contacts={n:gasket.distToShape(d.getObject(n).Shape)[0] for n in ('MicPCBAssembly','TopCoverSupported')}
if max(contacts.values())>1e-6:fail.append('Seal interface gap')
# Manufacturer maximum diameter and height, preserving installed adhesive Z.
max_lra=Part.makeCylinder(5.05,3.85,V(0,24,4.15));lra_contacts=[]
for o in d.Assembly.Group:
    if o.Name=='LRA' or not max_lra.BoundBox.intersect(o.Shape.BoundBox):continue
    v=overlap_volume(max_lra,o.Shape)
    if v>1e-5:lra_contacts.append({'part':o.Name,'mm3':v})
if lra_contacts:fail.append('Maximum LRA envelope collision')
adh=d.LRAAdhesive.Shape
adh_contacts={n:adh.distToShape(d.getObject(n).Shape)[0] for n in ('LRA','FingerShellSupported')}
if max(adh_contacts.values())>1e-6:fail.append('LRA bonded face disconnected')
# Hole axis/mic port retained in the native saved placement, not copied from
# a design note. This is the independently read KiCad hole at (54.18,53.5).
native_port=d.MicPCBAssembly.Shape.Placement.multVec(V(4.18,-3.5,0))
if (native_port-V(-13,107.5,-6)).Length>1e-6:fail.append('Acoustic port misalignment')
pcb=next(b for b in json.loads((R/'reports/ecad-fiducial-source.json').read_text())['boards'] if b['board']=='aikey_mic')
wire_checks=[]
for pad in pcb['pads']:
    if not pad['ref'].startswith('TP'):continue
    x,y=pad['xy_mm'];point=d.MicPCBAssembly.Shape.Placement.multVec(V(x-50,-(y-50),0))
    gauge=Part.makeCylinder(.6,1.3,point,V(0,1,0));hits=[]
    for obj in d.Assembly.Group:
        if obj.Name=='MicPCBAssembly' or not gauge.BoundBox.intersect(obj.Shape.BoundBox):continue
        v=overlap_volume(gauge,obj.Shape)
        if v>1e-5:hits.append({'part':obj.Name,'mm3':v})
    wire_checks.append({'pad':pad['ref'],'net':pad['net'],'world_mm':list(point),'clearance_gauge_diameter_mm':1.2,'depth_mm':1.3,'collisions':hits})
    if hits:fail.append('Mic solder access '+pad['ref'])
report={'status':'FAIL' if fail else 'NOMINAL_ACOUSTIC_PATH_SEAL_CONTACT_AND_MAX_LRA_FIT_PASS',
 'native_file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
 'air_gauge':{'diameter_mm':1.3,'from_mm':[-13,107.5,-6],'to_mm':[-13,120.5,-6],'obstructions':obstructions},
 'native_mic_port_mm':list(native_port),'gasket_volume_mm3':gasket.Volume,'gasket_contact_distance_mm':contacts,
 'max_lra_body_mm':[10.1,3.85],'max_lra_collisions':lra_contacts,'adhesive_contact_distance_mm':adh_contacts,'mic_wire_solder_access':wire_checks,'failures':fail,
 'scope':'Rigid nominal geometry and manufacturer maximum LRA body only. Gasket compression/leak, adhesive grade/peel, sound transfer, vibration strength, lead fit and physical assembly remain untested.'}
(R/f'reports/audio-mechanics-design{opt.revision}.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
sys.exit(bool(fail))

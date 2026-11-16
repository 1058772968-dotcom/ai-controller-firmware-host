#!/usr/bin/env python3
"""Add removable edge clamps and captive M1.6 nuts to the saved palm shell."""
import sys,json,hashlib,argparse
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
from key_cartridge import hex_prism,box
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1];V=A.Vector
ap=argparse.ArgumentParser();ap.add_argument('--revision',default='08');opt=ap.parse_args()
source=R/'mechanical/AIKEY_REVA_DESIGN05.FCStd';d=A.openDocument(str(source))
base=d.PalmShell.Shape.copy();history=d.addObject('PartDesign::Feature','PalmShellBeforeMainMounts');history.Shape=base.copy();d.Construction.addObject(history)
if history.ViewObject:history.ViewObject.Visibility=False
mounts=[];new=[];cavities=[]
def feature(name,shape,status):
    if not shape.isValid() or len(shape.Solids)!=1:raise RuntimeError('Invalid mount '+name)
    o=d.addObject('PartDesign::Feature',name);o.Shape=shape;o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=status;d.Assembly.addObject(o);new.append(o)
    return o
for y in (60.,93.):
    for sign,side in ((-1,'L'),(1,'R')):
        x=sign*14.;label=side+str(int(y))
        # Only the outer 0.35 mm of PCB laminate rests on the ledge. Native
        # copper edge is at |X|=11.40 mm; ledge starts at |X|=11.65 mm.
        beam=Part.makeBox(16.35,4.,3.,V(11.65 if sign>0 else -28,y-2,-11.5)).common(d.OuterEnvelope.Shape)
        tower=Part.makeCylinder(2.1,1.,V(x,y,-8.5))
        # The circular screw pedestal must not intrude into the 24 mm PCB.
        # Ledges remain below the PCB; this upper pedestal has 0.15 mm edge gap.
        tower=tower.cut(Part.makeBox(24.3,140,2.,V(-12.15,0,-8.5)))
        hole=Part.makeCylinder(.90,8.,V(x,y,-12.))
        pocket=hex_prism(3.45,1.40,x,y,-11.51)
        support=beam.fuse(tower).cut(hole).cut(pocket)
        cavities.extend([hole,pocket,box(4.85,4.3,3.,x=sign*13.925,y=y,z=-7.5)])
        if not support.isValid():raise RuntimeError('Invalid support '+label)
        base=base.fuse(support,1e-7)
        clamp=box(4.55,4.,1.3,x=sign*13.925,y=y,z=-7.5).cut(hole)
        feature('MainClamp'+label,clamp,'Removable edge clamp; M1.6 x 5 screw; no mounting load on sensor body')
        nut=hex_prism(3.2,1.3,x,y,-11.5).cut(Part.makeCylinder(.85,2,V(x,y,-11.6)))
        feature('MainNut'+label,nut,'M1.6 hex nut, 3.2 AF x1.3, inserted from underside before PCB')
        screw=Part.makeCylinder(.8,5.,V(x,y,-11.2)).fuse(Part.makeCylinder(1.6,1.3,V(x,y,-6.2)))
        screw=screw.cut(box(.45,2.3,.5,x=x,y=y,z=-5.4).fuse(box(2.3,.45,.5,x=x,y=y,z=-5.4)))
        feature('MainScrew'+label,screw,'M1.6 x5 pan-head nominal fastener envelope')
        mounts.append({'name':label,'fastener_center_xy_mm':[x,y],'ledge_inner_abs_x_mm':11.65,'board_edge_abs_x_mm':12.,'board_bottom_z_mm':-8.5,'clamp_bottom_z_mm':-7.5})
        print('Created main mount',label,flush=True)
# Four corner-only end stops leave the centre of each board edge open for harnesses.
for y0 in (54.85,98.15):
    for sign in (-1,1):
        stop=Part.makeBox(16.35,1.,4.,V(11.65 if sign>0 else -28,y0,-11.5)).common(d.OuterEnvelope.Shape)
        base=base.fuse(stop,1e-7)
# The original curved shell can occupy the same space as the new nut. Cut
# every fastener cavity through the final union, including the original shell.
for cavity in cavities:base=base.cut(cavity)
if not base.isValid() or len(base.Solids)!=1:raise RuntimeError('Palm supports are disconnected or invalid')
d.PalmShell.Shape=base;d.PalmShell.DesignStatus='Main PCB ledges integrated; four removable edge clamps with captive M1.6 nuts. Full assembly check required.'
d.PalmShell.addProperty('App::PropertyLink','PreMountSource');d.PalmShell.PreMountSource=history
d.recompute()
checks=[]
for o in new+[d.PalmShell]:
    vol=overlap_volume(o.Shape,d.MainPCBAssembly.Shape)
    checks.append({'a':o.Name,'b':'MainPCBAssembly','overlap_mm3':vol});print(checks[-1],flush=True)
    if vol>1e-5:raise RuntimeError('Mount intersects PCB/components')
out=R/f'mechanical/AIKEY_REVA_DESIGN{opt.revision}.FCStd';d.saveAs(str(out));A.closeDocument(d.Name);d=A.openDocument(str(out))
invalid=[o.Name for o in d.Assembly.Group if not o.Shape.isValid()]
if invalid:raise RuntimeError('Reopened invalid assembly: '+str(invalid))
report={'status':'MAIN_MOUNT_LOCAL_PASS_FULL_DELTA_CHECK_PENDING','native_file':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'parts':len(d.Assembly.Group),'mounts':mounts,'end_stops':{'board_y_mm':[56.,98.],'stop_inner_y_mm':[55.85,98.15],'nominal_axial_clearance_mm':.15,'corner_contact_width_mm':.35},'pcb_interference':checks,
 'assembly':'Load four nuts from underside, place board on ledges with lower edge located, install four clamps and M1.6x5 screws from the open finger side. Do not clamp the IMU package.',
 'remaining':['full interference and key-motion delta check','printed fits and screw preload','other module retention and assembly paths']}
(R/f'reports/mechanical-design{opt.revision}-build.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)

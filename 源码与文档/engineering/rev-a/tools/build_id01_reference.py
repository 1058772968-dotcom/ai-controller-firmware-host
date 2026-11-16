#!/usr/bin/env python3
"""Native B-rep exterior reconstruction of the user's ID-01 six-view reference.

This intentionally starts a new exterior branch. It does not re-certify the
DESIGN18 hardware fit. Section curves and all visible parts remain native CAD.
"""
from pathlib import Path
import sys,math,json,hashlib,ast,os
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
R=Path(__file__).resolve().parents[1];P=R.parents[1];OUT=Path(os.environ.get('ID01_OUTPUT_DIR',str(R/'mechanical/id01-reference')));OUT.mkdir(exist_ok=True)
REVISION='AIKEY_ID01_REFERENCE_04'
CAP_DEPTH=58.0  # User chose visual proportions over the conflicting 46 mm annotation.
CAP_SLOPE=.25
V=A.Vector;d=A.newDocument('AIKEY_ID01_REFERENCE')
construction=d.addObject('App::DocumentObjectGroup','Construction')
assembly=d.addObject('App::DocumentObjectGroup','ExteriorAssembly')
palette={'shell':(.72,.71,.67),'cap':(.79,.78,.74),'key':(.19,.20,.20),'rubber':(.14,.15,.15),'strap':(.18,.19,.19),'gap':(.075,.08,.08),'metal':(.35,.37,.37),'gold':(.83,.55,.18),'led':(.17,.75,.89),'ink':(.90,.92,.91)}
source=P/'prototype/src/reference-product.js'
# Surface construction shares only pure math with the previous generator;
# new section dimensions and visible controls below follow the supplied image.
tree=ast.parse((R/'tools/build_mechanical.py').read_text())
defs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('section','smooth','bezier','capunit','surface')]
PROFILE=[[0,15.7,11.5,16.8],[.6,18,13,18.5],[2,20,15.5,20.5],[5,21,16.7,21.7],
 [17,21.3,16.2,22.3],[32,20.7,14.4,22.5],[48,19.6,13.8,21.3],
 [62,18.6,12.6,19.4],[74,17.9,7.8,17.5],[82,18.3,8.7,17.3],
 [90,20,13,18.5],[98,23.2,19.6,21.1],[103.7,24.5,22.8,22.8]]
ns={'PROFILE':PROFILE,'math':math,'V':V,'P':{'top_slope':-.2}}
exec(compile(ast.Module(body=defs,type_ignores=[]),'surface-functions','exec'),ns)
arcs=[[(7,-23),(18,-23),(26,-12),(26,0)],[(26,0),(26,12),(17,23),(2,23)],[(2,23),(-12,23),(-26,14),(-26,2)],[(-26,2),(-26,-8),(-7,-23),(7,-23)]]
ns['boundary']=[(-p[0],p[1]) for a in arcs for i in range(96) for p in [ns['bezier'](*a,i/96)]];ns['boundary'].append(ns['boundary'][0])
base_surface=ns['surface'];capunit=ns['capunit']
# The reference's side view has an aft-swept palm belly, not a straight bottle.
# The 46 mm arrow spans the cap. Overall grip depth is measured separately.
SIDE_SHIFT=[(0,-9.5),(5,-10),(17,-10.5),(32,-10.5),(48,-9.2),(62,-7.6),(74,-5.5),(82,-3.5),(90,-1.5),(98,-.4),(103.7,0)]
def side_shift(y):
    if y<=0:return SIDE_SHIFT[0][1]
    if y>=103.7:return 0
    i=next(i for i in range(len(SIDE_SHIFT)-1) if SIDE_SHIFT[i][0]<=y<=SIDE_SHIFT[i+1][0])
    a,b=SIDE_SHIFT[i:i+2];prev=SIDE_SHIFT[max(0,i-1)];nxt=SIDE_SHIFT[min(len(SIDE_SHIFT)-1,i+2)]
    span=b[0]-a[0];t=(y-a[0])/span;m0=(b[1]-prev[1])/(b[0]-prev[0]);m1=(nxt[1]-a[1])/(nxt[0]-a[0])
    return (2*t**3-3*t*t+1)*a[1]+(t**3-2*t*t+t)*span*m0+(-2*t**3+3*t*t)*b[1]+(t**3-t*t)*span*m1
def surface(y,angle,inset=0):
    rx,f,r=ns['section'](y);cz=(f-r)/2;rz=(f+r)/2
    x=(rx-inset)*math.cos(angle);z=cz+(rz-inset)*math.sin(angle)
    blend=ns['smooth'](89,103.7,y);u=capunit(angle)
    x=x*(1-blend)+(rx-inset)*u[0]*blend;z=z*(1-blend)+(cz+(rz-inset)*u[1])*blend
    return V(x,y-CAP_SLOPE*z*ns['smooth'](92,103.7,y),z+side_shift(y))
K=.5522847498307936
ellipse_arcs=[[(0,-1),(-K,-1),(-1,-K),(-1,0)],[(-1,0),(-1,K),(-K,1),(0,1)],[(0,1),(K,1),(1,K),(1,0)],[(1,0),(1,-K),(K,-1),(0,-1)]]
def section_wire(y,inset):
    rx,f,r=ns['section'](y);cz=(f-r)/2;rz=(f+r)/2;blend=ns['smooth'](89,103.7,y);slope=-CAP_SLOPE*ns['smooth'](92,103.7,y)
    edges=[];points=[]
    for ea,ca in zip(ellipse_arcs,arcs):
        poles=[]
        for (ex,ez),(cx,cz0) in zip(ea,ca):
            x=(rx-inset)*(ex*(1-blend)-cx/26*blend)
            z=cz+(rz-inset)*(ez*(1-blend)+cz0/23*blend)
            poles.append(V(x,y+slope*z,z+side_shift(y)))
        c=Part.BezierCurve();c.setPoles(poles);edges.append(c.toShape());points.extend(poles)
    return Part.Wire(edges),points
def feature(name,s,kind='shell',visible=True,note=''):
    if not s.isValid() or not s.Solids:raise RuntimeError('Invalid or nonsolid '+name)
    o=d.addObject('PartDesign::Feature',name);o.Shape=s
    o.addProperty('App::PropertyString','DesignStatus');o.DesignStatus=note or 'Image-derived exterior; internal mounting must be revalidated'
    o.addProperty('App::PropertyString','MaterialRole');o.MaterialRole=kind
    (assembly if visible else construction).addObject(o)
    if o.ViewObject:o.ViewObject.ShapeColor=palette[kind];o.ViewObject.Visibility=visible;o.ViewObject.DisplayMode='Flat Lines'
    print(name,len(s.Solids),round(s.Volume,4),flush=True);return o
def wire(points):
    c=Part.BSplineCurve();c.interpolate(points,PeriodicFlag=True);return Part.Wire(c.toShape())
def loft_profile(name,inset,ys):
    sections=[]
    for i,y in enumerate(ys):
        section,points=section_wire(y,inset)
        o=d.addObject('PartDesign::Feature',name+'Section%02d'%i);o.Shape=section
        o.addProperty('App::PropertyVectorList','ControlPoints');o.ControlPoints=points
        construction.addObject(o);sections.append(o)
    o=d.addObject('Part::Loft',name);o.Sections=sections;o.Solid=True;o.Ruled=False;o.MaxDegree=3
    construction.addObject(o);d.recompute()
    if not o.Shape.isValid():raise RuntimeError('Loft '+name)
    return o
def tube(points,r):
    closed=(points[0]-points[-1]).Length<1e-6
    c=Part.BSplineCurve();c.interpolate(points[:-1] if closed else points,PeriodicFlag=closed);edge=c.toShape();path=Part.Wire(edge)
    start=points[0];t=c.tangent(c.FirstParameter)[0]
    circle=Part.Wire(Part.makeCircle(r,start,t));return path.makePipeShell([circle],True,False)
def rounded(w,h,t,r):
    s=Part.makeBox(w-2*r,h,t,V(-w/2+r,-h/2,0)).fuse(Part.makeBox(w,h-2*r,t,V(-w/2,-h/2+r,0)))
    for x in (-w/2+r,w/2-r):
        for y in (-h/2+r,h/2-r):s=s.fuse(Part.makeCylinder(r,t,V(x,y,0)))
    return s.removeSplitter()
def positioned(s,origin,normal,roll=0):
    q=s.copy();rot=A.Rotation(V(0,0,1),normal).multiply(A.Rotation(V(0,0,1),roll))
    q.Placement=A.Placement(origin,rot).multiply(q.Placement);return q
ys=sorted(set([v[0] for v in PROFILE]+[(a[0]+b[0])/2 for a,b in zip(PROFILE[3:],PROFILE[4:])]))
outer=loft_profile('OuterSkin',0,ys)
inner=loft_profile('InnerSkin',2,[y for y in ys if y>=2.0])
body=outer.Shape.cut(inner.Shape)
def bodycheck(label):print('BODY',label,[(round(s.Volume,8),list(s.CenterOfMass)) for s in body.Solids],flush=True)
bodycheck('hollow')
# A native wraparound soft-touch insert, interpolated as two smooth surfaces
# and four ruled perimeter faces. No triangle-to-B-rep conversion is used.
def inlay(center,start,end,maxangle):
    def patch(offset):
        pts=[]
        for j in range(19):
            t=j/18;y=start+(end-start)*t
            half=.30+maxangle*math.sin(math.pi*t)**.4
            pts.append([surface(y+2*(i/24*2-1)**2*(1-2*t)*abs(math.cos(math.pi*t))**8,center+(i/24*2-1)*half,-offset) for i in range(25)])
        s=Part.BSplineSurface();s.interpolate(pts);return s.toShape()
    front=patch(.40);back=patch(-.60)
    sides=[Part.makeRuledSurface(a,b) for a,b in zip(front.Edges,back.Edges)]
    s=Part.makeSolid(Part.makeShell([front,back]+sides))
    if s.Volume<0:s.reverse()
    if not s.isValid():raise RuntimeError('Grip insert surface shell')
    return s
grips=[]
for name,center,start,end,half in [('PalmGrip',-math.pi/2,12,78,1.60)]:
    grip=inlay(center,start,end,half);body=body.cut(grip);feature(name,grip,'rubber');grips.append(name)
bodycheck('grips')
# Delete only detached sub-mm3 milling remnants at the curved pocket edges;
# keep the operation and measured removed volume explicit, never hide a shell.
slivers=[]
if len(body.Solids)>1:
    ordered=sorted(body.Solids,key=lambda s:s.Volume,reverse=True)
    slivers=[{'volume_mm3':s.Volume,'centre_mm':list(s.CenterOfMass)} for s in ordered[1:]]
    if sum(s['volume_mm3'] for s in slivers)>2.0:raise RuntimeError('Grip pocket fragmented the housing')
    feature('GripPocketBeforeEdgeCleanup',body,'shell',False)
    body=ordered[0]
# The index trigger hangs beneath the cap, with an actual recess behind it.
# Front silhouette: broad upper edge and a rounded U-shaped lower edge.
def trigger(expand=0,front_offset=0):
    rows=[(82.8,4.5,12.6,10.1),(84,8,15.0,8.0),(87,10.7,17.4,5.0),
          (93,12,19.7,3.0),(98.5,12.6,21.6,4.0),(102,12.6,22.6,7.0)]
    ws=[]
    for y,rx,f,b in rows:
        cz=(f+b)/2+front_offset;rz=(f-b)/2+expand
        pts=[V((rx+expand)*math.copysign(abs(math.cos(t))**.72,math.cos(t)),y,cz+rz*math.sin(t)) for t in [2*math.pi*i/48 for i in range(48)]]
        ws.append(wire(pts))
    return Part.makeLoft(ws,True,False,False,3)
def below_sloped_plane(y0):
    p=[V(-50,-20,-50),V(-50,y0+CAP_SLOPE*50,-50),V(-50,y0-CAP_SLOPE*50,50),V(-50,-20,50)]
    return Part.Face(Part.makePolygon(p+[p[0]])).extrude(V(100,0,0))
trigger_body=trigger().common(below_sloped_plane(103.4));trigger_socket=trigger(.65,-.2).common(below_sloped_plane(103.5))
body=body.cut(trigger_socket)
bodycheck('trigger')
feature('TriggerSocketConstruction',trigger_socket,'gap',False)
feature('VoiceTrigger',trigger_body,'key')
# Slim gold-ringed drawing key goes back to the LEFT SIDE, per the image.
y=44.;angle=math.pi*.82;pt=surface(y,angle)
ta=surface(y,angle+.002)-surface(y,angle-.002);ty=surface(y+.01,angle)-surface(y-.01,angle)
normal=ty.cross(ta);normal.normalize()
key_origin=pt+normal*.35
cutout=positioned(rounded(10.2,23.0,6,4.8),pt-normal*4,normal)
body=body.cut(cutout)
for name in grips:d.getObject(name).Shape=d.getObject(name).Shape.cut(cutout)
bodycheck('side key')
gold=rounded(9.9,22.4,.8,4.7).cut(rounded(8.5,21,1.2,4.0))
feature('DrawingKeyGoldBezel',positioned(gold,key_origin,normal),'gold')
key=rounded(8.2,20.7,1.1,3.95)
try:key=key.makeFillet(.35,[e for e in key.Edges if e.BoundBox.ZLength<1e-5])
except Part.OCCError:pass
feature('DrawingKey',positioned(key,key_origin+normal*.1,normal),'key')
# Top cover: continuously rounded side wall and sloping deck, no stacked
# horizontal ridges. Contours preserve the asymmetric egg of the reference.
def capwire(y,rx,rz):
    edges=[]
    for arc in arcs:
        c=Part.BezierCurve();c.setPoles([V(-rx*x/26,y-CAP_SLOPE*rz*z/23,rz*z/23) for x,z in arc]);edges.append(c.toShape())
    return Part.Wire(edges)
cap=Part.makeLoft([capwire(*p) for p in [(103.7,24.5,22.8),(104.4,25.55,23),(106.2,26,23),(108.0,25.85,22.85),(109.3,25.15,22.2),(109.8,24.5,21.7)]],True,False,False,3)
capinner=Part.makeLoft([capwire(*p) for p in [(103.4,22.5,20.7),(107.8,22.5,19.7)]],True,False,False,3)
cap=cap.cut(capinner)
topnormal=V(0,1,CAP_SLOPE);topnormal.normalize()
# Organic key outline from native Bezier geometry, normalized to true sizes.
thumbs={
 'L':[[(-.27,.49),(-.04,.56),(.37,.40),(.47,.17)],[(.47,.17),(.56,-.06),(.37,-.43),(.10,-.49)],[(.10,-.49),(-.17,-.55),(-.46,-.32),(-.49,-.07)],[(-.49,-.07),(-.54,.18),(-.46,.40),(-.27,.49)]],
 'R':[[(-.25,.50),(.03,.48),(.47,.17),(.49,-.07)],[(.49,-.07),(.50,-.30),(.15,-.49),(-.10,-.49)],[(-.10,-.49),(-.34,-.50),(-.51,-.23),(-.49,.02)],[(-.49,.02),(-.47,.24),(-.43,.49),(-.25,.50)]]}
def thumbwire(n,w,h,z,scale=1):
    pts=[]
    for i in range(80):
        a=2*math.pi*i/80;x=.5*w*math.copysign(abs(math.cos(a))**.55,math.cos(a));y=.5*h*math.copysign(abs(math.sin(a))**.55,math.sin(a))
        pts.append(V((x+.07*y)*scale,y*scale,z))
    return wire(pts)
for name,w,h,x,z in [('L',24,19,8.5,8),('R',20,17,-8.5,-10)]:
    origin=V(x,109.8-CAP_SLOPE*z,z)
    rotation=-8 if name=='L' else -5
    key=Part.Face(thumbwire(name,w,h,-.3)).extrude(V(0,0,2.5))
    top_edges=[e for e in key.Edges if e.BoundBox.ZMin>2.19]
    key=key.makeFillet(.65,top_edges)
    aperture=Part.Face(thumbwire(name,w+.55,h+.55,-3)).extrude(V(0,0,5))
    cap=cap.cut(positioned(aperture,origin,topnormal,rotation))
    feature('Thumb'+name,positioned(key,origin,topnormal,rotation),'key')
    rim=Part.Face(thumbwire(name,w+.9,h+.9,-.25)).extrude(V(0,0,.5)).cut(Part.Face(thumbwire(name,w+.12,h+.12,-.3)).extrude(V(0,0,.8)))
    feature('Thumb'+name+'Seal',positioned(rim,origin,topnormal,rotation),'gap')
    # Geometric white legends remain present in the saved STEP and FCStd.
    if name=='L':
        glyph=Part.makeBox(.36,3.6,.05,V(-1.2,-1.8,2.20)).fuse(Part.makeBox(2.3,.36,.05,V(-1.2,-1.8,2.20)))
    else:
        outside=[(-1.1,-1.8),(-1.1,1.8),(.2,1.8),(1.1,1.4),(1.25,.8),(1.1,.2),(.55,-.1),(1.45,-1.8),(.95,-1.8),(.1,-.25),(-.7,-.25),(-.7,-1.8)]
        inside=[(-.7,.15),(.15,.15),(.75,.4),(.85,.8),(.75,1.2),(.15,1.4),(-.7,1.4)]
        def glyph_face(poly):
            pp=[V(x,y,2.2) for x,y in poly];return Part.Face(Part.makePolygon(pp+[pp[0]]))
        glyph=glyph_face(outside).cut(glyph_face(inside)).extrude(V(0,0,.05))
    feature('Legend'+name,positioned(glyph,origin,topnormal,rotation),'ink')
    if name=='L':feature('TactileDot',positioned(Part.makeCylinder(.45,.12,V(6,-2,2.2)),origin,topnormal,rotation),'ink')
# Cyan slit follows the front edge of the top deck.
led=positioned(rounded(11.6,1.05,1.4,.48),V(0,103.0,21.75),V(0,0,1))
cap=cap.cut(led);feature('StatusLightWindow',led,'led')
feature('TopCover',cap,'cap')
# Bottom apertures are cut in the actual housing, with a separate rim/tongue.
down=V(0,-1,0)
for name,x,z,w,h in [('USB',0,1+side_shift(0),8.5,2.8),('Lanyard',0,-10.5+side_shift(0),6.7,3)]:
    tool=positioned(rounded(w,h,5,min(h/2-.05,1.3)),V(x,2,z),down)
    body=body.cut(tool)
    rim=rounded(w+1.4,h+1.4,.25,min(h/2+.6,1.9)).cut(rounded(w,h,.4,min(h/2-.05,1.3)))
    feature(name+'Rim',positioned(rim,V(x,.25,z),down),'metal')
    feature(name+'Cavity',positioned(rounded(w-.3,h-.3,.05,min((h-.3)/2-.05,1.1)),V(x,1.3,z),down),'gap')
feature('USBTongue',positioned(rounded(5.8,.6,.2,.24),V(0,.5,1+side_shift(0)),down),'metal')
feature('MainHousing',body,'shell')
# Reference hand strap and detachable round end anchors, all native lofts.
centres=[(20.0,90,-8.4),(22.5,83,-8.0),(23.8,64,-7.1),(24.0,43,-7.3),(23.0,26,-8.1),(21.0,14,-9.6)]
ws=[]
for i,(x,y,z) in enumerate(centres):
    z+=side_shift(y)
    prev=V(*centres[max(0,i-1)]);nxt=V(*centres[min(len(centres)-1,i+1)]);t=nxt-prev
    normal=V(-t.y,t.x,0);normal.normalize()
    width_axis=V(-.45,0,.893);width_axis.normalize()
    thick_axis=normal+V(0,0,.45);thick_axis.normalize()
    pts=[V(x,y,z)+thick_axis*(1.1*math.copysign(abs(math.cos(a))**.65,math.cos(a)))+width_axis*(5.2*math.copysign(abs(math.sin(a))**.65,math.sin(a))) for a in [2*math.pi*j/32 for j in range(32)]]
    ws.append(wire(pts))
feature('HandStrap',Part.makeLoft(ws,True,False,False,3),'strap')
for name,x,y,z in [('Upper',20,90,-8.4),('Lower',21,14,-9.6)]:
    z+=side_shift(y)
    n=V(.963,0,-.27);n.normalize();p=V(x,y,z)
    feature('Strap'+name+'Base',Part.makeCylinder(5.4,1.0,p,n),'gap')
    feature('Strap'+name+'Ring',Part.makeCylinder(4.4,.8,p+n*.95,n).cut(Part.makeCylinder(3.65,1,p+n*.9,n)),'metal')
    feature('Strap'+name+'Button',Part.makeCylinder(3.55,.7,p+n*1.0,n),'key')
# Rear mould seam and low foot joint: thin native curves, never tessellation edges.
feature('RearPartingLine',tube([surface(y,-math.pi/2,-.46) for y in range(5,103,2)],.065),'gap')
feature('FootPartingLine',tube([surface(3.4,a,-.02) for a in [2*math.pi*i/96 for i in range(97)]],.055),'metal')
# White microphone mark on the hanging trigger.
micorigin=V(0,92.5,20.0)
feature('MicSymbolCapsule',positioned(rounded(1.3,3.2,.07,.6),micorigin,V(0,0,1)),'ink')
feature('MicSymbolArc',tube([micorigin+V(2*math.cos(a),-.2+2*math.sin(a),0) for a in [math.pi+math.pi*i/20 for i in range(21)]],.14),'ink')
feature('MicSymbolStem',positioned(rounded(.25,1.1,.08,.1),micorigin+V(0,-2.6,0),V(0,0,1)),'ink')
feature('MicSymbolBase',positioned(rounded(2.4,.25,.08,.1),micorigin+V(0,-3.1,0),V(0,0,1)),'ink')
# Visual proportions take priority, as explicitly selected by the user.
# Height and cap width remain 116 and 52 mm. Cap depth is now 58 mm, derived
# from image proportions; all measured dimensions are reported separately.
cb=d.TopCover.Shape.optimalBoundingBox(False,False)
bb=Part.makeCompound([o.Shape for o in assembly.Group if not o.Name.startswith('Strap') and o.Name!='HandStrap']).optimalBoundingBox(False,False)
calibration={'x':52/cb.XLength,'y':116/bb.YLength,'z':CAP_DEPTH/cb.ZLength,'height_base_y_mm':bb.YMin}
matrix=A.Matrix();matrix.A11=calibration['x'];matrix.A22=calibration['y'];matrix.A33=calibration['z'];matrix.A24=-bb.YMin*calibration['y']
for o in assembly.Group:
    o.Shape=o.Shape.transformGeometry(matrix)
    if not o.Shape.isValid():raise RuntimeError('Invalid calibrated exterior '+o.Name)
params=d.addObject('Spreadsheet::Sheet','ExteriorParameters');construction.addObject(params)
for row,(k,v) in enumerate([('Reference','User ID-01 six-view image'),('Dimension interpretation','User selected visual proportions; 116 mm height, 52 x 58 mm cap; overall depth separately measured'),('Top width',52),('Top depth',CAP_DEPTH),('Reference annotation conflict','46 mm label superseded by user visual-priority decision'),('Trigger layout','hanging under front cap'),('Side key layout','left side, gold bezel'),('Hardware validation','Pending remapping to this new exterior')],1):params.set('A'+str(row),str(k));params.set('B'+str(row),str(v))
for o in construction.Group:
    if o.ViewObject:o.ViewObject.Visibility=False
d.recompute();path=OUT/(REVISION+'.FCStd');d.saveAs(str(path));A.closeDocument(d.Name)
d=A.openDocument(str(path));rows=[];meshes=[]
for o in d.ExteriorAssembly.Group:
    s=o.Shape;b=s.optimalBoundingBox(False,False);rows.append({'name':o.Name,'valid':s.isValid(),'solids':len(s.Solids),'volume_mm3':s.Volume,'bounds_xyz_mm':[b.XMin,b.XMax,b.YMin,b.YMax,b.ZMin,b.ZMax]})
    import MeshPart
    mesh=MeshPart.meshFromShape(Shape=s,LinearDeflection=.10,AngularDeflection=.3,Relative=False)
    vertices,faces=mesh.Topology
    meshes.append({'name':o.Name,'role':o.MaterialRole,'color':palette[o.MaterialRole],'vertices':[[round(v.x,5),round(v.y,5),round(v.z,5)] for v in vertices],'faces':faces})
(OUT/'native-meshes.json').write_text(json.dumps(meshes,separators=(',',':')))
step=OUT/(REVISION+'.step');Part.export(d.ExteriorAssembly.Group,str(step))
report={'status':'NATIVE_EXTERIOR_SAVED_REOPENED_VALID_SOLIDS' if all(p['valid'] for p in rows) and len(d.MainHousing.Shape.Solids)==1 else 'FAIL','native_file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_image_sha256':hashlib.sha256((OUT/'user-reference.png').read_bytes()).hexdigest(),'profile':PROFILE,'rearward_side_shift_mm':SIDE_SHIFT,'dimension_calibration':calibration,'grip_edge_slivers_removed':slivers,'parts':rows,'scope':'Exterior visual reconstruction only; no claim of image-exact unseen surfaces, complete internal fit, mechanism travel or manufacturing release. The user reference supersedes the previous C exterior layout; firmware/electronics are retained for remapping.'}
(OUT/'native-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(report['status'],flush=True)

"""Split-guide key cartridge; all dimensions mm, local +Z is outward.

The two guide halves assemble laterally around the captive flange, then clamp
to the fixed PCB carrier with two M1.6 x 4 screws and captured hex nuts.
Switch actuator compression is a functional interface, not a rigid collision.
"""
import math
import FreeCAD as A
import Part
V=A.Vector

def box(w,h,t,x=0,y=0,z=0):
    return Part.makeBox(w,h,t,V(x-w/2,y-h/2,z))

def rounded(w,h,t,r,z=0):
    r=min(r,w/2-.01,h/2-.01)
    shape=box(w-2*r,h,t,z=z).fuse(box(w,h-2*r,t,z=z))
    for x in (-w/2+r,w/2-r):
        for y in (-h/2+r,h/2-r):
            shape=shape.fuse(Part.makeCylinder(r,t,V(x,y,z)))
    return shape.removeSplitter()

def hex_prism(af,t,x,y,z):
    radius=af/math.sqrt(3)
    pts=[V(x+radius*math.cos(math.pi/6+k*math.pi/3),y+radius*math.sin(math.pi/6+k*math.pi/3),z) for k in range(6)]
    return Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(V(0,0,t))

def thumb(id,w,h,t,z):
    # Same four cubic Bezier curves as reference-product.js thumbContour.
    curves=(
      [[(-.27,.49),(-.04,.56),(.37,.40),(.47,.17)],[(.47,.17),(.56,-.06),(.37,-.43),(.10,-.49)],[(.10,-.49),(-.17,-.55),(-.46,-.32),(-.49,-.07)],[(-.49,-.07),(-.54,.18),(-.46,.40),(-.27,.49)]]
      if id=='Left' else
      [[(-.25,.50),(.03,.48),(.47,.17),(.49,-.07)],[(.49,-.07),(.50,-.30),(.15,-.49),(-.10,-.49)],[(-.10,-.49),(-.34,-.50),(-.51,-.23),(-.49,.02)],[(-.49,.02),(-.47,.24),(-.43,.49),(-.25,.50)]])
    edges=[]
    for arc in curves:
        curve=Part.BezierCurve();curve.setPoles([V(x,y,0) for x,y in arc]);edges.append(curve.toShape())
    wire=Part.Wire(edges);b=wire.BoundBox
    matrix=A.Matrix();matrix.A11=w/b.XLength;matrix.A22=h/b.YLength
    matrix.A14=-(b.XMin+b.XMax)/2*matrix.A11
    matrix.A24=-(b.YMin+b.YMax)/2*matrix.A22;matrix.A34=z
    wire=wire.transformGeometry(matrix)
    return Part.Face(wire).extrude(V(0,0,t))

def key_sweep(name,width,height,travel=0):
    cap=thumb(name,width,height,2.1+travel,-.9-travel) if name in ('Left','Right') else rounded(width,height,.9+travel,2.2,-.9-travel)
    stem=box(3,3,2.9+travel,z=-3.8-travel)
    flange=rounded(6.8,6.8,.3+travel,1,-4.1-travel)
    nib=Part.makeCylinder(.8,.3+travel,V(0,0,-4.4-travel))
    return cap.fuse(stem).fuse(flange).fuse(nib).removeSplitter()

def cartridge(name,width,height,board_file):
    key=key_sweep(name,width,height)
    guide=rounded(8.5,8.5,2.35,1,-3.8).cut(box(3.2,3.2,4,z=-4))
    carrier=rounded(17.6,10.4,1.6,1,-8.65)
    # Solder joints and wire bend space: actual backside pads x=+/-1.4,y=-3.2.
    carrier=carrier.cut(box(7,3.4,2,y=-3.2,z=-8.7))
    # The PCB rests on a rigid flat base; guide halves retain its top edges.
    for x in (-6.5,6.5):
        lug=box(4.6,7,2.5,x=x,z=-6.1)
        lug=lug.cut(box(9.3,9.3,1.2,z=-7.1))
        guide=guide.fuse(lug)
        tower=box(4.6,7,2.55,x=x,z=-8.65)
        tower=tower.cut(box(9.3,11,5,z=-8.7))
        carrier=carrier.fuse(tower)
        hole=Part.makeCylinder(.9,10,V(x,0,-10))
        guide=guide.cut(hole).cut(hex_prism(3.35,1.45,x,0,-6.15))
        carrier=carrier.cut(hole)
        carrier=carrier.cut(Part.makeCylinder(1.7,.35,V(x,0,-8.65)))
    # Lips leave 0.05 mm above the full nominal PCB thickness; copper/mask
    # omitted by STEP must not be mistaken for usable mechanical clearance.
    for x in (-4.15,4.15):
        lip=box(.65,2,.9,x=x,y=2.5,z=-5.90)
        guide=guide.fuse(lip)
    # Sloping outside shoulders clear the curved finger-shell inner wall.
    for sign in (-1,1):
        pts=[V(sign*x,-10,z) for x,z in [(6.3,-3.6),(9.2,-4.82),(9.2,2),(6.3,2)]]
        wedge=Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(V(0,20,0))
        guide=guide.cut(wedge)
    guide=guide.removeSplitter();carrier=carrier.removeSplitter()
    left=guide.common(box(30,30,20,x=-15,z=-10)).removeSplitter()
    right=guide.common(box(30,30,20,x=15,z=-10)).removeSplitter()
    board=Part.Shape();board.read(str(board_file));board.translate(V(-4.5,4.5,-6.75))
    shim=box(9,9,.3,z=-7.05).cut(box(7,3.4,1,y=-3.2,z=-7.2))
    shapes={'Key':key,'GuideL':left,'GuideR':right,'Carrier':carrier,'PCBAssembly':board,'Shim':shim}
    for side,x in [('L',-6.5),('R',6.5)]:
        nut=hex_prism(3.2,1.3,x,0,-6.1).cut(Part.makeCylinder(.85,2,V(x,0,-6.2)))
        screw=Part.makeCylinder(.8,4,V(x,0,-8.3)).fuse(Part.makeCylinder(1.6,1.3,V(x,0,-9.6)))
        screw=screw.cut(box(.45,2.3,.5,x=x,z=-9.6).fuse(box(2.3,.45,.5,x=x,z=-9.6)))
        shapes['Nut'+side]=nut;shapes['Screw'+side]=screw
    for name,shape in shapes.items():
        assert shape.isValid(),name
        if name!='PCBAssembly':assert len(shape.Solids)==1,(name,len(shape.Solids))
    return shapes

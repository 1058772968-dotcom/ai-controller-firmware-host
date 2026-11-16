"""Single-miter PMMA light guide; local s is the outgoing optical axis."""
import math
import FreeCAD as A,Part
V=A.Vector
B=V(0,96.2,-12)
U=V(-4,19.8,0);U.normalize()
W=V(U.y,-U.x,0)
def point(s,z,w=0):return B+U*s+V(0,0,z)+W*w
def elbow(radius,length=24,height=2.6):
    # The diagonal from (-r,+r) to (+r,-r) is the 45-degree optical face.
    coords=[(-radius,height),(radius,height),(radius,radius),
            (length,radius),(length,-radius),(radius,-radius),(-radius,radius)]
    points=[point(s,z,-radius) for s,z in coords]
    return Part.Face(Part.makePolygon(points+[points[0]])).extrude(W*(2*radius))
def limit(recess=0):
    # Nominal sloping top plane y+0.2*z=109.8, source top profile.
    yy=109.8-recess
    p=[V(-50,-20,-50),V(-50,yy+10,-50),V(-50,yy-10,50),V(-50,-20,50)]
    return Part.Face(Part.makePolygon(p+[p[0]])).extrude(V(100,0,0))
def side_pad(sign):
    pts=[point(s,z,sign*1.1) for s,z in [(11,-1.1),(14,-1.1),(14,1.1),(11,1.1)]]
    return Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(W*(sign*.15))
def shapes():
    guide=elbow(1.1).common(limit(.15))
    cavity=elbow(1.25,height=3.0)
    shield=elbow(2.25,height=2.6).cut(cavity).common(limit(.3))
    return guide,cavity,shield,[side_pad(s) for s in (-1,1)]

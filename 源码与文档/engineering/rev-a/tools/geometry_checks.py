"""Exact B-rep overlap with a distance/containment broad phase.

Positive boundary distance alone does not rule out full containment. Checking
one boundary point from both connected solids handles that case before skipping
the expensive boolean. No part or net is exempted from collision checks.
"""
def overlap_volume(a,b):
    total=0.0
    for sa in a.Solids:
        for sb in b.Solids:
            if not sa.BoundBox.intersect(sb.BoundBox):continue
            # Whole-shape extrema on trimmed B-spline shell unions can take
            # minutes per pair. The exact Boolean itself needs no distance
            # pre-pass. Retain the fast pre-pass only for simple geometry.
            simple=len(sa.Faces)+len(sb.Faces)<80 and not any(type(f.Surface).__name__=='BSplineSurface' for f in list(sa.Faces)+list(sb.Faces))
            if simple and sa.distToShape(sb)[0]>1e-6:
                if not sa.isInside(sb.Vertexes[0].Point,1e-7,True) and not sb.isInside(sa.Vertexes[0].Point,1e-7,True):
                    continue
            intersection=sa.common(sb)
            if not intersection.isNull() and not intersection.isValid():
                raise RuntimeError('Invalid exact intersection; no collision clearance may be claimed')
            total+=intersection.Volume
    return total

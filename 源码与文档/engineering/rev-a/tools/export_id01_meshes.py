"""Render the saved CAD with its analytic surface normals, preserving creases."""
from pathlib import Path
import sys,json,hashlib,math,time,os
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part,MeshPart
R=Path(__file__).resolve().parents[1];D=Path(os.environ.get('ID01_OUTPUT_DIR',str(R/'mechanical/id01-reference')));path=D/'AIKEY_ID01_REFERENCE_04.FCStd'
d=A.openDocument(str(path));items=[];rows=[];start=time.monotonic()
cache=D/'mesh-cache';cache.mkdir(exist_ok=True)
for o in d.ExteriorAssembly.Group:
    fingerprint=hashlib.sha256(o.Shape.exportBrepToString().encode()).hexdigest()
    cached=cache/(o.Name+'-'+fingerprint[:16]+'.json')
    if cached.exists():
        item=json.loads(cached.read_text());items.append(item);rows.append({'part':o.Name,'vertices':len(item['vertices']),'triangles':len(item['faces']),'cached_identical_brep':True});print(rows[-1],flush=True);continue
    if 'PartingLine' in o.Name or o.Name=='MicSymbolArc':
        mesh=MeshPart.meshFromShape(Shape=o.Shape,LinearDeflection=.10,AngularDeflection=.30,Relative=False)
        vs,fs=mesh.Topology
        item={'name':o.Name,'role':o.MaterialRole,'vertices':[[round(v.x,5),round(v.y,5),round(v.z,5)] for v in vs],'faces':fs}
        items.append(item);cached.write_text(json.dumps(item,separators=(',',':')));rows.append({'part':o.Name,'vertices':len(vs),'triangles':len(fs),'normals':'averaged only for subpixel seam/ink tubes'});print(rows[-1],flush=True);continue
    vertices=[];normals=[];indices=[];flips=0
    for face in o.Shape.Faces:
        mesh=MeshPart.meshFromShape(Shape=face,LinearDeflection=.06,AngularDeflection=.20,Relative=False)
        vs,fs=mesh.Topology;offset=len(vertices);ns=[]
        for p in vs:
            uv=face.Surface.parameter(p);n=face.normalAt(*uv);n.normalize();ns.append(n)
            vertices.append([round(p.x,5),round(p.y,5),round(p.z,5)]);normals.append([round(n.x,6),round(n.y,6),round(n.z,6)])
        for aa,bb,cc in fs:
            cross=(vs[bb]-vs[aa]).cross(vs[cc]-vs[aa])
            if cross.dot(ns[aa]+ns[bb]+ns[cc])<0:bb,cc=cc,bb;flips+=1
            indices.append([offset+aa,offset+bb,offset+cc])
    row={'part':o.Name,'vertices':len(vertices),'triangles':len(indices),'winding_fixed':flips};rows.append(row);print(row,flush=True)
    item={'name':o.Name,'role':o.MaterialRole,'vertices':vertices,'normals':normals,'faces':indices};items.append(item);cached.write_text(json.dumps(item,separators=(',',':')))
(D/'native-meshes.json').write_text(json.dumps(items,separators=(',',':')))
(D/'mesh-export-validation.json').write_text(json.dumps({'status':'NATIVE_ANALYTIC_SURFACE_NORMALS_EXPORTED','source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'linear_deflection_mm':.06,'angular_deflection_rad':.2,'parts':rows,'elapsed_s':time.monotonic()-start},indent=2)+'\n')

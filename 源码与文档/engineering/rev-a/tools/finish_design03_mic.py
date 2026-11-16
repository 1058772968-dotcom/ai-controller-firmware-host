#!/usr/bin/env python3
"""Incremental native check: translate mic after a complete static check.

Reopen and compare exact B-rep serialization of every unchanged part; reuse
their pair results only when their saved geometry is byte-identical.
"""
import sys,json,hashlib,shutil
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A
from geometry_checks import overlap_volume
R=Path(__file__).resolve().parents[1]
path=R/'mechanical/AIKEY_REVA_DESIGN03.FCStd';rp=R/'reports/mechanical-design03.json'
report=json.loads(rp.read_text())
assert report['status']=='FAIL' and all('MicPCBAssembly' in [c['a'],c['b']] for c in report['collisions'])
prior_sha=hashlib.sha256(path.read_bytes()).hexdigest()
shutil.copy2(rp,R/'reports/history/design03-mic-before.json')
d=A.openDocument(str(path))
assert 'y=107.5' not in d.MicPCBAssembly.DesignStatus,'Already moved; use full assembly validation, do not apply translation twice'
digest=lambda o:hashlib.sha256(o.Shape.exportBrepToString().encode()).hexdigest()
before={o.Name:digest(o) for o in d.Assembly.Group if o.Name!='MicPCBAssembly'}
mic=d.MicPCBAssembly;s=mic.Shape.copy();s.translate(A.Vector(0,1.5,0));mic.Shape=s
mic.DesignStatus='Actual KiCad STEP; acoustic port x=-13,y=107.5,z=-6; inward-facing PDM; seal pending'
d.recompute();d.save();A.closeDocument(d.Name);d=A.openDocument(str(path))
assert before=={o.Name:digest(o) for o in d.Assembly.Group if o.Name!='MicPCBAssembly'}
hits=[];checks=[]
for other in d.Assembly.Group:
    if other.Name=='MicPCBAssembly':continue
    vol=overlap_volume(d.MicPCBAssembly.Shape,other.Shape)
    checks.append({'other':other.Name,'overlap_mm3':vol})
    if vol>1e-5:hits.append({'a':'MicPCBAssembly','b':other.Name,'overlap_mm3':vol})
report['collisions']=hits
report['status']='FAIL' if hits else 'NOMINAL_STATIC_PASS_MOUNTS_PENDING'
report['incremental_validation']={'prior_native_sha256':prior_sha,'unchanged_part_brep_sha256':before,'mic_translation_mm':[0,1.5,0],
    'mic_pair_checks':checks,'readback':'Every unchanged saved B-rep matched byte-for-byte after reopen'}
report['native_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
rp.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'collisions':hits}),flush=True)
assert not hits

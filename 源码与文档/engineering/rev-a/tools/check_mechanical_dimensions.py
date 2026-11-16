#!/usr/bin/env python3
"""Independent saved-native measurements and placed ECAD fiducials."""
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
R=Path(__file__).resolve().parents[1];path=R/'mechanical/AIKEY_REVA_DESIGN04.FCStd';d=A.openDocument(str(path))
records={}
for name in ['PalmShell','FingerShellSupported','TopCoverSupported','VoiceKey','SideKey','LeftKey','RightKey','MainPCBAssembly','USBPCBAssembly','MicPCBAssembly','AntennaFPC','BatteryPack']:
 obj=d.getObject(name);b=obj.Shape.optimalBoundingBox()
 records[name]={'valid':obj.Shape.isValid(),'bbox_min_mm':[b.XMin,b.YMin,b.ZMin],'bbox_max_mm':[b.XMax,b.YMax,b.ZMax],
                'bbox_size_mm':[b.XLength,b.YLength,b.ZLength],'solids':len(obj.Shape.Solids)}
 if 'LocalKeyFrame' in obj.PropertiesList:records[name]['local_frame']=json.loads(obj.LocalKeyFrame)
 print(name,records[name]['bbox_size_mm'],flush=True)
body=Part.makeCompound([d.getObject(n).Shape for n in ['PalmShell','FingerShellSupported','TopCoverSupported']]).optimalBoundingBox()
envelope=[body.XLength,body.YLength,body.ZLength];target=[52,116,46]
report={'native_file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'records':records,
 'shell_envelope_xyz_mm':envelope,'reference_nominal_xyz_mm':target,'measured_minus_reference_mm':[a-b for a,b in zip(envelope,target)],
 'rear_key_centers_y_mm':{n:records[n+'Key']['local_frame']['origin_mm'][1] for n in ['Voice','Side']},
 'scope':'Saved native B-rep dimensions; shell-only envelope excludes moving key caps. Printed tolerance and component supplier variation are not proven.'}
report['rear_key_centers_pass']=report['rear_key_centers_y_mm']=={'Voice':90,'Side':40}
(R/'reports/mechanical-design04-dimensions.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='records'}),flush=True)

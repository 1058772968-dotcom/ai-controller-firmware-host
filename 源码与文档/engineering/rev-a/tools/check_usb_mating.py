#!/usr/bin/env python3
"""Independent case obstruction check using the GCT USB4105 mating drawing."""
import sys, json, hashlib, argparse
from pathlib import Path
sys.path.insert(0, '/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A, Part
from geometry_checks import overlap_volume

R = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser(); ap.add_argument('--revision', default='05'); args = ap.parse_args()
path = R / f'mechanical/AIKEY_REVA_DESIGN{args.revision}.FCStd'
d = A.openDocument(str(path)); usb = d.USBPCBAssembly.Shape
# Read the two stamped connector shell halves from the saved native exchange.
shells = [s for s in usb.Solids if 19 < s.Volume < 21 and s.BoundBox.ZLength > 4]
if len(shells) != 2: raise RuntimeError('USB shell identification changed; review model')
face_y = min(s.BoundBox.YMin for s in shells)
mount_z = max(s.BoundBox.ZMax for s in shells) - 3.31
center_z = mount_z + 1.73
# Verify that the actual two contact rows are symmetric about that center.
contacts = [s for s in usb.Solids if .047 < s.Volume < .061 and 2 < s.BoundBox.YLength < 2.5]
row_z = sorted(set(round((s.BoundBox.ZMin+s.BoundBox.ZMax)/2, 5) for s in contacts))
if len(row_z) != 2 or abs(sum(row_z)/2-center_z) > 1e-5:
    raise RuntimeError('Drawing datum does not match the native contact rows')
shoulder_y = face_y - 1.85
# The maximum receptacle aperture encloses the mating plug neck, conservatively
# using a rectangle (no corner relief). It sweeps the entire approach to the face.
neck = Part.makeBox(8.40, 20+face_y, 2.60, A.Vector(-4.20, -20, center_z-1.30))
neck_margin = Part.makeBox(8.70, 20+face_y, 2.90, A.Vector(-4.35, -20, center_z-1.45))
# Width is a gauge choice, not a USB/GCT universal cable dimension. The entire
# overmold remains outside the case Y extent; the axial separation is decisive.
overmold = Part.makeBox(13, 20, 6.50, A.Vector(-6.5, shoulder_y-20, center_z-3.25))
records = []
for name in ('PalmShell', 'FingerShellSupported', 'TopCoverSupported'):
    case = d.getObject(name).Shape
    for label, gauge in [('neck',neck), ('neck_0.15mm_margin',neck_margin), ('overmold',overmold)]:
        vol = overlap_volume(case,gauge)
        records.append({'case':name, 'gauge':label, 'overlap_mm3':vol})
        print(records[-1], flush=True)
group = d.addObject('App::DocumentObjectGroup','USBMatingGauges')
for name,shape in [('PlugNeckApproach',neck),('PlugNeckMargin',neck_margin),('PlugOvermold',overmold)]:
    o=d.addObject('PartDesign::Feature',name);o.Shape=shape;group.addObject(o)
d.recompute(); out=R/f'mechanical/AIKEY_REVA_DESIGN{args.revision}_USB_REVIEW.FCStd';d.saveAs(str(out))
case_min_y=min(d.getObject(n).Shape.optimalBoundingBox().YMin for n in ('PalmShell','FingerShellSupported','TopCoverSupported'))
result={'status':'NOMINAL_CASE_MATING_CLEARANCE_PASS' if max(x['overlap_mm3'] for x in records)<1e-5 and shoulder_y<case_min_y else 'FAIL',
 'native_file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'review_file':str(out),
 'drawing':{'url':'https://gct.co/files/drawings/usb4105.pdf','revision':'B4, 18/12/2023, sheet 1/2',
 'sha256':hashlib.sha256((R/'reference/usb4105.pdf').read_bytes()).hexdigest(),
 'min_mated_plug_shoulder_to_receptacle_face_mm':1.85,'max_overmold_height_mm':6.5},
 'native_connector_face_y_mm':face_y,'native_contact_rows_z_mm':row_z,'native_connector_center_z_mm':center_z,
 'mated_overmold_front_y_mm':shoulder_y,'case_min_y_mm':case_min_y,'nominal_overmold_axial_clearance_mm':case_min_y-shoulder_y,
 'checks':records,'scope':'Saved-native case obstruction during straight axial approach. The rectangular neck gauge encloses the maximum female aperture. Connector internal electrical mating is a specified functional interface, not a rigid-solid interference check.',
 'not_proven':['production tolerances','cable tilt and off-axis insertion','insertion/withdrawal force','plug supplier dimensional conformance','USB signal integrity']}
(R/f'reports/usb-mating-design{args.revision}.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
sys.exit(0 if result['status'].endswith('PASS') else 1)

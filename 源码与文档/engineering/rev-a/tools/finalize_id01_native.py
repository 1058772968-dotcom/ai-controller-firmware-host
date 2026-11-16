"""Persist native FreeCAD appearance, reopen it, and read back CAD dimensions."""
from pathlib import Path
import sys,json,hashlib,zipfile,os
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,FreeCADGui as Gui,Part
Gui.showMainWindow()
import ImportGui
R=Path(__file__).resolve().parents[1];D=Path(os.environ.get('ID01_OUTPUT_DIR',str(R/'mechanical/id01-reference')));p=D/'AIKEY_ID01_REFERENCE_04.FCStd'
palette={'shell':(.72,.71,.67),'cap':(.79,.78,.74),'key':(.19,.20,.20),'rubber':(.14,.15,.15),'strap':(.18,.19,.19),'gap':(.075,.08,.08),'metal':(.35,.37,.37),'gold':(.83,.55,.18),'led':(.17,.75,.89),'ink':(.90,.92,.91)}
d=A.openDocument(str(p))
for o in d.Objects:
    if o.ViewObject:o.ViewObject.Visibility=False
for o in d.ExteriorAssembly.Group:
    v=o.ViewObject;v.Visibility=True;v.ShapeColor=palette[o.MaterialRole];v.LineColor=palette[o.MaterialRole]
    # Shaded suppresses technical edge outlines in the saved exterior view.
    v.DisplayMode='Shaded'
    if 'Deviation' in v.PropertiesList:v.Deviation=.03
    if 'AngularDeflection' in v.PropertiesList:v.AngularDeflection=5
    if 'Shininess' in v.PropertiesList:v.Shininess=5
    if 'ShapeAppearance' in v.PropertiesList:
        materials=list(v.ShapeAppearance)
        for m in materials:
            if hasattr(m,'Shininess'):m.Shininess=8
            if hasattr(m,'SpecularColor'):m.SpecularColor=(.08,.08,.08)
        v.ShapeAppearance=materials
d.ExteriorAssembly.ViewObject.Visibility=True
v=Gui.activeDocument().activeView();v.setCameraType('Orthographic');v.setCameraOrientation(A.Rotation(A.Vector(0,0,1),A.Vector(-1,.4,1.6)).Q);v.fitAll();Gui.updateGui();v.redraw();Gui.updateGui()
d.recompute();d.save();A.closeDocument(d.Name);d=A.openDocument(str(p));v=Gui.activeDocument().activeView();v.fitAll();Gui.updateGui();v.redraw();Gui.updateGui()
v.saveImage(str(D/'native-warmup.png'),1400,1200,'White');v.redraw();Gui.updateGui();v.saveImage(str(D/'FreeCAD-native.png'),1400,1200,'White')
parts=d.ExteriorAssembly.Group;invalid=[o.Name for o in parts if not o.Shape.isValid()]
cap=d.TopCover.Shape.optimalBoundingBox(False,False);case=Part.makeCompound([o.Shape for o in parts if not o.Name.startswith('Strap') and o.Name!='HandStrap']).optimalBoundingBox(False,False)
full=Part.makeCompound([o.Shape for o in parts]).optimalBoundingBox(False,False)
step=p.with_suffix('.step');ImportGui.export(parts,str(step));s=Part.Shape();s.read(str(step))
solid_count=sum(len(o.Shape.Solids) for o in parts)
dimensions={'cap_width_x_mm':cap.XLength,'cap_depth_z_mm':cap.ZLength,'assembled_height_y_mm':case.YLength,'swept_grip_depth_z_mm':case.ZLength,'including_strap_xyz_mm':[full.XLength,full.YLength,full.ZLength]}
checks={'all_native_parts_valid':not invalid,'main_housing_single_solid':len(d.MainHousing.Shape.Solids)==1,'cap_width_52mm':abs(cap.XLength-52)<1e-4,'visual_priority_cap_depth_58mm':abs(cap.ZLength-58)<1e-4,'assembled_height_116mm':abs(case.YLength-116)<1e-4,'step_readback_valid':s.isValid(),'step_solid_count_matches':len(s.Solids)==solid_count,'native_gui_state_present':'GuiDocument.xml' in zipfile.ZipFile(p).namelist()}
report={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'dimensions':dimensions,'native_file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'step_sha256':hashlib.sha256(step.read_bytes()).hexdigest(),'native_part_count':len(parts),'solid_count':solid_count,'invalid':invalid,'scope':'Native exterior and exchange-file readback only; reference image fit and internal assembly qualification are separate.'}
(D/'native-readback.json').write_text(json.dumps(report,indent=2)+'\n')
previous={'status':'NATIVE_EXTERIOR_SAVED_REOPENED_VALID_SOLIDS' if all(checks.values()) else 'FAIL',
    'native_file':str(p),'sha256':report['sha256'],'native_gui_saved':True,
    'source_image_sha256':hashlib.sha256((D/'user-reference.png').read_bytes()).hexdigest(),
    'parts':[{'name':o.Name,'valid':o.Shape.isValid(),'solids':len(o.Shape.Solids),'volume_mm3':o.Shape.Volume} for o in parts],
    'dimensions':dimensions,'scope':report['scope'],'dimension_priority':'User explicitly selected reference image visual proportions; original 46 mm cap label is not retained.'}
(D/'native-validation.json').write_text(json.dumps(previous,indent=2)+'\n')
print(json.dumps(report),flush=True)
# Embedded FreeCAD/ImportGui can segfault during Python GUI finalizer teardown
# on this runtime. All saves, STEP reopening and report writes above finish
# synchronously; exit with the actual gate result after explicitly closing UI.
A.closeDocument(d.Name);Gui.getMainWindow().close();os._exit(0 if all(checks.values()) else 2)

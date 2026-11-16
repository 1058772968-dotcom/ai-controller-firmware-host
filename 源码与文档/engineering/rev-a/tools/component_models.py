#!/usr/bin/env python3
"""Nominal mechanical envelopes for models absent from installed library.

Dimensions are package-level datasheet dimensions; these are explicitly not
manufacturer detailed STEP models. The native FreeCAD source is also saved.
"""
from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as A,Part
r=Path(__file__).resolve().parents[1];doc=A.newDocument('AIKEY_Component_Envelopes')
specs=[
 ('aikey_mic','Infineon_PG-LLGA-5-1',[4,3,1.2],'IM69D130 datasheet package drawing, bottom port x=0.68 mm'),
 ('aikey_main','ESP32-S3-WROOM-1U',[18,19.2,3.2],'ESP32-S3-WROOM-1U datasheet package body, antenna connector clearance additional'),
 ('aikey_main','BQ24074RGTR',[3,3,1],'TI RGT0016C nominal package envelope'),
 ('aikey_main','MAX17048G',[2,2,.8],'ADI TDFN package envelope 2x2x0.8'),
 ('aikey_main','TPS63802DLAR',[2,3,1],'TI DLA0010A maximum height envelope'),
 ('aikey_main','Coilcraft_XFL4015',[4.3,4.3,1.6],'Coilcraft Doc769-2 maximum body dimensions'),
 ('aikey_main','Kingbright_APTF1616LSEEZGKQBKC',[1.6,1.6,.7],'Kingbright V9B nominal body, general dimensional tolerance +/-0.2 mm')]
rows=[]
for board,name,dims,source in specs:
 w,l,h=dims;f=doc.addObject('Part::Feature',name);f.Label=name+' (package envelope)'
 f.Shape=Part.makeBox(w,l,h,A.Vector(-w/2,-l/2,0))
 if name=='Infineon_PG-LLGA-5-1':f.Shape=f.Shape.cut(Part.makeCylinder(.3,.25,A.Vector(.68,0,0)))
 f.addProperty('App::PropertyString','Source');f.Source=source
 f.addProperty('App::PropertyString','VerificationBoundary');f.VerificationBoundary='Nominal envelope; not vendor detailed CAD; physical sample and stackup validation required'
 dest=r/'electrical'/board/'libraries/models'/f'{name}.step';dest.parent.mkdir(parents=True,exist_ok=True)
 doc.recompute();Part.export([f],str(dest))
 check=Part.Shape();check.read(str(dest));assert check.isValid() and len(check.Solids)==1
 rows.append({'board':board,'model':name,'dimensions_mm':dims,'source':source,'type':'datasheet_package_envelope','sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'readback_valid':True,'volume_mm3':check.Volume})
doc.saveAs(str(r/'mechanical/Component_Envelopes.FCStd'))
(r/'reports/component-models.json').write_text(json.dumps({'models':rows,'status':'NOMINAL_ENVELOPES_ONLY'},indent=2)+'\n')
A.closeDocument(doc.Name)

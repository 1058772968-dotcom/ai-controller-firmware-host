"""Bind local, explicitly nominal STEP envelopes to the native footprint assets."""
from sexpr import parse,dump,one,Atom
import json
MODELS={
 'ESP32-S3-WROOM-1U_ThermalVia03':'ESP32-S3-WROOM-1U',
 'VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm':'BQ24074RGTR',
 'TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm':'MAX17048G',
 'ADI_MAX17048_90-0065_RevE':'MAX17048G',
 'TI_DLA0010A_TPS63802':'TPS63802DLAR',
 'Coilcraft_XFL4015':'Coilcraft_XFL4015',
 'Kingbright_APTF1616LSEEZGKQBKC':'Kingbright_APTF1616LSEEZGKQBKC'}
def attach(p):
 for name,model in MODELS.items():
  file=p.fp/(name+'.kicad_mod')
  if not file.exists():continue
  assert (p.lib/'models'/f'{model}.step').is_file(),model
  f=parse(file.read_text());f[:]=[v for v in f if not (isinstance(v,list) and v and v[0]=='model')]
  path='${KIPRJMOD}/libraries/models/'+model+'.step'
  f.append(parse(f'(model {json.dumps(path)} (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))'))
  file.write_text(dump(f)+'\n')

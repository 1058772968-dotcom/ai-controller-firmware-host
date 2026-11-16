#!/usr/bin/env python3
"""Create and measure acoustic DFM variant; manufacturer original retained."""
from pathlib import Path
import sys,json,math,hashlib
from shapely.geometry import Point,Polygon
from sexpr import parse,dump,children,one,Atom
folder=Path(sys.argv[1]);src=folder/'Infineon_PG-LLGA-5-1.kicad_mod'
f=parse(src.read_text());name='Infineon_PG-LLGA-5-1_AcousticRing03';f[1]=name
p5=next(p for p in children(f,'pad') if p[1]=='5')
one(p5,'size')[1:]=[.3,.3]
one(one(one(p5,'primitives'),'gr_circle'),'width')[1]=.3
# Clip the six annular paste apertures to a 0.24 mm band, leaving a nominal
# 0.03 mm copper margin. Four rectangular signal lands remain unchanged.
center=Point(.68,0);aperture=center.buffer(.93,resolution=128).difference(center.buffer(.69,resolution=128))
rows=[]
for i,p in enumerate(children(f,'pad')):
 if p[1] or one(p,'layers')!=['layers','F.Paste']:continue
 a=one(p,'at');x,y=float(a[1]),float(a[2])
 if x<-.2:continue
 g=one(one(p,'primitives'),'gr_poly');pts=one(g,'pts')
 old=Polygon([(float(v[1])+x,float(v[2])+y) for v in pts[1:]])
 new=old.intersection(aperture)
 assert new.geom_type=='Polygon' and new.is_valid and not new.interiors
 pts[1:]=[[Atom('xy'),round(px-x,6),round(py-y,6)] for px,py in list(new.exterior.coords)[:-1]]
 one(p,'size')[1:]=[.15,.15]
 rows.append({'aperture':i,'original_area_mm2':old.area,'variant_area_mm2':new.area})
model=one(f,'model');model[1]='${KIPRJMOD}/libraries/models/Infineon_PG-LLGA-5-1.step'
dest=folder/(name+'.kicad_mod');dest.write_text(dump(f)+'\n')
r=Path(__file__).resolve().parents[1]
report={'source':'KiCad 10.0.6 Infineon PG-LLGA-5-1','manufacturer_datasheet':'https://www.infineon.com/dgdl/Infineon-IM69D130-DS-v01_00-EN.pdf?fileId=5546d462602a9dc801607a0e46511a2e','source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'variant':name,'variant_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'hole_diameter_mm':.8,'ground_ring_center_radius_mm':.81,'ground_ring_copper_width_mm':.30,'minimum_nominal_drill_copper_gap_mm':.26,'paste_apertures':rows,'nominal_radial_copper_margin_mm':.03,'reason':'Retain project 0.25 mm hole-to-copper constraint. Original library annulus did not meet it. Copper annulus and six stencil openings are explicitly revised, not the sound hole.','qualification':'ENGINEERING_DERIVATIVE; 0.30 mm continuous ground seal, paste volume, acoustic leakage and reflow must be qualified on prototype; not manufacturer-approved land.'}
(r/'reports/mic-footprint-dfm.json').write_text(json.dumps(report,indent=2)+'\n');print(dest)

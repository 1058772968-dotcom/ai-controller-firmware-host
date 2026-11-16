#!/usr/bin/env python3
"""Preserve reference/duplicate assets outside the active native footprint table."""
import argparse,json
from pathlib import Path
from sexpr import parse,children
R=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('board',default='aikey_main',nargs='?');args=ap.parse_args()
P=R/'electrical'/args.board;folder=P/'libraries/AIKEY.pretty';dest=P/'libraries/reference-footprints';dest.mkdir(exist_ok=True)
t=parse((P/(args.board+'.kicad_pcb')).read_text());used={str(fp[1]).split(':',1)[1] for fp in children(t,'footprint') if str(fp[1]).startswith('AIKEY:')}
moved=[]
for file in folder.glob('*.kicad_mod'):
    if file.stem in used:continue
    target=dest/file.name
    if target.exists():continue
    file.rename(target);moved.append(file.name)
(R/'reports'/f'{args.board}-library-archive.json').write_text(json.dumps({'active_footprints':sorted(used),'archived_unused':moved,'destination':str(dest),'reason':'KiCad enumerates every file in an active library. Unused iCloud placeholders caused blocking reads. Reference assets preserved without replacing their contents.'},indent=2)+'\n')
print('Preserved',len(moved),'unused/reference footprints outside active library')

#!/usr/bin/env python3
"""Remove only native-DRC-confirmed dead-end copper, preserving connected nets."""
from pathlib import Path
import json,subprocess
from sexpr import parse,dump,children,one,CLI
r=Path(__file__).resolve().parents[1];f=r/'electrical/aikey_main/aikey_main.kicad_pcb';report=r/'reports/main-board-drc.json'
removed=[]
for iteration in range(20):
    subprocess.run([CLI,'pcb','drc','--refill-zones','--save-board','--schematic-parity','--severity-all','--format','json','--output',str(report),str(f)],check=True,capture_output=True)
    d=json.loads(report.read_text())
    if d['unconnected_items'] or d['schematic_parity']:raise RuntimeError('Unconnected net/parity error: automatic stub cleanup refused')
    unexpected=[v for v in d['violations'] if v['type'] not in ('track_dangling','via_dangling')]
    if unexpected:raise RuntimeError(json.dumps(unexpected))
    if not d['violations']:break
    ids={v['items'][0]['uuid'] for v in d['violations']}
    tree=parse(f.read_text());count=0
    for item in children(tree,'via')+children(tree,'segment'):
        if one(item,'uuid')[1] in ids:
            removed.append({'iteration':iteration,'item':item});tree.remove(item);count+=1
    if count!=len(ids):raise RuntimeError('DRC IDs did not match native copper')
    f.write_text(dump(tree)+'\n')
else:raise RuntimeError('Cleanup did not converge')
(r/'reports/main-stub-cleanup.json').write_text(json.dumps({'status':'NATIVE_DRC_PASS','removed':removed,'iterations':iteration+1},indent=2)+'\n')
print('Native DRC: zero violations, zero unrouted, zero parity errors. Removed',len(removed),'dead-end copper items.')

#!/usr/bin/env python3
from pathlib import Path
import subprocess,json,hashlib,sys
r=Path(__file__).resolve().parents[1];results=[]
for name in ['host_transactions_test.py','host_device_test.py','host_http_test.py','host_physical_test.py','config_protocol_test.py']:
 p=subprocess.run([sys.executable,str(r/'tests'/name)],capture_output=True,text=True)
 results.append({'test':name,'exit_code':p.returncode,'log':p.stdout+p.stderr});print(name,p.returncode,flush=True)
sources=list((r/'host').glob('*.py'))+[r/'host/controller_sim.c']+list((r/'tests').glob('host_*test.py'))+[r/'tests/config_protocol_test.py']
sources += [r/'firmware/core'/name for name in ['controller.c','controller.h','protocol.c','protocol.h','board_config.h']]
sources += [r/'firmware/core'/name for name in ['settings.c','settings.h']]
report={'status':'PASS' if all(x['exit_code']==0 for x in results) else 'FAIL','scope':'Real local HTTP and temporary files; C firmware core and protocol through native shared library; USB/BLE API adapter doubles and ACK-driven companion; no physical USB/BLE/audio peripheral',
 'results':results,'sha256':{str(f.relative_to(r)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}}
(r/'reports/host-integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
raise SystemExit(0 if report['status']=='PASS' else 1)

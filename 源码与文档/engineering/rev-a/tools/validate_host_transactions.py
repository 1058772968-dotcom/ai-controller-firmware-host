#!/usr/bin/env python3
from pathlib import Path
import subprocess,json,hashlib,sys
r=Path(__file__).resolve().parents[1]
p=subprocess.run([sys.executable,str(r/'tests/host_transactions_test.py')],capture_output=True,text=True)
report={'scope':'real temporary filesystem operations; local exact replacement adapter, not AI or physical hardware','status':'PASS' if p.returncode==0 else 'FAIL','exit_code':p.returncode,'log':p.stdout+p.stderr,'sha256':{str(f.relative_to(r)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [r/'host/transactions.py',r/'host/local_adapter.py',r/'tests/host_transactions_test.py']}}
(r/'reports/host-transactions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(report['log']);raise SystemExit(p.returncode)

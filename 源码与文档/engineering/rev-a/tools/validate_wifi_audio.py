#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,ssl,subprocess,sys
r=Path(__file__).resolve().parents[1]
if not getattr(ssl,'HAS_PSK',False):raise SystemExit('Use Python with TLS PSK support, e.g. /opt/homebrew/bin/python3.14')
p=subprocess.run([sys.executable,str(r/'tests/wifi_audio_test.py')],capture_output=True,text=True)
names=['host/wifi_audio.py','tests/wifi_audio_test.py','firmware/core/audio_wire.c','firmware/core/audio_wire.h']
result={'status':'PASS' if p.returncode==0 else 'FAIL','scope':'Real loopback TLS 1.2 PSK-AES128-GCM-SHA256; actual portable C audio frame encoder and Python receiver; no ESP radio or PDM hardware','python':sys.version,'tls':ssl.OPENSSL_VERSION,'log':p.stdout+p.stderr,'source_sha256':{n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in names}}
(r/'reports/wifi-audio-validation.json').write_text(json.dumps(result,indent=2)+'\n');print(result['log']);raise SystemExit(p.returncode)

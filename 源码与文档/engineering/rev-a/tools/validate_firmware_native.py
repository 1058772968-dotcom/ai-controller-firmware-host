#!/usr/bin/env python3
"""Compile real portable firmware modules and run behavior tests with sanitizers."""
from pathlib import Path
import subprocess,tempfile,json,hashlib
root=Path(__file__).resolve().parents[1]
cases={'controller':['controller.c'],'protocol':['controller.c','protocol.c'],'signal':['motion.c','audio_filter.c'],'peripherals':['peripherals.c'],'link_policy':['controller.c','link_policy.c'],'settings':['controller.c','protocol.c','settings.c'],'audio_wire':['audio_wire.c']}
records=[]
with tempfile.TemporaryDirectory(prefix='aikey-native-') as temp:
    for name,sources in cases.items():
        executable=str(Path(temp)/name)
        files=[root/'firmware/core'/s for s in sources]+[root/'tests'/f'{name}_test.c']
        command=['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-fsanitize=address,undefined','-I'+str(root/'firmware/core')]+[str(f) for f in files]+['-o',executable]
        build=subprocess.run(command,capture_output=True,text=True)
        run=subprocess.run([executable],capture_output=True,text=True) if build.returncode==0 else None
        records.append({'test':name,'build_exit':build.returncode,'test_exit':run.returncode if run else None,'log':build.stdout+build.stderr+(run.stdout+run.stderr if run else ''),'source_sha256':{str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}})
report={'scope':'actual portable firmware code executed natively; no physical device','status':'PASS' if all(r['build_exit']==0 and r['test_exit']==0 for r in records) else 'FAIL','tests':records}
(root/'reports/firmware-native-tests.json').write_text(json.dumps(report,indent=2)+'\n')
for r in records:print(r['log'])
raise SystemExit(0 if report['status']=='PASS' else 1)

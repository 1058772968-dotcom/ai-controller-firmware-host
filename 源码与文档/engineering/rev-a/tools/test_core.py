#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
subprocess.run(['python3',str(ROOT/'tools/generate_board_config.py')],check=True)
files=[ROOT/'firmware/core/controller.c',ROOT/'firmware/core/controller.h',ROOT/'firmware/core/board_config.h',ROOT/'tests/controller_test.c']
with tempfile.TemporaryDirectory(prefix='aikey-core-') as tmp:
    command=['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-g','-fsanitize=address,undefined','-I'+str(ROOT/'firmware/core'),str(files[0]),str(files[3]),'-o',str(Path(tmp)/'test')]
    built=subprocess.run(command,text=True,capture_output=True)
    run=subprocess.run([str(Path(tmp)/'test')],text=True,capture_output=True) if built.returncode==0 else None
    report={'scope':'native build of actual portable firmware core; not MCU or hardware execution','compiler_command':command,'build_exit':built.returncode,'build_log':built.stdout+built.stderr,'test_exit':run.returncode if run else None,'test_log':run.stdout+run.stderr if run else None,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'status':'PASS' if run and run.returncode==0 else 'FAIL'}
    (ROOT/'reports/core-tests.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['build_log']);print(report['test_log']);print(report['status'])
    raise SystemExit(0 if report['status']=='PASS' else 1)

#!/usr/bin/env python3
"""Reproduce task-local, pinned native inference engines without changing ESP-IDF."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CACHE=Path.home()/'.cache/ai-key-rev-a/local-ai'
ENGINES=[
 {'name':'whisper','repo':'https://github.com/ggml-org/whisper.cpp.git','folder':'whisper.cpp','tag':'v1.9.4','commit':'927cfce34f31707e17f2bff35c349632fb9e2c3a','targets':['whisper-cli'],'extra':['-DWHISPER_BUILD_TESTS=OFF']},
 {'name':'llama','repo':'https://github.com/ggml-org/llama.cpp.git','folder':'llama.cpp','tag':'v0.5.0','commit':'7fe450e19305b828c199d602c23a8337aaa1f03b','targets':['llama-cli','llama-server'],'extra':['-DLLAMA_BUILD_TESTS=OFF','-DLLAMA_BUILD_SERVER=ON']},
]
def run(args,**kw):return subprocess.run(list(map(str,args)),check=True,**kw)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
parser=argparse.ArgumentParser();parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
CACHE.mkdir(parents=True,exist_ok=True);records=[]
for engine in ENGINES:
 source=CACHE/engine['folder'];build=CACHE/('build-'+engine['name'])
 if not source.exists():
  if args.verify_only:raise RuntimeError('Engine source missing: '+str(source))
  run(['git','clone','--depth','1','--branch',engine['tag'],engine['repo'],source])
 head=run(['git','-C',source,'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
 dirty=run(['git','-C',source,'status','--porcelain'],capture_output=True,text=True).stdout.strip()
 if head!=engine['commit'] or dirty:raise RuntimeError('Existing source differs; inspect instead of overwriting '+str(source))
 if not args.verify_only:
  run(['cmake','-S',source,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DGGML_METAL=ON','-DGGML_METAL_EMBED_LIBRARY=ON',*engine['extra']])
  run(['cmake','--build',build,'--target',*engine['targets'],'--parallel','3'])
 binaries={name:sha(build/'bin'/name) for name in engine['targets']}
 records.append(dict(engine,source_clean=True,head=head,binary_sha256=binaries))
report={'status':'PINNED_NATIVE_ENGINES_VERIFIED','cache':str(CACHE),'engines':records,
 'models':'tools/fetch_local_model.py asr and text; publisher size and SHA256 required before activation',
 'network':'Model downloads fetch public weights. Inference binds only to 127.0.0.1 and sends no user context externally.'}
(ROOT/'reports/local-ai-runtime.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'])
if not args.verify_only:
 for kind in ('asr','text'):run([sys.executable,ROOT/'tools/fetch_local_model.py',kind])

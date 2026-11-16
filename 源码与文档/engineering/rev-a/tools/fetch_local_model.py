#!/usr/bin/env python3
"""Fetch a public, pinned model into the task cache and verify publisher SHA256."""
import argparse,hashlib,json,urllib.request,time,re
from pathlib import Path
R=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('kind',choices=['asr','text']);args=ap.parse_args()
repo='ggerganov/whisper.cpp' if args.kind=='asr' else 'Qwen/Qwen2.5-1.5B-Instruct-GGUF'
m=next(v for v in json.loads((R/'reports/local-model-sources.json').read_text()) if v['repo']==repo)
cache=Path('/Users/linxiansheng/.cache/ai-key-rev-a/local-ai/models');cache.mkdir(parents=True,exist_ok=True)
dest=cache/m['filename'];partial=dest.with_suffix(dest.suffix+'.partial')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
expected=m['metadata']['lfs']['sha256'];size=m['metadata']['size'];start=time.monotonic()
if not dest.exists():
    url=f'https://huggingface.co/{repo}/resolve/{m["revision"]}/{m["filename"]}'
    for attempt in range(6):
        count=partial.stat().st_size if partial.exists() else 0
        if count==size:break
        if count>size:raise RuntimeError('Oversized partial; inspect before retry')
        milestone=count//(64*1024*1024)
        request=urllib.request.Request(url,headers={'Range':f'bytes={count}-'} if count else {})
        try:
            with urllib.request.urlopen(request,timeout=45) as response:
                if count and response.status==206:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if not match or int(match[1])!=count or int(match[3])!=size:
                        raise RuntimeError('Invalid Content-Range; refusing append')
                    mode='ab'
                elif response.status==200:
                    count=0;milestone=0;mode='wb'
                else:raise RuntimeError('Unexpected HTTP status: '+str(response.status))
                with partial.open(mode) as out:
                    while True:
                        block=response.read(4*1024*1024)
                        if not block:break
                        if count+len(block)>size:raise RuntimeError('Response exceeds publisher size')
                        out.write(block);count+=len(block)
                        if count//(64*1024*1024)>milestone:
                            milestone=count//(64*1024*1024);print(f'{args.kind}: {count}/{size} bytes',flush=True)
        except (OSError,TimeoutError) as error:
            print(f'{args.kind}: interrupted ({type(error).__name__}); verified-range resume attempt {attempt+1}',flush=True)
        retained=partial.stat().st_size if partial.exists() else 0
        if retained==size:break
        print(f'{args.kind}: short download; retained {retained} bytes',flush=True)
    if not partial.exists() or partial.stat().st_size!=size:raise RuntimeError('Incomplete model; partial retained and not activated')
    if sha(partial)!=expected:raise RuntimeError('Publisher hash mismatch; partial retained and not activated')
    partial.replace(dest)
if dest.stat().st_size!=size or sha(dest)!=expected:raise RuntimeError('Installed model failed publisher size/SHA256 verification')
report={'status':'PUBLISHER_SIZE_AND_SHA256_VERIFIED','kind':args.kind,'model':m,'path':str(dest),'elapsed_s':time.monotonic()-start,'inference_test':'not yet run'}
(R/f'reports/local-model-{args.kind}.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':report['status'],'path':str(dest)}),flush=True)

"""Local file change boundary: locked context, separate confirmations and receipts.

This module does not implement an LLM or claim that a model ran. An adapter is
called only by confirm_send. Applying and undoing are distinct, verified writes.
"""
from pathlib import Path
from dataclasses import dataclass
import hashlib,json,os,secrets,tempfile,time,threading
from functools import wraps
def serialized(fn):
 @wraps(fn)
 def call(self,*args,**kwargs):
  with self._mutex:return fn(self,*args,**kwargs)
 return call

LIMIT=1024*1024
class Conflict(RuntimeError):pass
class Rejected(ValueError):pass
def digest(data):return hashlib.sha256(data).hexdigest()
def encode(text):
 if not isinstance(text,str):raise Rejected('text must be UTF-8 string')
 raw=text.encode('utf-8')
 if len(raw)>LIMIT or b'\0' in raw:raise Rejected('text limit or NUL')
 return raw
@dataclass(frozen=True)
class Context:
 id:str
 path:str
 sha256:str
 text:str
 captured_ns:int

class Workspace:
 def __init__(self,root,journal):
  self.root=Path(root).resolve(strict=True);self.journal=Path(journal).resolve()
  if not self.root.is_dir():raise Rejected('workspace is not a directory')
  self.journal.mkdir(parents=True,exist_ok=True)
  self._mutex=threading.RLock();self.contexts={};self.proposals={};self.receipts={};self.used=set()
 def target(self,relative):
  if not isinstance(relative,str) or not relative:raise Rejected('path required')
  p=Path(relative)
  if p.is_absolute() or '..' in p.parts:raise Rejected('relative workspace path required')
  path=self.root/p
  # Do not follow file or directory symlinks, including inside the workspace.
  node=self.root
  for part in p.parts:
   node=node/part
   if node.is_symlink():raise Rejected('symlinks are not editable targets')
  resolved=path.resolve(strict=True)
  if not resolved.is_relative_to(self.root) or not resolved.is_file():raise Rejected('not a workspace file')
  if resolved.stat().st_nlink!=1:raise Rejected('hard-linked files are not editable targets')
  return resolved
 def read(self,relative):
  path=self.target(relative)
  if path.stat().st_size>LIMIT:raise Rejected('file exceeds 1 MiB')
  with open(path,'rb') as f:raw=f.read(LIMIT+1)
  if len(raw)>LIMIT or b'\0' in raw:raise Rejected('binary or oversized file')
  try:text=raw.decode('utf-8')
  except UnicodeDecodeError as e:raise Rejected('UTF-8 text required') from e
  return path,raw,text
 @serialized
 def lock(self,relative):
  _,raw,text=self.read(relative)
  c=Context(secrets.token_urlsafe(24),str(Path(relative)),digest(raw),text,time.time_ns())
  self.contexts[c.id]=c;return c
 def confirm_send(self,context_id,instruction,adapter):
  """First explicit user action. Preview generation never writes the target."""
  if not isinstance(instruction,str) or not instruction.strip() or len(instruction)>8000:raise Rejected('nonempty instruction <=8000 characters required')
  with self._mutex:
   if context_id not in self.contexts:raise Rejected('unknown or expired context')
   if context_id in self.used:raise Rejected('context already sent; capture again')
   c=self.contexts[context_id]
   if digest(self.read(c.path)[1])!=c.sha256:raise Conflict('target changed since trigger was pressed')
   self.used.add(c.id)
  # Snapshot text and path cannot be replaced by caller-provided new context.
  output=adapter(c,instruction.strip())
  if not isinstance(output,dict) or set(output)!={'new_text','adapter','summary'}:raise Rejected('adapter response schema')
  raw=encode(output['new_text'])
  if raw==encode(c.text):raise Rejected('adapter proposed no change')
  if not all(isinstance(output[k],str) and output[k] for k in ('adapter','summary')):raise Rejected('adapter identity and summary required')
  proposal={'id':secrets.token_urlsafe(24),'context_id':c.id,'path':c.path,'before_sha256':c.sha256,'after_sha256':digest(raw),'new_text':output['new_text'],'adapter':output['adapter'],'summary':output['summary'],'created_ns':time.time_ns()}
  with self._mutex:
   if self.contexts.get(c.id) is not c:raise Rejected('request cancelled while adapter was running')
   if digest(self.read(c.path)[1])!=c.sha256:raise Conflict('target changed during model inference')
   self.proposals[proposal['id']]=proposal
   return dict(proposal)
 def _record(self,record):
  path=self.journal/(record['id']+'.json')
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w',encoding='utf-8') as f:
   json.dump(record,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
  dfd=os.open(self.journal,os.O_RDONLY)
  try:os.fsync(dfd)
  finally:os.close(dfd)
 def _replace(self,relative,expected,raw):
  target,current,_=self.read(relative)
  if digest(current)!=expected:raise Conflict('target changed; write refused')
  fd,temp=tempfile.mkstemp(prefix='.aikey-',dir=target.parent)
  try:
   with os.fdopen(fd,'wb') as f:
    os.fchmod(f.fileno(),target.stat().st_mode & 0o777);f.write(raw);f.flush();os.fsync(f.fileno())
   # Recheck after preparing the temporary file; refuse a stale proposal.
   if digest(self.read(relative)[1])!=expected:raise Conflict('target changed while preparing write')
   os.replace(temp,target)
   dfd=os.open(target.parent,os.O_RDONLY)
   try:os.fsync(dfd)
   finally:os.close(dfd)
  finally:
   if os.path.exists(temp):os.unlink(temp)
  actual=self.read(relative)[1]
  if actual!=raw:raise Conflict('write readback mismatch; no success receipt')
  return digest(actual)
 @serialized
 def confirm_apply(self,proposal_id):
  """Second explicit user action. Every success requires actual file readback."""
  if proposal_id not in self.proposals:raise Rejected('unknown, used or expired proposal')
  p=self.proposals[proposal_id];c=self.contexts[p['context_id']]
  if digest(self.read(c.path)[1])!=p['before_sha256']:raise Conflict('target changed after preview')
  tx=secrets.token_urlsafe(24)
  intent={'id':tx,'phase':'intent','kind':'apply','path':c.path,'proposal_id':proposal_id,'before_sha256':c.sha256,'after_sha256':p['after_sha256'],'before_text':c.text,'after_text':p['new_text'],'time_ns':time.time_ns()}
  self._record(intent)
  actual=self._replace(c.path,c.sha256,encode(p['new_text']))
  receipt={'id':secrets.token_urlsafe(24),'transaction_id':tx,'phase':'verified','kind':'apply','path':c.path,'proposal_id':proposal_id,'before_sha256':c.sha256,'after_sha256':actual,'readback_verified':True,'time_ns':time.time_ns()}
  self._record(receipt);self.receipts[receipt['id']]=dict(receipt,before_text=c.text)
  del self.proposals[proposal_id]
  return dict(receipt)
 @serialized
 def confirm_undo(self,receipt_id):
  if receipt_id not in self.receipts:raise Rejected('unknown or already undone receipt')
  previous=self.receipts[receipt_id]
  if digest(self.read(previous['path'])[1])!=previous['after_sha256']:raise Conflict('file changed since apply; undo refused')
  tx=secrets.token_urlsafe(24)
  self._record({'id':tx,'phase':'intent','kind':'undo','path':previous['path'],'apply_receipt':receipt_id,'before_sha256':previous['after_sha256'],'after_sha256':previous['before_sha256'],'before_text':self.read(previous['path'])[2],'after_text':previous['before_text'],'time_ns':time.time_ns()})
  actual=self._replace(previous['path'],previous['after_sha256'],encode(previous['before_text']))
  receipt={'id':secrets.token_urlsafe(24),'transaction_id':tx,'phase':'verified','kind':'undo','path':previous['path'],'apply_receipt':receipt_id,'after_sha256':actual,'readback_verified':True,'time_ns':time.time_ns()}
  self._record(receipt);del self.receipts[receipt_id];return receipt
 @serialized
 def cancel(self):
  self.contexts.clear();self.proposals.clear();self.used.clear()
 @serialized
 def pending_recovery(self):
  """Report interrupted intents. Never silently replay an edit after restart."""
  records=[json.loads(p.read_text()) for p in self.journal.glob('*.json')]
  completed={x['transaction_id'] for x in records if x.get('phase')=='verified'}
  pending=[]
  for record in records:
   if record.get('phase')!='intent' or record['id'] in completed:continue
   try:actual=digest(self.read(record['path'])[1])
   except (OSError,Rejected):actual=None
   state='unchanged' if actual==record['before_sha256'] else 'write_present_without_receipt' if actual==record['after_sha256'] else 'conflict'
   pending.append({'transaction_id':record['id'],'path':record['path'],'state':state,'action':'manual review required; no automatic write or success feedback'})
  return pending

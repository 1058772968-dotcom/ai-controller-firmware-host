import unittest,tempfile,sys,json,os,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from transactions import Workspace,Rejected,Conflict,digest
from local_adapter import replace_text
class Transactions(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  (self.root/'work').mkdir();self.path=self.root/'work/example.txt';self.path.write_text('按钮颜色：灰色\n',encoding='utf-8')
  self.w=Workspace(self.root/'work',self.root/'journal')
 def tearDown(self):self.temp.cleanup()
 def proposal(self):
  c=self.w.lock('example.txt');return self.w.confirm_send(c.id,'把「灰色」替换为「蓝色」',replace_text)
 def test_two_confirmations_and_verified_undo(self):
  original=self.path.read_bytes();c=self.w.lock('example.txt');self.assertEqual(self.path.read_bytes(),original)
  p=self.w.confirm_send(c.id,'把「灰色」替换为「蓝色」',replace_text);self.assertEqual(self.path.read_bytes(),original)
  receipt=self.w.confirm_apply(p['id']);self.assertEqual(digest(self.path.read_bytes()),receipt['after_sha256']);self.assertTrue(receipt['readback_verified'])
  undo=self.w.confirm_undo(receipt['id']);self.assertEqual(self.path.read_bytes(),original);self.assertTrue(undo['readback_verified']);self.assertEqual(self.w.pending_recovery(),[])
 def test_missing_apply_permission(self):
  before=self.path.read_bytes()
  with self.assertRaises(Rejected):self.w.confirm_apply('not-issued')
  self.assertEqual(self.path.read_bytes(),before)
 def test_context_stale_before_send(self):
  c=self.w.lock('example.txt');self.path.write_text('externally changed')
  with self.assertRaises(Conflict):self.w.confirm_send(c.id,'change',lambda *_:self.fail('must not call adapter'))
 def test_changed_after_preview(self):
  p=self.proposal();self.path.write_text('newer user edit')
  with self.assertRaises(Conflict):self.w.confirm_apply(p['id'])
  self.assertEqual(self.path.read_text(),'newer user edit')
 def test_undo_preserves_newer_edit(self):
  p=self.proposal();r=self.w.confirm_apply(p['id']);self.path.write_text('do not overwrite')
  with self.assertRaises(Conflict):self.w.confirm_undo(r['id'])
  self.assertEqual(self.path.read_text(),'do not overwrite')
 def test_cancel_invalidates_tokens(self):
  p=self.proposal();self.w.cancel()
  with self.assertRaises(Rejected):self.w.confirm_apply(p['id'])
 def test_no_automatic_replay_after_restart(self):
  p=self.proposal();fresh=Workspace(self.w.root,self.w.journal)
  with self.assertRaises(Rejected):fresh.confirm_apply(p['id'])
  self.assertIn('灰色',self.path.read_text())
 def test_symlink_and_traversal(self):
  (self.w.root/'link.txt').symlink_to(self.path)
  for name in ['../work/example.txt',str(self.path),'link.txt']:
   with self.assertRaises(Rejected):self.w.lock(name)
 def test_hard_link_rejected(self):
  os.link(self.path,self.w.root/'hard.txt')
  with self.assertRaises(Rejected):self.w.lock('hard.txt')
 def test_binary_and_limit(self):
  self.path.write_bytes(b'x\0y')
  with self.assertRaises(Rejected):self.w.lock('example.txt')
  self.path.write_bytes(b'x'*(1024*1024+1))
  with self.assertRaises(Rejected):self.w.lock('example.txt')
 def test_adapter_failure_no_write(self):
  c=self.w.lock('example.txt')
  with self.assertRaises(Rejected):self.w.confirm_send(c.id,'unknown instruction',replace_text)
  self.assertIn('灰色',self.path.read_text())
 def test_concurrent_apply_at_most_once(self):
  p=self.proposal()
  def apply():
   try:return self.w.confirm_apply(p['id'])
   except Rejected:return None
  with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(lambda _:apply(),range(2)))
  self.assertEqual(sum(x is not None for x in r),1)
 def test_receipt_failure_never_report_success(self):
  p=self.proposal();record=self.w._record
  def fail_verified(r):
   if r['phase']=='verified':raise OSError('injected journal failure')
   record(r)
  self.w._record=fail_verified
  with self.assertRaises(OSError):self.w.confirm_apply(p['id'])
  recovery=Workspace(self.w.root,self.w.journal).pending_recovery()
  self.assertEqual(recovery[0]['state'],'write_present_without_receipt');self.assertIn('蓝色',self.path.read_text())
 def test_malformed_adapter_result(self):
  c=self.w.lock('example.txt')
  with self.assertRaises(Rejected):self.w.confirm_send(c.id,'x',lambda *_:{'new_text':'evil','execute':'rm'})
 def test_ambiguous_replace_rejected(self):
  self.path.write_text('灰色 灰色')
  with self.assertRaises(Rejected):self.proposal()
 def test_cancel_during_inference_discards_late_result(self):
  entered=threading.Event();release=threading.Event();c=self.w.lock('example.txt')
  def slow(context,instruction):
   entered.set();release.wait(2);return replace_text(context,instruction)
  with ThreadPoolExecutor(max_workers=1) as pool:
   job=pool.submit(self.w.confirm_send,c.id,'把「灰色」替换为「蓝色」',slow)
   self.assertTrue(entered.wait(1));self.w.cancel();release.set()
   with self.assertRaises(Rejected):job.result()
  self.assertFalse(self.w.proposals);self.assertIn('灰色',self.path.read_text())
 def test_duplicate_send_cannot_run_two_models(self):
  entered=threading.Event();release=threading.Event();c=self.w.lock('example.txt')
  def slow(context,instruction):
   entered.set();release.wait(2);return replace_text(context,instruction)
  with ThreadPoolExecutor(max_workers=1) as pool:
   job=pool.submit(self.w.confirm_send,c.id,'把「灰色」替换为「蓝色」',slow)
   self.assertTrue(entered.wait(1))
   with self.assertRaises(Rejected):self.w.confirm_send(c.id,'x',lambda *_:self.fail('duplicate inference'))
   release.set();job.result()
if __name__=='__main__':unittest.main(verbosity=2)

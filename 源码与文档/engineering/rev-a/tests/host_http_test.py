import json,sys,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from server import Application,Server

class HTTPBoundary(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'work').mkdir()
  self.file=self.root/'work/example.txt';self.file.write_text('按钮颜色：灰色\n')
  self.app=Application(self.root/'work',self.root/'journal');self.server=Server(('127.0.0.1',0),self.app)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.url=f'http://127.0.0.1:{self.server.server_port}'
 def tearDown(self):self.server.shutdown();self.server.server_close();self.app.close();self.temp.cleanup()
 def post(self,path,data,origin=None,token=None):
  req=urllib.request.Request(self.url+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':origin or self.url,'X-AIKEY-Session':token or self.app.token})
  try:
   with urllib.request.urlopen(req,timeout=5) as response:return response.status,json.load(response)
  except urllib.error.HTTPError as error:return error.code,json.load(error)
 def test_external_origin_and_missing_token_cannot_lock_or_write(self):
  self.assertEqual(self.post('/api/lock',{'path':'example.txt'},origin='https://unrelated.example')[0],403)
  self.assertEqual(self.post('/api/lock',{'path':'example.txt'},token='invalid')[0],403)
  self.assertFalse(self.app.workspace.contexts)
 def test_two_confirmations_and_real_http_undo(self):
  status,c=self.post('/api/lock',{'path':'example.txt'});self.assertEqual(status,200)
  data={'context_id':c['id'],'instruction':'把「灰色」替换为「蓝色」','adapter':'exact-replace'}
  self.assertEqual(self.post('/api/send',data)[0],400)
  status,p=self.post('/api/send',dict(data,confirmed=True));self.assertEqual(status,200)
  self.assertIn('灰色',self.file.read_text())
  self.assertEqual(self.post('/api/apply',{'proposal_id':p['id']})[0],400)
  status,r=self.post('/api/apply',{'proposal_id':p['id'],'confirmed':True});self.assertEqual(status,200);self.assertIn('蓝色',self.file.read_text())
  status,u=self.post('/api/undo',{'receipt_id':r['id'],'confirmed':True});self.assertEqual(status,200);self.assertIn('灰色',self.file.read_text());self.assertTrue(u['readback_verified'])
 def test_host_header_rebinding_refused(self):
  req=urllib.request.Request(self.url+'/',headers={'Host':'unrelated.example'})
  with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
  self.assertEqual(error.exception.code,403)
 def test_no_hardware_is_explicit(self):
  status,s=self.post('/api/status',{});self.assertEqual(s['device_mode'],'disconnected')
  self.assertEqual(self.post('/api/device/pulse',{})[0],400)
 def test_annotation_text_is_derived_from_locked_file_including_trailing_line(self):
  status,c=self.post('/api/lock',{'path':'example.txt','annotations':{'regions':[],'arrows':[],'selected_lines':[1,2]}})
  self.assertEqual(status,200);self.assertEqual(c['annotations']['selected_text'],'按钮颜色：灰色\n')
  self.assertEqual(self.post('/api/lock',{'path':'example.txt','annotations':{'selected_text':'injected'}})[0],400)
  self.assertEqual(self.post('/api/lock',{'path':'example.txt','annotations':{'selected_lines':[3]}})[0],400)
 def test_stale_visible_file_cannot_be_locked_silently(self):
  _,old=self.post('/api/read',{'path':'example.txt'});self.file.write_text('newer external edit')
  self.assertEqual(self.post('/api/lock',{'path':'example.txt','expected_sha256':old['sha256']})[0],409)
  self.assertFalse(self.app.workspace.contexts)
if __name__=='__main__':unittest.main(verbosity=2)

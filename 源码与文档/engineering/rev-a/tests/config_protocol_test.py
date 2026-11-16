import ctypes,hashlib,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from configure_device import settings_blob,config_packet,decode_reply,private_json
from transactions import Rejected
U8=ctypes.c_uint8;PTR=ctypes.POINTER(U8)
SAVE=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,PTR);FORGET=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p)
class Stage(ctypes.Structure):_fields_=[('bytes',U8*160),('session',ctypes.c_uint32),('transaction',ctypes.c_uint32),('received',ctypes.c_uint16),('active',ctypes.c_bool)]
class IO(ctypes.Structure):_fields_=[('context',ctypes.c_void_p),('save',SAVE),('forget',FORGET)]
sources=[ROOT/'firmware/core'/n for n in ('settings.c','settings.h','protocol.c','protocol.h','controller.h')]
folder=Path.home()/'.cache/ai-key-rev-a/host';folder.mkdir(parents=True,exist_ok=True)
library=folder/('settings-'+hashlib.sha256(b''.join(p.read_bytes() for p in sources)).hexdigest()[:16]+'.dylib')
if not library.exists():subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-dynamiclib',str(sources[0]),str(sources[2]),'-o',str(library)],check=True)
lib=ctypes.CDLL(str(library));lib.ak_settings_process.argtypes=[ctypes.POINTER(Stage),IO,ctypes.c_uint32,ctypes.c_bool,ctypes.c_bool,PTR,ctypes.c_uint,PTR];lib.ak_settings_process.restype=ctypes.c_bool;lib.ak_settings_valid.argtypes=[PTR];lib.ak_settings_valid.restype=ctypes.c_bool
class ConfigurationProtocol(unittest.TestCase):
    def setUp(self):
        self.saved=[];self.forgotten=0;self.storage=True;self.stage=Stage();self.session=0x01020304;self.tx=1234
        def save(_,p):
            if self.storage:self.saved.append(bytes(p[:160]))
            return self.storage
        def forget(_):self.forgotten+=1;return True
        self.save=SAVE(save);self.forget=FORGET(forget);self.io=IO(None,self.save,self.forget)
        self.blob=settings_blob('实验网络','fixture-password','192.168.1.2',8894,bytes(range(32)))
    def exchange(self,op,offset=0,payload=b'',idle=True,session=None):
        packet=config_packet(op,self.session if session is None else session,self.tx,offset,payload);out=(U8*32)();raw=(U8*32).from_buffer_copy(packet)
        self.assertTrue(lib.ak_settings_process(ctypes.byref(self.stage),self.io,self.session,idle,bool(self.saved),raw,32,out))
        return decode_reply(bytes([3])+bytes(out),op,self.tx)
    def upload(self):
        self.assertEqual(self.exchange(1,payload=b'\xa0\0')['code'],0)
        for offset in range(0,160,16):self.assertEqual(self.exchange(2,offset,self.blob[offset:offset+16])['received'],offset+16)
    def test_python_upload_matches_real_c_validator_and_save_callback(self):
        self.assertTrue(lib.ak_settings_valid((U8*160).from_buffer_copy(self.blob)))
        self.upload();response=self.exchange(3,160);self.assertEqual(response['code'],0);self.assertTrue(response['configured']);self.assertEqual(self.saved,[self.blob]);self.assertEqual(bytes(self.stage.bytes),bytes(160))
    def test_missing_chunk_and_duplicate_commit_do_not_persist(self):
        self.exchange(1,payload=b'\xa0\0');self.assertEqual(self.exchange(2,16,self.blob[16:32])['code'],4);self.assertFalse(self.saved)
        self.upload();self.assertEqual(self.exchange(3,160)['code'],0);self.assertEqual(self.exchange(3,160)['code'],4);self.assertEqual(len(self.saved),1)
    def test_busy_or_stale_session_rejects_mutation(self):
        self.assertEqual(self.exchange(1,payload=b'\xa0\0',idle=False)['code'],3);self.assertEqual(self.exchange(1,payload=b'\xa0\0',session=8)['code'],2);self.assertFalse(self.stage.active)
    def test_storage_failure_does_not_report_saved(self):
        self.upload();self.storage=False;r=self.exchange(3,160);self.assertEqual(r['code'],6);self.assertFalse(r['configured']);self.assertFalse(self.saved)
    def test_forget_bond_is_explicit_and_does_not_write_wifi(self):
        self.assertEqual(self.exchange(5)['code'],0);self.assertEqual(self.forgotten,0)
        self.assertEqual(self.exchange(6,idle=False)['code'],3);self.assertEqual(self.forgotten,0)
        self.assertEqual(self.exchange(6)['code'],0);self.assertEqual(self.forgotten,1);self.assertFalse(self.saved)
    def test_private_key_file_permissions_and_malformed_reply(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'config.json';private_json(p,{'fixture':'not-a-real-key'});self.assertEqual(p.stat().st_mode&0o777,0o600)
        with self.assertRaises(Rejected):decode_reply(bytes(33),5,self.tx)
if __name__=='__main__':unittest.main(verbosity=2)

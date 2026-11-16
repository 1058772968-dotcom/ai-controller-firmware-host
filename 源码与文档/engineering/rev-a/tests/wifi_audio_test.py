import ctypes,hashlib,io,secrets,socket,ssl,subprocess,sys,time,unittest,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from wifi_audio import AudioReceiver,frame,receive,HELLO,BEGIN,DATA,END,PING,ACK
from transactions import Rejected
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'firmware/core/audio_wire.c';header=source.with_suffix('.h');folder=Path.home()/'.cache/ai-key-rev-a/host';folder.mkdir(parents=True,exist_ok=True)
library=folder/('audio-wire-'+hashlib.sha256(source.read_bytes()+header.read_bytes()).hexdigest()[:16]+'.dylib')
if not library.exists():subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-dynamiclib',str(source),'-o',str(library)],check=True)
native=ctypes.CDLL(str(library));native.ak_audio_frame.argtypes=[ctypes.POINTER(ctypes.c_uint8),ctypes.c_size_t,ctypes.c_uint8,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.POINTER(ctypes.c_int16),ctypes.c_size_t];native.ak_audio_frame.restype=ctypes.c_size_t
def c_frame(kind,session,stream,sequence,payload=b''):
    output=(ctypes.c_uint8*340)();pcm=(ctypes.c_int16*(len(payload)//2)).from_buffer_copy(payload) if payload else None
    length=native.ak_audio_frame(output,340,kind,session,stream,sequence,pcm,len(payload)//2)
    if not length:raise ValueError('C audio encoder rejected frame')
    return bytes(output[:length])
class WifiAudio(unittest.TestCase):
    def setUp(self):
        self.key=secrets.token_bytes(32);self.r=AudioReceiver({'serial':'fixture','psk_hex':self.key.hex(),'host':'127.0.0.1','port':0});self.clients=[]
    def tearDown(self):
        for c in self.clients:c.close()
        self.r.close()
    def connect(self,key=None):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
        context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_2;context.set_ciphers('PSK-AES128-GCM-SHA256')
        context.set_psk_client_callback(lambda hint:('fixture',self.key if key is None else key))
        raw=socket.create_connection(self.r.address,timeout=2)
        try:c=context.wrap_socket(raw,server_hostname=None)
        except Exception:raw.close();raise
        self.clients.append(c);self.assertEqual(c.cipher()[0],'PSK-AES128-GCM-SHA256');c.sendall(c_frame(HELLO,42,0,0));self.assertEqual(receive(c),(ACK,42,0,0,b''));return c
    def send(self,c,kind,stream,seq,data=b''):
        packet=c_frame(kind,42,stream,seq,data)
        # Exercise fragmented TLS/TCP input rather than assuming one recv/frame.
        c.sendall(packet[:7]);c.sendall(packet[7:]);self.assertEqual(receive(c),(ACK,42,stream,seq,b''))
    def test_real_psk_tls_fragmented_capture_and_wav(self):
        c=self.connect();self.r.arm(42);self.send(c,BEGIN,7,1)
        pcm=b'\x34\x12\xcc\xed'*80;self.send(c,DATA,7,2,pcm);self.send(c,END,7,3)
        with wave.open(io.BytesIO(self.r.finish(42)),'rb') as w:self.assertEqual((w.getnchannels(),w.getframerate(),w.getsampwidth()),(1,16000,2));self.assertEqual(w.readframes(160),pcm)
        self.send(c,PING,0,4)
    def test_wrong_key_cannot_authenticate(self):
        with self.assertRaises(ssl.SSLError):self.connect(secrets.token_bytes(32))
        self.assertFalse(self.r.status()['ready'])
    def test_no_audio_before_grant(self):
        c=self.connect();c.sendall(frame(BEGIN,42,7,1))
        with self.assertRaises((OSError,EOFError)):receive(c)
        self.assertEqual(self.r.status()['bytes'],0)
    def test_reordered_frame_discards_partial_audio(self):
        c=self.connect();self.r.arm(42);self.send(c,BEGIN,7,1);self.send(c,DATA,7,2,b'\x12\x00'*160);c.sendall(frame(END,42,7,4))
        with self.assertRaises((OSError,EOFError)):receive(c)
        with self.assertRaises(Rejected):self.r.finish(42,.1)
        self.assertEqual(self.r.status()['bytes'],0)
    def test_cancel_closes_stream_and_late_audio_is_not_retained(self):
        c=self.connect();self.r.arm(42);self.send(c,BEGIN,7,1);self.send(c,DATA,7,2,b'\x12\x00'*160);self.r.cancel()
        with self.assertRaises((OSError,EOFError)):receive(c)
        self.assertEqual(self.r.status()['bytes'],0)
        with self.assertRaises(Rejected):self.r.finish(42,.1)
    def test_stale_session_cannot_arm_or_complete(self):
        c=self.connect()
        with self.assertRaises(Rejected):self.r.arm(41)
        self.r.arm(42);self.send(c,BEGIN,7,1);c.sendall(frame(END,41,7,2))
        with self.assertRaises((OSError,EOFError)):receive(c)
        with self.assertRaises(Rejected):self.r.finish(42,.1)
if __name__=='__main__':unittest.main(verbosity=2)

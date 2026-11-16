"""Test-only synthesized PDM stand-in, C framing and real loopback TLS."""
import argparse,secrets,socket,ssl,sys,threading,time,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from host_physical_test import WireFixture
from wifi_audio_test import c_frame
from physical_device import PhysicalDevice
from wifi_audio import AudioReceiver,receive,HELLO,BEGIN,DATA,END,PING,ACK
from server import Application,Server
ROOT=Path(__file__).resolve().parents[1]
class PCMFixture:
    def __init__(self,wire,receiver,key):
        self.wire=wire;self.receiver=receiver;self.key=key;self.running=True;self.sent_frames=0;self.streams=0;self.error=None
        with wave.open(str(Path.home()/'.cache/ai-key-rev-a/fixtures/voice-change-color.wav'),'rb') as w:
            assert (w.getnchannels(),w.getframerate(),w.getsampwidth())==(1,16000,2);self.pcm=w.readframes(w.getnframes())
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
    def state(self):
        with self.wire.core.lock:return self.wire.core.snapshot()
    def exchange(self,c,kind,sid,stream,seq,payload=b''):
        c.sendall(c_frame(kind,sid,stream,seq,payload));assert receive(c)==(ACK,sid,stream,seq,b'')
    def loop(self):
        stream_id=0
        while self.running:
            client=None
            try:
                state=self.state();sid=state['session'];ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
                ctx.minimum_version=ctx.maximum_version=ssl.TLSVersion.TLSv1_2;ctx.set_ciphers('PSK-AES128-GCM-SHA256');ctx.set_psk_client_callback(lambda hint:('fixture',self.key))
                raw=socket.create_connection(self.receiver.address,timeout=1);raw.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);client=ctx.wrap_socket(raw,server_hostname=None);self.exchange(client,HELLO,sid,0,0)
                seq=1;active=False;offset=0;last=0
                while self.running:
                    state=self.state()
                    if state['session']!=sid:break
                    allowed=bool(state['flags']&4)
                    if allowed and not active:
                        stream_id+=1;self.exchange(client,BEGIN,sid,stream_id,seq);seq+=1;active=True;offset=0;self.streams+=1
                    if active and not allowed:self.exchange(client,END,sid,stream_id,seq);seq+=1;active=False
                    if active:
                        chunk=self.pcm[offset:offset+320].ljust(320,b'\0');offset+=320
                        self.exchange(client,DATA,sid,stream_id,seq,chunk);seq+=1;self.sent_frames+=1;last=time.monotonic();time.sleep(.01)
                    else:
                        if time.monotonic()-last>.15:self.exchange(client,PING,sid,0,seq);seq+=1;last=time.monotonic()
                        time.sleep(.005)
            except (OSError,EOFError,AssertionError) as e:self.error=type(e).__name__
            finally:
                if client:client.close()
            time.sleep(.05)
    def close(self):self.running=False;self.thread.join(timeout=2)
class WifiFixtureApplication(Application):
    def call(self,path,data):
        if path=='/api/test-fixture/buttons':
            mask=data['mask']
            if type(mask) is not int or not 0<=mask<=15:raise ValueError('bad fixture input')
            self.device.transport.buttons(mask);return {'test_fixture_only':True}
        if path=='/api/test-fixture/audio':return {'sent_frames':self.fixture.sent_frames,'streams':self.fixture.streams,'source_frames':(len(self.fixture.pcm)+319)//320,'error':self.fixture.error,'physical_device':False}
        return super().call(path,data)
    def close(self):self.fixture.close();super().close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workspace',type=Path);p.add_argument('journal',type=Path);a=p.parse_args()
    key=secrets.token_bytes(32);audio=AudioReceiver({'serial':'fixture','psk_hex':key.hex(),'host':'127.0.0.1','port':0})
    io=WireFixture();io.label='ble';device=PhysicalDevice(io);app=WifiFixtureApplication(a.workspace,a.journal,device=device,audio=audio);app.fixture=PCMFixture(io,audio,key)
    server=Server(('127.0.0.1',0),app);print(f'http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()

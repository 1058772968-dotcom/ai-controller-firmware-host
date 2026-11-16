"""Authenticated LAN audio receiver. TLS 1.2 PSK, bounded held-trigger sessions."""
import io,json,secrets,socket,ssl,struct,threading,time,wave
from pathlib import Path
from transactions import Rejected

HEADER=struct.Struct('<4sBBHIII')
HELLO,BEGIN,DATA,END,PING,ACK=range(1,7)
def frame(kind,session,stream,sequence,payload=b''):
    if len(payload)>320:raise ValueError('audio frame too large')
    return HEADER.pack(b'AKAU',1,kind,len(payload),session,stream,sequence)+payload
def receive(sock):
    def exact(n):
        result=bytearray()
        while len(result)<n:
            block=sock.recv(n-len(result))
            if not block:raise EOFError('audio connection closed')
            result.extend(block)
        return bytes(result)
    magic,version,kind,length,session,stream,sequence=HEADER.unpack(exact(HEADER.size))
    if magic!=b'AKAU' or version!=1 or length>320:raise ValueError('invalid audio frame')
    return kind,session,stream,sequence,exact(length)
def load_config(path):
    path=Path(path)
    if path.stat().st_mode&0o077:raise Rejected('连接密钥文件必须仅当前用户可读写：chmod 600 '+str(path))
    data=json.loads(path.read_text());key=bytes.fromhex(data['psk_hex'])
    if data.get('schema')!=1 or data.get('state')!='device_acknowledged_restart_required' or len(key)!=32 or not any(key):raise Rejected('连接配置尚未由设备确认，或密钥格式不正确')
    return data
class AudioReceiver:
    def __init__(self,config,bind=None):
        if not getattr(ssl,'HAS_PSK',False):raise Rejected('Wi-Fi 语音需要支持 TLS PSK 的 Python 3.13 以上运行环境')
        self.identity=config['serial'];self.key=bytes.fromhex(config['psk_hex'])
        if len(self.key)!=32 or not any(self.key):raise ValueError('Invalid PSK')
        self.condition=threading.Condition();self.running=True;self.connection=None;self.session=None;self.ready=False;self.armed=None
        self.stream=None;self.pcm=bytearray();self.completed=None;self.started=0;self.failure=None
        self.context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version=self.context.maximum_version=ssl.TLSVersion.TLSv1_2
        self.context.set_ciphers('PSK-AES128-GCM-SHA256')
        self.context.set_psk_server_callback(lambda identity:self.key if identity==self.identity else b'',identity_hint='AIKEY audio v1')
        self.listener=socket.socket();self.listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.listener.bind(bind or (config['host'],config['port']));self.listener.listen(1);self.listener.settimeout(.2)
        self.address=self.listener.getsockname();self.thread=threading.Thread(target=self._serve,daemon=True);self.thread.start()
    def status(self):
        with self.condition:return {'ready':self.ready,'session':self.session,'capturing':self.stream is not None,'bytes':len(self.pcm),'error':self.failure}
    def arm(self,session):
        with self.condition:
            if not self.ready or self.session!=session:raise Rejected('Wi-Fi 音频通道尚未与当前设备会话连接')
            if self.armed is not None:raise Rejected('已有录音会话')
            self.armed=session;self.stream=None;self.pcm.clear();self.completed=None;self.started=time.monotonic();self.failure=None
    def cancel(self):
        with self.condition:
            active=self.armed is not None or self.stream is not None
            self.armed=None;self.stream=None;self.pcm.clear();self.completed=None
            if active and self.connection:
                try:self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            self.condition.notify_all()
    def finish(self,session,timeout=1):
        with self.condition:
            if session!=self.session:raise Rejected('录音会话已失效')
            self.condition.wait_for(lambda:self.completed is not None or self.failure or not self.running,timeout)
            if self.completed is None:
                self.cancel();raise Rejected('录音没有收到完整结束帧；已丢弃本次录音')
            pcm=self.completed;self.completed=None
        if not pcm:raise Rejected('没有音频样本')
        out=io.BytesIO()
        with wave.open(out,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(pcm)
        return out.getvalue()
    def _serve(self):
        while self.running:
            try:raw,_=self.listener.accept()
            except socket.timeout:continue
            except OSError:break
            raw.settimeout(2);raw.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            client=None
            try:
                client=self.context.wrap_socket(raw,server_side=True);client.settimeout(.8)
                kind,session,stream,sequence,payload=receive(client)
                if (kind,stream,sequence,payload)!=(HELLO,0,0,b'') or not session:raise ValueError('invalid audio hello')
                with self.condition:
                    self.connection=client;self.session=session;self.ready=True;self.failure=None;self.armed=None;self.stream=None;self.pcm.clear();self.completed=None
                    self.condition.notify_all()
                client.sendall(frame(ACK,session,0,0));expected=1;used_streams=set()
                while self.running:
                    kind,sid,stream,sequence,payload=receive(client)
                    if sid!=session or sequence!=expected:raise ValueError('audio session/sequence mismatch')
                    expected+=1
                    if expected>0xffffffff:raise ValueError('audio sequence exhausted')
                    with self.condition:
                        if self.armed is not None and time.monotonic()-self.started>60:raise ValueError('audio time limit exceeded')
                        if kind==PING:
                            if stream or payload:raise ValueError('invalid audio ping')
                        elif kind==BEGIN:
                            if not stream or stream in used_streams or payload or self.armed!=session or self.stream is not None:raise ValueError('recording not granted')
                            if len(used_streams)>=4096:raise ValueError('audio session limit')
                            self.stream=stream;used_streams.add(stream)
                        elif kind==DATA:
                            if self.armed!=session or self.stream is None or stream!=self.stream or not payload or len(payload)%2:raise ValueError('audio outside active grant')
                            if len(self.pcm)+len(payload)>60*32000:raise ValueError('audio size limit exceeded')
                            self.pcm.extend(payload)
                        elif kind==END:
                            if self.armed!=session or self.stream is None or stream!=self.stream or payload:raise ValueError('invalid audio end')
                            self.completed=bytes(self.pcm);self.pcm.clear();self.stream=None;self.armed=None;self.condition.notify_all()
                        else:raise ValueError('invalid audio message type')
                    client.sendall(frame(ACK,session,stream,sequence))
            except (OSError,EOFError,ValueError) as e:
                with self.condition:
                    self.failure=type(e).__name__;self.ready=False;self.armed=None;self.stream=None;self.pcm.clear();self.completed=None;self.condition.notify_all()
            finally:
                if client:client.close()
                else:raw.close()
                with self.condition:self.connection=None;self.ready=False
    def close(self):
        self.running=False;self.cancel();self.listener.close()
        with self.condition:
            if self.connection:
                try:self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
        self.thread.join(timeout=3)

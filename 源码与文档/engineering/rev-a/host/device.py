"""Shared 32-byte firmware protocol and explicit native-core simulation transport."""
import ctypes,hashlib,secrets,struct,subprocess,threading,time
from pathlib import Path
from transactions import Rejected

ROOT=Path(__file__).resolve().parents[1]
def crc16(data):
    crc=0xffff
    for byte in data:
        crc^=byte<<8
        for _ in range(8):crc=((crc<<1)^0x1021 if crc&0x8000 else crc<<1)&0xffff
    return crc
def command_packet(session,sequence,command,value=0):
    if command not in range(1,9) or value not in (0,1):raise Rejected('invalid device command')
    out=bytearray(32);out[0]=1;out[1]=command
    struct.pack_into('<II',out,4,session,sequence);out[16]=value
    struct.pack_into('<H',out,30,crc16(out[:30]));return bytes(out)
def decode(packet):
    if len(packet)!=32 or packet[0]!=1 or struct.unpack_from('<H',packet,30)[0]!=crc16(packet[:30]):
        raise Rejected('invalid firmware packet')
    if packet[1] not in (*range(1,10),0x80,0x81) or packet[2]>1:raise Rejected('unknown firmware packet type')
    session,seq,now=struct.unpack_from('<III',packet,4)
    result={'type':packet[1],'owner':packet[2],'buttons':packet[3],'session':session,'sequence':seq,
            'time_ms':now,'flags':packet[16],'value':packet[17],'hid_buttons':packet[18],'faults':packet[19],
            'command_sequence':struct.unpack_from('<I',packet,24)[0]}
    if packet[1]==0x81:result['dx'],result['dy']=struct.unpack_from('<hh',packet,20)
    if packet[1]==0x80:
        result['battery_mv'],result['soc_q8']=struct.unpack_from('<HH',packet,20)
        result['battery_valid']=bool(packet[28]&1)
    return result

class SimulatedDevice:
    """Actual C controller/protocol, virtual button inputs; never physical USB."""
    def __init__(self):
        sources=[ROOT/'host/controller_sim.c',ROOT/'firmware/core/controller.c',ROOT/'firmware/core/protocol.c']
        headers=list((ROOT/'firmware/core').glob('*.h'))
        key=hashlib.sha256(b''.join(p.read_bytes() for p in sources+sorted(headers))).hexdigest()[:16]
        folder=Path.home()/'.cache/ai-key-rev-a/host';folder.mkdir(parents=True,exist_ok=True)
        library=folder/f'controller-{key}.dylib'
        if not library.exists():
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-O2','-dynamiclib',
                '-I'+str(ROOT/'firmware/core'),*map(str,sources),'-o',str(library)],check=True,capture_output=True)
        self.lib=ctypes.CDLL(str(library));u32=ctypes.c_uint32;u8=ctypes.c_uint8
        self.lib.ak_sim_init.argtypes=[u32,u8,u32];self.lib.ak_sim_poll.argtypes=[u8,u32]
        self.lib.ak_sim_command.argtypes=[ctypes.POINTER(u8),u32]
        self.lib.ak_sim_pop.argtypes=[ctypes.POINTER(u8)];self.lib.ak_sim_state.argtypes=[ctypes.POINTER(u8)]
        self.lib.ak_sim_disconnect.argtypes=[u32]
        self.lock=threading.RLock();self.start=time.monotonic();self.mask=0;self.sequence=0;self.running=True
        self.last_ui=0;self.last_keepalive=0;self.history=[];self.cursor=0;self.active=False
        self.lib.ak_sim_init(secrets.randbits(32) or 1,0,0)
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
    def now(self):return int((time.monotonic()-self.start)*1000)&0xffffffff
    def snapshot(self):
        data=(ctypes.c_uint8*32)();self.lib.ak_sim_state(data);return decode(bytes(data))
    def drain(self):
        data=(ctypes.c_uint8*32)()
        while self.lib.ak_sim_pop(data):
            self.cursor+=1;self.history.append(dict(decode(bytes(data)),cursor=self.cursor))
        self.history=self.history[-512:]
    def command(self,command,value=0):
        with self.lock:
            self.sequence=(self.sequence+1)&0xffffffff
            packet=command_packet(self.snapshot()['session'],self.sequence,command,value)
            data=(ctypes.c_uint8*32).from_buffer_copy(packet)
            result=self.lib.ak_sim_command(data,self.now());self.drain()
            if result!=0:raise Rejected('firmware command refused: '+str(result))
            return self.snapshot()
    def pulse(self,cursor=None):
        with self.lock:
            self.last_ui=time.monotonic()
            if not self.active:self.command(1);self.active=True
            state=self.snapshot()
            return {'transport':'native firmware core simulation','physical_device':False,'state':state,
                    'events':[] if cursor is None else [event for event in self.history if event['cursor']>cursor],'cursor':self.cursor}
    def buttons(self,mask):
        if type(mask) is not int or mask<0 or mask>15:raise Rejected('invalid button mask')
        with self.lock:self.mask=mask
    def disconnect(self):
        with self.lock:
            self.lib.ak_sim_disconnect(self.now());self.drain();self.active=False;self.mask=0
    def loop(self):
        while self.running:
            with self.lock:
                self.lib.ak_sim_poll(self.mask,self.now());self.drain()
                if self.active and time.monotonic()-self.last_ui>.55:self.disconnect()
                elif self.active and time.monotonic()-self.last_keepalive>.2:
                    try:self.command(3)
                    except Rejected:self.disconnect()
                    self.last_keepalive=time.monotonic()
            time.sleep(.005)
    def close(self):
        self.running=False;self.thread.join(timeout=1);self.disconnect()

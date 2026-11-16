"""ACK-driven companion control over actual USB/BLE adapters."""
import threading,time
from device import command_packet,decode
from transactions import Rejected

class PhysicalDevice:
    def __init__(self,transport,initial_timeout=3,ack_timeout=.5):
        self.transport=transport;self.physical_device=transport.physical_device
        self.mode=transport.label;self.condition=threading.Condition();self.commands=threading.RLock()
        self.running=True;self.active=False;self.error=None;self.state=None;self.sequence=0;self.ack=None
        self.history=[];self.cursor=0;self.last_packet=0;self.last_ui=0;self.last_keepalive=0;self.ack_timeout=ack_timeout
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        try:
            with self.condition:
                if not self.condition.wait_for(lambda:self.state is not None or self.error,initial_timeout):raise Rejected('设备没有返回有效状态')
                self._check()
            self.heartbeat=threading.Thread(target=self._heartbeat,daemon=True);self.heartbeat.start()
        except Exception:
            self.close();raise
    def _check(self):
        if self.error or not self.running:raise Rejected(str(self.error or '设备连接已关闭'))
    def _read(self):
        while self.running:
            try:
                raw=self.transport.read(.03)
                if raw is None:continue
                packet=decode(raw)
                with self.condition:
                    if self.state is None or packet['session']!=self.state['session']:
                        self.active=False;self.history.clear();self.ack=None
                        self.sequence=packet['command_sequence']
                    self.state=packet;self.last_packet=time.monotonic()
                    # Periodic status is a snapshot, not an input event.
                    if packet['type']!=0x80:
                        self.cursor+=1;self.history.append(dict(packet,cursor=self.cursor));self.history=self.history[-512:]
                    if packet['type']==8:self.ack=packet.copy()
                    self.condition.notify_all()
            except Exception as e:
                with self.condition:self.error=e;self.active=False;self.condition.notify_all()
                return
    def command(self,command,value=0):
        with self.commands:
            with self.condition:
                self._check();session=self.state['session'];self.sequence=(self.sequence+1)&0xffffffff;sequence=self.sequence
                packet=command_packet(session,sequence,command,value);self.ack=None
            try:self.transport.write(packet)
            except Exception as e:
                with self.condition:self.error=e;self.active=False;self.condition.notify_all()
                raise Rejected('设备写入失败') from e
            with self.condition:
                received=self.condition.wait_for(lambda:self.error or self.state['session']!=session or
                    (self.ack is not None and self.ack['session']==session and self.ack['command_sequence']==sequence),self.ack_timeout)
                self._check()
                if self.state['session']!=session:raise Rejected('设备会话已改变；旧命令已撤回')
                if not received:
                    self.active=False;raise Rejected('固件 ACK 超时；未确认执行，等待租约释放')
                if self.ack['value']!=0:raise Rejected('固件拒绝命令：'+str(self.ack['value']))
                if command==1:self.active=True
                return self.state.copy()
    def pulse(self,cursor=None):
        with self.commands:
            with self.condition:
                self._check();self.last_ui=time.monotonic()
                if time.monotonic()-self.last_packet>.5:raise Rejected('设备状态超时')
                active=self.active
            if not active:self.command(1)
            with self.condition:
                events=[] if cursor is None else [p.copy() for p in self.history if p['cursor']>cursor]
                if cursor is not None and self.history and cursor<self.history[0]['cursor']-1:
                    self.active=False;raise Rejected('设备事件积压，必须重新连接以免重放输入')
                return {'transport':self.mode,'physical_device':self.physical_device,'state':self.state.copy(),'events':events,'cursor':self.cursor}
    def buttons(self,mask):raise Rejected('实物模式仅接受设备实体按键，不能注入模拟按键')
    def disconnect(self):
        with self.commands:
            with self.condition:available=self.running and self.state is not None and self.error is None
            if available:
                try:self.command(4)
                except Rejected:pass
            with self.condition:self.active=False;self.history.clear();self.last_ui=0
    def _heartbeat(self):
        while self.running:
            with self.condition:active=self.active;stale=time.monotonic()-self.last_ui>.55;due=time.monotonic()-self.last_keepalive>.2
            if active:
                if stale:self.disconnect()
                elif due:
                    try:self.command(3)
                    except Rejected:
                        with self.condition:self.active=False
                    self.last_keepalive=time.monotonic()
            time.sleep(.02)
    def close(self):
        self.disconnect();self.running=False
        self.transport.close()
        if hasattr(self,'reader'):self.reader.join(timeout=1)
        if hasattr(self,'heartbeat'):self.heartbeat.join(timeout=1)

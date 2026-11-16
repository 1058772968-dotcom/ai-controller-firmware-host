"""Real C firmware through an injected I/O boundary, plus native adapter API tests."""
import asyncio,ctypes,queue,sys,threading,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from device import SimulatedDevice,decode
from physical_device import PhysicalDevice
from transports import USBTransport,BLETransport,SERVICE,CONTROL
from transactions import Rejected

class WireFixture:
    label='C wire fixture';physical_device=False
    def __init__(self):
        self.core=SimulatedDevice();self.core.running=False;self.core.thread.join()
        self.queue=queue.Queue();self.running=True;self.drop_ack=False;self.hold_ack=False;self.acks=[]
        self.last=0;self.worker=threading.Thread(target=self.loop,daemon=True);self.worker.start()
    def drain(self):
        data=(ctypes.c_uint8*32)()
        while self.core.lib.ak_sim_pop(data):
            packet=bytes(data)
            if packet[1]==8:
                if self.drop_ack:continue
                if self.hold_ack:self.acks.append(packet);continue
            self.queue.put(packet)
    def loop(self):
        while self.running:
            with self.core.lock:
                self.core.lib.ak_sim_poll(self.core.mask,self.core.now());self.drain()
                if time.monotonic()-self.last>.08:
                    data=(ctypes.c_uint8*32)();self.core.lib.ak_sim_state(data);self.queue.put(bytes(data));self.last=time.monotonic()
            time.sleep(.003)
    def read(self,timeout):
        try:return self.queue.get(timeout=timeout)
        except queue.Empty:return None
    def write(self,packet):
        with self.core.lock:
            data=(ctypes.c_uint8*32).from_buffer_copy(packet);self.core.lib.ak_sim_command(data,self.core.now());self.drain()
    def buttons(self,mask):
        with self.core.lock:self.core.mask=mask
    def close(self):self.running=False;self.worker.join(timeout=1);self.core.close()

class PhysicalControl(unittest.TestCase):
    def setUp(self):self.io=WireFixture();self.d=PhysicalDevice(self.io,ack_timeout=.22);self.d.pulse()
    def tearDown(self):self.d.close()
    def wait(self,predicate,seconds=.4):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.004)
        self.fail('condition timed out')
    def test_ack_ownership_record_cut_and_no_injected_buttons(self):
        self.assertEqual(self.d.command(2)['owner'],1)
        self.io.buttons(4);self.wait(lambda:self.d.state['buttons']==4)
        self.assertTrue(self.d.command(5,1)['flags']&2)
        self.io.buttons(0);self.wait(lambda:not self.d.state['flags']&2)
        self.assertFalse(self.d.pulse()['physical_device'])
        with self.assertRaises(Rejected):self.d.buttons(1)
    def test_rejection_is_not_transport_success(self):
        self.io.buttons(1);self.wait(lambda:self.d.state['buttons']==1)
        with self.assertRaisesRegex(Rejected,'拒绝'):self.d.command(2)
        self.assertEqual(self.d.state['owner'],0)
    def test_state_receipt_without_matching_ack_is_not_success(self):
        self.io.drop_ack=True
        with self.assertRaisesRegex(Rejected,'ACK 超时'):self.d.command(2)
        self.assertFalse(self.d.active)
        self.io.drop_ack=False
        self.wait(lambda:self.d.state['owner']==0,1.1)
    def test_ui_loss_releases_recording_and_next_connection_has_no_replay(self):
        self.d.command(2);self.io.buttons(4);self.wait(lambda:self.d.state['buttons']==4);self.d.command(5,1)
        self.wait(lambda:not self.d.active,.9);self.wait(lambda:not self.d.state['flags']&2)
        fresh=self.d.pulse();self.assertEqual(fresh['events'],[]);self.assertEqual(fresh['state']['owner'],0)
        with self.assertRaises(Rejected):self.d.command(5,1)
    def test_session_change_invalidates_waiting_command(self):
        self.io.hold_ack=True
        def reset():
            time.sleep(.04)
            with self.io.core.lock:self.io.core.lib.ak_sim_disconnect(self.io.core.now())
        t=threading.Thread(target=reset);t.start()
        with self.assertRaisesRegex(Rejected,'会话已改变'):self.d.command(2)
        t.join();self.io.hold_ack=False
        self.assertFalse(self.d.active)
        # Late ACK cannot make an already failed request succeed.
        self.assertTrue(self.io.acks)
    def test_corrupt_packet_fails_closed(self):
        self.io.queue.put(bytes(32));self.wait(lambda:self.d.error is not None)
        with self.assertRaises(Rejected):self.d.pulse()

class FakeHID:
    def __init__(self):self.written=[];self.next=[];self.closed=False;self.short=False
    def enumerate(self,vid,pid):return [{'usage_page':0xff00,'usage':1,'serial_number':'fixture','path':b'fixture'}]
    def device(self):return self
    def open_path(self,p):self.path=p
    def read(self,n,t):return self.next
    def write(self,p):self.written.append(p);return len(p)-(1 if self.short else 0)
    def close(self):self.closed=True
class FakeBLE:
    def __init__(self,address,**kwargs):self.address=address;self.services=self;self.mtu_size=64;self.calls=[]
    async def connect(self):self.calls.append('connect')
    def get_service(self,uuid):return uuid==SERVICE
    async def read_gatt_char(self,uuid):self.calls.append(('read',uuid));return bytes(32)
    async def start_notify(self,uuid,callback):self.calls.append(('notify',uuid));self.callback=callback;callback(None,bytes([1])*32)
    async def write_gatt_char(self,uuid,packet,response):self.calls.append(('write',uuid,packet,response))
    async def disconnect(self):self.calls.append('disconnect')
class AdapterBoundary(unittest.TestCase):
    def test_usb_report_id_and_selection_and_short_write(self):
        fake=FakeHID();usb=USBTransport('fixture',fake)
        usb.write(bytes(32));self.assertEqual(fake.written[-1],bytes([2])+bytes(32))
        fake.next=bytes([1])+bytes(5);self.assertIsNone(usb.read())
        fake.next=bytes([2])+bytes(32);self.assertEqual(usb.read(),bytes(32))
        fake.short=True
        with self.assertRaises(OSError):usb.write(bytes(32))
        usb.close();self.assertTrue(fake.closed)
        with self.assertRaises(Rejected):USBTransport('wrong',FakeHID())
    def test_ble_subscribe_then_notification_and_write_response(self):
        ble=BLETransport('fixture',FakeBLE)
        self.assertEqual(ble.read(),bytes([1])*32) # pre-subscription read was discarded
        ble.write(bytes(32));self.assertEqual(ble.client.calls[-1],('write',CONTROL,bytes(32),True))
        ble.close();self.assertEqual(ble.client.calls[-1],'disconnect')
    def test_ble_rejects_small_mtu(self):
        def factory(*a,**k):c=FakeBLE(*a,**k);c.mtu_size=23;return c
        with self.assertRaisesRegex(OSError,'MTU'):BLETransport('fixture',factory)

if __name__=='__main__':unittest.main(verbosity=2)

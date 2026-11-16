"""Physical I/O adapters. Opening one never falls back to simulated hardware."""
import asyncio,concurrent.futures,ctypes,queue,sys,threading
from transactions import Rejected

CONTROL='98f32a0e-79bc-4d5b-9f84-dcce6f807292'
SERVICE='98f32a0e-79bc-4d5b-9f84-dcce6f807291'

def configure_hid_shared(hid_module):
    if sys.platform!='darwin':return
    # Use the exported HIDAPI Darwin API in the same loaded extension. The
    # companion must share the HID interface with the system mouse driver.
    try:
        library=ctypes.CDLL(hid_module.__file__)
        setter=library.hid_darwin_set_open_exclusive;setter.argtypes=[ctypes.c_int];setter.restype=None
        getter=library.hid_darwin_get_open_exclusive;getter.argtypes=[];getter.restype=ctypes.c_int
        setter(0)
        if getter()!=0:raise RuntimeError('exclusive open remains enabled')
    except (AttributeError,OSError,RuntimeError) as e:raise Rejected('当前 HIDAPI 不能保证与系统鼠标共享接口') from e

class USBTransport:
    label='usb';physical_device=True
    def __init__(self,serial=None,hid_module=None):
        if hid_module is None:
            try:import hid as hid_module
            except ImportError as e:raise Rejected('USB 依赖未安装，请运行 tools/setup_host_transports.py') from e
            configure_hid_shared(hid_module)
        candidates=[d for d in hid_module.enumerate(0xcafe,0x4031)
                    if d.get('usage_page')==0xff00 and d.get('usage')==1 and (serial is None or d.get('serial_number')==serial)]
        if len(candidates)!=1:raise Rejected('未找到唯一 AI KEY USB 控制接口；连接设备或使用 --usb-serial 指定序列号')
        self.device=hid_module.device();self.device.open_path(candidates[0]['path'])
        self.serial=candidates[0].get('serial_number');self.lock=threading.Lock();self.closed=False
    def read(self,timeout=.05):
        with self.lock:
            if self.closed:raise OSError('USB closed')
            raw=bytes(self.device.read(64,max(1,int(timeout*1000))))
        if not raw:return None
        # HIDAPI supplies the numbered-report prefix. Never treat mouse bytes
        # or a prefix-free packet as a control report.
        if raw[0]!=2:return None
        if len(raw)!=33:raise OSError('USB control report length mismatch')
        return raw[1:]
    def write(self,packet):
        with self.lock:
            if self.closed:raise OSError('USB closed')
            if self.device.write(bytes([2])+packet)!=33:raise OSError('USB short write')
    def close(self):
        with self.lock:
            if not self.closed:self.closed=True;self.device.close()

class BLETransport:
    label='ble';physical_device=True
    def __init__(self,address,client_factory=None,timeout=45):
        if client_factory is None:
            try:from bleak import BleakClient as client_factory
            except ImportError as e:raise Rejected('BLE 依赖未安装，请运行 tools/setup_host_transports.py') from e
        self.address=address;self.queue=queue.Queue(maxsize=512);self.error=None;self.closed=False
        self.loop=asyncio.new_event_loop();self.thread=threading.Thread(target=self.loop.run_forever,daemon=True);self.thread.start()
        self.client=client_factory(address,disconnected_callback=self._disconnected,timeout=timeout)
        try:self._call(self._connect(),timeout+5)
        except Exception:
            self.close();raise
    def _disconnected(self,client):
        if not self.closed:self.error=OSError('BLE disconnected')
    def _notify(self,sender,data):
        if len(data)!=32:self.error=OSError('BLE control notification length mismatch');return
        try:self.queue.put_nowait(bytes(data))
        except queue.Full:self.error=OSError('BLE notification queue overflow')
    def _call(self,coroutine,timeout=3):
        future=asyncio.run_coroutine_threadsafe(coroutine,self.loop)
        try:return future.result(timeout)
        except concurrent.futures.TimeoutError as e:
            future.cancel();raise OSError('BLE operation timed out') from e
    async def _connect(self):
        await self.client.connect()
        if not self.client.services.get_service(SERVICE):raise OSError('AI KEY service missing')
        # On macOS encrypted access invokes OS pairing. Do not call pair(),
        # which CoreBluetooth does not implement. No repeated reads after
        # notify subscription: CoreBluetooth uses the same callback for both.
        initial=bytes(await self.client.read_gatt_char(CONTROL))
        if len(initial)!=32:raise OSError('BLE initial state length mismatch')
        if self.client.mtu_size<35:raise OSError('BLE ATT MTU below 35')
        await self.client.start_notify(CONTROL,self._notify)
        # Subscription rotates firmware session. Discard pre-subscription
        # state and wait for the first actual notification from the new session.
    def read(self,timeout=.05):
        if self.closed or self.error:raise OSError(str(self.error or 'BLE closed'))
        try:return self.queue.get(timeout=timeout)
        except queue.Empty:return None
    def write(self,packet):
        if self.closed or self.error:raise OSError(str(self.error or 'BLE closed'))
        self._call(self.client.write_gatt_char(CONTROL,packet,response=True))
    def close(self):
        if self.closed:return
        self.closed=True
        try:self._call(self.client.disconnect(),3)
        except Exception:pass
        self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join(timeout=4)
        if not self.thread.is_alive():self.loop.close()

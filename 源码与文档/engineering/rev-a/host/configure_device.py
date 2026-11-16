#!/usr/bin/env python3
"""USB-only configuration with acknowledged chunks; credentials never logged."""
import argparse,getpass,ipaddress,json,os,secrets,struct,tempfile,time
from pathlib import Path
from device import crc16
from transactions import Rejected

def settings_blob(ssid,password,host,port,key):
    ssid=ssid.encode('utf-8');password=password.encode('ascii');ip=ipaddress.IPv4Address(host)
    if not 1<=len(ssid)<=32 or b'\0' in ssid:raise ValueError('SSID must be 1–32 UTF-8 bytes')
    if not 8<=len(password)<=63 or any(b<32 or b>126 for b in password):raise ValueError('WPA2/WPA3 transition password must be 8–63 printable ASCII bytes')
    if ip.is_multicast or int(ip)>>24==0 or int(ip)&255==255:raise ValueError('Host must be a unicast IPv4 address')
    if not 1024<=port<=65535 or len(key)!=32 or not any(key):raise ValueError('Invalid port or connection key')
    out=bytearray(160);out[0]=1;out[1]=len(ssid);out[2]=len(password);out[4:4+len(ssid)]=ssid;out[36:36+len(password)]=password
    host=str(ip).encode();out[100:100+len(host)]=host;struct.pack_into('<H',out,116,port);out[118:150]=key;return bytes(out)
def config_packet(op,session,transaction,offset=0,payload=b''):
    if len(payload)>16:raise ValueError('Configuration chunk too long')
    data=bytearray(32);struct.pack_into('<BBHII',data,0,1,op,offset,session,transaction);data[12:12+len(payload)]=payload
    struct.pack_into('<H',data,30,crc16(data[:30]));return bytes(data)
def decode_reply(raw,op,transaction):
    if len(raw)!=33 or raw[0]!=3:raise Rejected('Configuration report ID/size mismatch')
    data=raw[1:]
    if data[0]!=1 or data[1]!=(op|0x80) or struct.unpack_from('<I',data,8)[0]!=transaction or crc16(data[:30])!=struct.unpack_from('<H',data,30)[0]:raise Rejected('Configuration reply mismatch')
    return {'code':data[2],'configured':bool(data[3]),'session':struct.unpack_from('<I',data,4)[0],'received':struct.unpack_from('<H',data,12)[0]}
class ConfigUSB:
    def __init__(self,serial=None):
        import hid
        from transports import configure_hid_shared
        configure_hid_shared(hid)
        matches=[d for d in hid.enumerate(0xcafe,0x4031) if d.get('usage_page')==0xff00 and d.get('usage')==3 and (serial is None or d.get('serial_number')==serial)]
        if len(matches)!=1:raise Rejected('未找到唯一 USB 配置接口；请连接含报告 ID 3 的固件并指定正确序列号')
        self.serial=matches[0]['serial_number'];self.device=hid.device();self.device.open_path(matches[0]['path']);self.session=0
    def exchange(self,op,tx,offset=0,payload=b'',discover=False):
        packet=config_packet(op,self.session,tx,offset,payload)
        if self.device.write(bytes([3])+packet)!=33:raise Rejected('配置写入不完整')
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            raw=bytes(self.device.read(64,100))
            if not raw or raw[0]!=3:continue
            response=decode_reply(raw,op,tx)
            if discover:self.session=response['session']
            elif response['session']!=self.session:raise Rejected('设备重置，配置未继续')
            if response['code'] and not (discover and response['code']==2):raise Rejected('固件拒绝配置，状态码 '+str(response['code']))
            return response
        raise Rejected('没有配置 ACK；不认为已经保存')
    def close(self):self.device.close()
def private_json(path,data):
    path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.aikey-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(data,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
def main():
    p=argparse.ArgumentParser(description='停止工作台、松开全部按键后，通过 USB 配置设备。Wi-Fi 设置在下次复位生效。')
    p.add_argument('--serial');p.add_argument('--forget-bond',action='store_true');p.add_argument('--ssid');p.add_argument('--host');p.add_argument('--port',type=int,default=8894);p.add_argument('--output',type=Path)
    a=p.parse_args();device=None
    try:
        if not a.forget_bond and (not a.ssid or not a.host):p.error('Wi-Fi 配置需要 --ssid 和电脑局域网 IPv4 --host')
        device=ConfigUSB(a.serial);tx=secrets.randbits(32) or 1;device.exchange(5,tx,discover=True)
        if a.forget_bond:
            device.exchange(6,tx);print('设备确认已删除 BLE 绑定。可重新配对；Wi-Fi 设置未修改。');return
        password=getpass.getpass('Wi-Fi 密码（不回显、不写入电脑配置文件）：');key=secrets.token_bytes(32)
        blob=settings_blob(a.ssid,password,a.host,a.port,key);password=None
        output=a.output or Path.home()/'.config/aikey'/f'{device.serial}.json'
        if output.exists():raise Rejected('连接配置文件已存在；请备份后移走旧文件，或用 --output 指定新文件。')
        # Preserve the new key before device commit so a host disk error cannot
        # strand an otherwise successfully configured controller.
        private_json(output,{'schema':1,'serial':device.serial,'host':a.host,'port':a.port,'psk_hex':key.hex(),'state':'pending_device_ack'})
        device.exchange(1,tx,payload=struct.pack('<H',160))
        for offset in range(0,160,16):
            response=device.exchange(2,tx,offset,blob[offset:offset+16])
            if response['received']!=offset+16:raise Rejected('设备接收偏移与发送不同')
        device.exchange(3,tx,160)
        private_json(output,{'schema':1,'serial':device.serial,'host':a.host,'port':a.port,'psk_hex':key.hex(),'state':'device_acknowledged_restart_required'})
        print('设备确认已保存。按 EN 复位或重新上电后应用。电脑连接配置：'+str(output))
    except (Rejected,ValueError,OSError,ImportError) as e:p.exit(2,str(e)+'\n')
    finally:
        if device:device.close()
if __name__=='__main__':main()

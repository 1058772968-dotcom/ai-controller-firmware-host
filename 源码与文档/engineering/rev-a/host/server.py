#!/usr/bin/env python3
"""Loopback-only AI KEY workbench with actual local inference and file receipts."""
import argparse,base64,dataclasses,difflib,json,math,mimetypes,os,secrets,socketserver,threading,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from ai_runtime import LocalAI
from transactions import Workspace,Conflict,Rejected,digest
from local_adapter import replace_text
from device import SimulatedDevice

ROOT=Path(__file__).resolve().parents[1];STATIC=ROOT/'host/web'
class Application:
    def __init__(self,workspace,journal,simulation=False,device=None,audio=None):
        if simulation and device is not None:raise ValueError('Select one device mode')
        self.workspace=Workspace(workspace,journal);self.ai=LocalAI()
        self.device=SimulatedDevice() if simulation else device
        self.device_mode='native-core-simulation' if simulation else device.mode if device else 'disconnected'
        self.audio=audio
        self.token=secrets.token_urlsafe(32);self.inference_slots=threading.BoundedSemaphore(1)
        self.context_info={}
    def files(self):
        result=[]
        for directory,dirs,files in os.walk(self.workspace.root,followlinks=False):
            dirs[:]=[d for d in dirs if not d.startswith('.') and not (Path(directory)/d).is_symlink()]
            for name in sorted(files):
                path=Path(directory)/name
                if name.startswith('.') or path.suffix.lower() not in {'.txt','.md','.py','.js','.ts','.json','.html','.css','.c','.h'}:continue
                if path.is_symlink() or path.stat().st_size>1024*1024:continue
                result.append(str(path.relative_to(self.workspace.root)))
                if len(result)>=200:return result
        return result
    def call(self,path,data):
        w=self.workspace
        if path=='/api/status':
            return {'workspace':str(w.root),'files':self.files(),'recovery':w.pending_recovery(),
                    'device_mode':self.device_mode,'physical_device':bool(getattr(self.device,'physical_device',False)),
                    'wifi_audio':self.audio.status() if self.audio else None,
                    'models':{'asr':'whisper small multilingual','text':'Qwen2.5 1.5B Instruct Q4_K_M'},'local_only':True}
        if path=='/api/read':
            _,raw,text=w.read(data.get('path'));return {'text':text,'sha256':digest(raw)}
        if path=='/api/lock':
            info=data.get('annotations',{})
            if not isinstance(info,dict) or set(info)-{'regions','arrows','selected_lines'} or len(json.dumps(info))>20000:raise Rejected('标注上下文无效或过大')
            selected=info.get('selected_lines',[])
            if not isinstance(selected,list) or len(selected)>200 or any(type(i) is not int or i<1 for i in selected):raise Rejected('标注行号无效')
            for key in ('regions','arrows'):
                items=info.get(key,[])
                if not isinstance(items,list) or len(items)>32:raise Rejected('标注数量超出上限')
                for item in items:
                    fields=('x','y','w','h') if key=='regions' else ('x1','y1','x2','y2')
                    if not isinstance(item,dict) or set(item)!=set(fields) or any(type(item[k]) not in (int,float) or not math.isfinite(item[k]) or abs(item[k])>1e6 for k in fields):raise Rejected('标注坐标无效')
            w.cancel();context=w.lock(data.get('path'))
            if data.get('expected_sha256') is not None and data['expected_sha256']!=context.sha256:
                w.cancel();raise Conflict('文件内容已与当前视图不同，请重新读取后锁定')
            lines=context.text.split('\n')
            if any(i>len(lines) for i in selected):w.cancel();raise Rejected('标注已超出文件范围')
            frozen=json.loads(json.dumps(info));frozen['selected_text']='\n'.join(lines[i-1] for i in sorted(set(selected)))
            self.context_info={context.id:frozen};return dict(dataclasses.asdict(context),annotations=frozen)
        if path=='/api/cancel':
            w.cancel();self.context_info.clear()
            if self.audio:self.audio.cancel()
            if self.device:self.device.disconnect()
            return {'cancelled':True}
        if path=='/api/asr':
            context_id=data.get('context_id')
            with w._mutex:
                if context_id not in w.contexts:raise Rejected('请先锁定目标')
                context=w.contexts[context_id]
            try:audio=base64.b64decode(data.get('wav_base64',''),validate=True)
            except (ValueError,TypeError):raise Rejected('音频编码无效')
            if not self.inference_slots.acquire(blocking=False):raise Rejected('本地推理正在进行，请稍后重试')
            try:result=self.ai.transcribe(audio)
            finally:self.inference_slots.release()
            with w._mutex:
                if w.contexts.get(context_id) is not context:raise Rejected('录音已取消；忽略迟到的识别结果')
            return result
        if path=='/api/send':
            if data.get('confirmed') is not True:raise Rejected('需要独立确认发送')
            adapter_name=data.get('adapter','local-ai')
            if adapter_name not in ('local-ai','exact-replace'):raise Rejected('未知适配器')
            if not self.inference_slots.acquire(blocking=False):raise Rejected('本地推理正在进行，请稍后重试')
            info=self.context_info.get(data.get('context_id'),{})
            adapter=(lambda context,instruction:self.ai.propose(context,instruction,info)) if adapter_name=='local-ai' else replace_text
            try:proposal=w.confirm_send(data.get('context_id'),data.get('instruction'),adapter)
            finally:self.inference_slots.release()
            before=w.contexts[proposal['context_id']].text
            proposal['before_text']=before
            proposal['diff']=''.join(difflib.unified_diff(before.splitlines(True),proposal['new_text'].splitlines(True),fromfile=proposal['path']+' (before)',tofile=proposal['path']+' (proposal)'))
            return proposal
        if path=='/api/apply':
            if data.get('confirmed') is not True:raise Rejected('需要独立确认应用')
            return w.confirm_apply(data.get('proposal_id'))
        if path=='/api/undo':
            if data.get('confirmed') is not True:raise Rejected('需要确认撤销')
            return w.confirm_undo(data.get('receipt_id'))
        if path=='/api/audio/finish':
            if not self.audio or self.device_mode!='ble':raise Rejected('当前未配置 BLE/Wi-Fi 语音')
            session=self.device.pulse()['state']['session'];wav=self.audio.finish(session)
            return {'wav_base64':base64.b64encode(wav).decode('ascii')}
        if path=='/api/audio/cancel':
            if self.audio:self.audio.cancel()
            return {'cancelled':True}
        if path.startswith('/api/device/'):
            if not self.device:raise Rejected('当前没有连接设备；用 --usb、--ble-address 或 --simulation 选择连接方式')
            if path.endswith('/connect'):self.device.disconnect();return self.device.pulse()
            if path.endswith('/pulse'):
                cursor=data.get('cursor')
                if cursor is not None and (type(cursor) is not int or cursor<0):raise Rejected('invalid event cursor')
                return self.device.pulse(cursor)
            if path.endswith('/buttons'):self.device.buttons(data.get('mask'));return {'accepted':True}
            if path.endswith('/command'):
                command,value=data.get('command'),data.get('value',0)
                wireless_start=self.device_mode=='ble' and command==5 and value==1
                if wireless_start:
                    if not self.audio:raise Rejected('无线录音需要 --wifi-config 连接配置')
                    self.audio.arm(self.device.pulse()['state']['session'])
                try:return self.device.command(command,value)
                except Exception:
                    if wireless_start:self.audio.cancel()
                    raise
        raise Rejected('未知操作')
    def close(self):
        if self.audio:self.audio.close()
        if self.device:self.device.close()
        self.ai.close()

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,application):
        self.application=application;super().__init__(address,Handler)
    def server_bind(self):
        # This server binds an explicit loopback address. HTTPServer's reverse
        # DNS lookup can stall local startup and provides no useful identity.
        socketserver.TCPServer.server_bind(self)
        self.server_name,self.server_port=self.server_address[:2]

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,fmt,*args):
        # No instructions, audio, file contents or access tokens in request logs.
        if len(args)>1 and not self.path.endswith('/pulse'):print('HTTP',args[1],self.path.split('?')[0][:80],flush=True)
    def allowed_host(self):return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
    def reply(self,status,body,content_type='application/json; charset=utf-8'):
        if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer');self.send_header('Cross-Origin-Resource-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        if not self.allowed_host():return self.reply(403,{'error':'invalid Host'})
        name=urllib.parse.urlsplit(self.path).path
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/recorder.js':'recorder.js','/interaction.js':'interaction.js'}
        if name not in files:return self.reply(404,{'error':'not found'})
        path=STATIC/files[name]
        try:body=path.read_bytes()
        except OSError:return self.reply(404,{'error':'not found'})
        if name=='/':body=body.replace(b'__SESSION_TOKEN__',self.server.application.token.encode())
        return self.reply(200,body,mimetypes.guess_type(str(path))[0]+'; charset=utf-8')
    def do_POST(self):
        origin=f'http://127.0.0.1:{self.server.server_port}'
        if not self.allowed_host() or self.headers.get('Origin')!=origin or not secrets.compare_digest(self.headers.get('X-AIKEY-Session',''),self.server.application.token):
            self.close_connection=True;return self.reply(403,{'error':'request origin or session rejected'})
        if self.headers.get('Content-Type')!='application/json':return self.reply(415,{'error':'JSON required'})
        try:length=int(self.headers.get('Content-Length','-1'))
        except ValueError:length=-1
        if not 0<length<=2_800_000:
            self.close_connection=True;return self.reply(413,{'error':'request size rejected'})
        try:
            self.connection.settimeout(15);data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise Rejected('JSON object required')
            result=self.server.application.call(self.path,data);return self.reply(200,result)
        except Conflict as error:return self.reply(409,{'error':str(error)})
        except (Rejected,ValueError,TypeError,KeyError) as error:return self.reply(400,{'error':str(error)})
        except OSError as error:return self.reply(500,{'error':'本地文件或模型服务失败：'+str(error)})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,default=ROOT/'host/workspace')
    parser.add_argument('--journal',type=Path,default=Path.home()/'.cache/ai-key-rev-a/host-journal')
    parser.add_argument('--port',type=int,default=8893)
    modes=parser.add_mutually_exclusive_group();modes.add_argument('--simulation',action='store_true');modes.add_argument('--usb',action='store_true');modes.add_argument('--ble-address')
    parser.add_argument('--usb-serial');parser.add_argument('--wifi-config',type=Path);args=parser.parse_args()
    if args.usb_serial and not args.usb:parser.error('--usb-serial requires --usb')
    if args.wifi_config and not args.ble_address:parser.error('--wifi-config requires --ble-address')
    device=None
    if args.usb or args.ble_address:
        from physical_device import PhysicalDevice
        from transports import USBTransport,BLETransport
        try:device=PhysicalDevice(USBTransport(args.usb_serial) if args.usb else BLETransport(args.ble_address))
        except (Rejected,OSError) as e:parser.exit(2,str(e)+'\n')
    audio=None
    if args.wifi_config:
        from wifi_audio import AudioReceiver,load_config
        try:audio=AudioReceiver(load_config(args.wifi_config))
        except (Rejected,OSError,ValueError) as e:
            if device:device.close()
            parser.exit(2,str(e)+'\n')
    app=Application(args.workspace,args.journal,args.simulation,device,audio);server=Server(('127.0.0.1',args.port),app)
    print(f'AI KEY workbench: http://127.0.0.1:{server.server_port} — '+app.device_mode,flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()
if __name__=='__main__':main()

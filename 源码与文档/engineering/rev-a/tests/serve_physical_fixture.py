"""Test-only HTTP input fixture. Never imported by the product server."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from host_physical_test import WireFixture
from physical_device import PhysicalDevice
from server import Application,Server
class FixtureApplication(Application):
    def call(self,path,data):
        if path=='/api/test-fixture/buttons':
            mask=data['mask']
            if type(mask) is not int or not 0<=mask<=15:raise ValueError('invalid fixture mask')
            self.device.transport.buttons(mask);return {'test_fixture_only':True}
        return super().call(path,data)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('workspace',type=Path);parser.add_argument('journal',type=Path);args=parser.parse_args()
    io=WireFixture();io.label='usb'
    app=FixtureApplication(args.workspace,args.journal,device=PhysicalDevice(io));server=Server(('127.0.0.1',0),app)
    print(f'http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()

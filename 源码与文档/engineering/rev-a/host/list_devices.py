#!/usr/bin/env python3
"""Read-only discovery; never pairs, opens HID handles or sends commands."""
import argparse,asyncio,json
def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True);g.add_argument('--usb',action='store_true');g.add_argument('--ble',action='store_true');a=p.parse_args()
    if a.usb:
        import hid
        result=[{k:d.get(k) for k in ('serial_number','product_string','usage_page','usage','interface_number')} for d in hid.enumerate(0xcafe,0x4031)]
    else:
        from bleak import BleakScanner
        async def scan():
            devices=await BleakScanner.discover(timeout=8,return_adv=True)
            return [{'address':d.address,'name':advert.local_name or d.name,'rssi':advert.rssi} for d,advert in devices.values() if (advert.local_name or d.name or '').startswith('AIKEY-')]
        result=asyncio.run(scan())
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

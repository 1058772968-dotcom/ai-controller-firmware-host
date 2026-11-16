// 对 cafe:4031 发一次 USB 总线复位（ReEnumerate），用来验证闸门不会卡开
import Foundation
import IOKit
import IOKit.usb
import IOKit.usb.IOUSBLib
let kUser=CFUUIDGetConstantUUIDWithBytes(nil,0x9d,0xc7,0xb7,0x80,0x9e,0xc0,0x11,0xD4,0xa5,0x4f,0x00,0x0a,0x27,0x05,0x28,0x61)!
let kPlug=CFUUIDGetConstantUUIDWithBytes(nil,0xC2,0x44,0xE8,0x58,0x10,0x9C,0x11,0xD4,0x91,0xD4,0x00,0x50,0xE4,0xC6,0x42,0x6F)!
let kDev=CFUUIDGetConstantUUIDWithBytes(nil,0x5c,0x81,0x87,0xd0,0x9e,0xf3,0x11,0xD4,0x8b,0x45,0x00,0x0a,0x27,0x05,0x28,0x61)!
let m=IOServiceMatching("IOUSBHostDevice") as NSMutableDictionary
m["idVendor"]=0xcafe;m["idProduct"]=0x4031
let s=IOServiceGetMatchingService(kIOMainPortDefault,m);guard s != 0 else{print("没找到设备");exit(1)}
var pi:UnsafeMutablePointer<UnsafeMutablePointer<IOCFPlugInInterface>?>?;var sc:Int32=0
var kr=IOCreatePlugInInterfaceForService(s,kUser,kPlug,&pi,&sc);guard kr==0,let p=pi?.pointee?.pointee else{print("plugin",kr);exit(2)}
var di:UnsafeMutablePointer<UnsafeMutablePointer<IOUSBDeviceInterface>?>?
_=withUnsafeMutablePointer(to:&di){$0.withMemoryRebound(to:Optional<LPVOID>.self,capacity:1){p.QueryInterface(pi,CFUUIDGetUUIDBytes(kDev),$0)}}
guard let d=di?.pointee?.pointee else{print("qi");exit(3)}
kr=d.USBDeviceOpen(di);print("open",String(kr,radix:16))
kr=d.USBDeviceReEnumerate(di,0);print("reenum",String(kr,radix:16))
_=d.USBDeviceClose(di)

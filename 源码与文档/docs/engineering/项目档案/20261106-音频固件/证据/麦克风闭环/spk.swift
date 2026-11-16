// 用法：spk vol <deviceID> [0..1]  读/写输出音量；spk play <deviceID> <wav>  播放到指定设备
import AVFoundation
import CoreAudio
let a=CommandLine.arguments
let dev=AudioDeviceID(a[2])!
if a[1]=="vol"{
 func addr(_ el:UInt32)->AudioObjectPropertyAddress{AudioObjectPropertyAddress(mSelector:kAudioDevicePropertyVolumeScalar,mScope:kAudioObjectPropertyScopeOutput,mElement:el)}
 for el in [UInt32(0),1,2]{var p=addr(el);if !AudioObjectHasProperty(dev,&p){continue}
  if a.count>3{var v=Float32(a[3])!;let st=AudioObjectSetPropertyData(dev,&p,0,nil,4,&v);if st != 0{print("set fail",st)}}
  var v=Float32(0);var z:UInt32=4;AudioObjectGetPropertyData(dev,&p,0,nil,&z,&v);print("element",el,"vol",v)}
 var m=AudioObjectPropertyAddress(mSelector:kAudioDevicePropertyMute,mScope:kAudioObjectPropertyScopeOutput,mElement:0)
 var mv=UInt32(0);var z:UInt32=4;if AudioObjectGetPropertyData(dev,&m,0,nil,&z,&mv)==0{print("mute",mv)}
}else{
 let e=AVAudioEngine();let n=AVAudioPlayerNode();e.attach(n)
 var d=dev
 let st=AudioUnitSetProperty(e.outputNode.audioUnit!,kAudioOutputUnitProperty_CurrentDevice,kAudioUnitScope_Global,0,&d,4)
 if st != 0{print("bind fail",st);exit(1)}
 let f=try! AVAudioFile(forReading:URL(fileURLWithPath:a[3]))
 e.connect(n,to:e.mainMixerNode,format:f.processingFormat)
 try! e.start()
 let s=DispatchSemaphore(value:0)
 n.scheduleFile(f,at:nil,completionCallbackType:.dataPlayedBack){_ in s.signal()}
 n.play();s.wait();e.stop()
}

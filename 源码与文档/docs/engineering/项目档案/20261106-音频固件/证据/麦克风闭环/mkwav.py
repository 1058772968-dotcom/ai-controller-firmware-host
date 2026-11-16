import math,struct,sys,wave
# 生成：mkwav.py out.wav hz sec amp(0..1)
o,hz,sec,amp=sys.argv[1],float(sys.argv[2]),float(sys.argv[3]),float(sys.argv[4])
r=48000;n=int(r*sec);w=wave.open(o,'wb');w.setnchannels(1);w.setsampwidth(2);w.setframerate(r)
fade=int(r*0.02)
w.writeframes(b''.join(struct.pack('<h',int(32767*amp*min(1,i/fade,(n-i)/fade)*math.sin(2*math.pi*hz*i/r))) for i in range(n)));w.close()

import math,struct,wave
r=48000
def tone(hz,s,a=.25):
    n=int(r*s);f=int(.02*r)
    return [a*min(1,i/f,(n-i)/f)*math.sin(2*math.pi*hz*i/r) for i in range(n)]
def sweep(f0,f1,s,a=.25):
    n=int(r*s);k=math.log(f1/f0);f=int(.02*r)
    return [a*min(1,i/f,(n-i)/f)*math.sin(2*math.pi*f0*s/k*(math.exp(k*i/n)-1)) for i in range(n)]
x=[0.0]*r+tone(1000,6)+[0.0]*(r//2)+sweep(100,7500,6)+[0.0]*(r//2)
w=wave.open('stim.wav','wb');w.setnchannels(1);w.setsampwidth(2);w.setframerate(r)
w.writeframes(b''.join(struct.pack('<h',int(v*32767)) for v in x));w.close();print(len(x)/r)

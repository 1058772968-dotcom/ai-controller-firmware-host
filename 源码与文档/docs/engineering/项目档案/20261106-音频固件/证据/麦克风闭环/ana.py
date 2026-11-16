import sys,wave
import numpy as np
from scipy.signal import hilbert,butter,sosfiltfilt,welch
f=sys.argv[1]
w=wave.open(f);r=w.getframerate();x=np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(float)/32768
db=lambda v:20*np.log10(np.maximum(v,1e-9))
print(f,len(x)/r,'s','DC',round(x.mean()*32768,1),'LSB')
# 连续零段
z=(x==0).astype(int);d=np.diff(np.r_[0,z,0]);s=np.where(d==1)[0];e=np.where(d==-1)[0];L=e-s
big=[(round(a/r,3),int(l)) for a,l in zip(s,L) if l>=4]
print('零段>=4样本',len(big),big[:12],'最长',int(L.max()) if len(L) else 0)
# 100ms 包络
h=r//10;n=len(x)//h;env=db(np.sqrt((x[:n*h].reshape(n,h)**2).mean(1)))
print('包络(每0.5s,dBFS):',' '.join(f'{v:.0f}' for v in env[::5]))
# 找单音段：1 kHz 窄带能量占比高
b=butter(4,[900,1100],'bandpass',fs=r,output='sos');y=sosfiltfilt(b,x)
ye=np.sqrt((y[:n*h].reshape(n,h)**2).mean(1));xe=np.sqrt((x[:n*h].reshape(n,h)**2).mean(1))
idx=np.where((ye/np.maximum(xe,1e-9)>.8)&(db(xe)>-50))[0]
if len(idx)>10:
    runs=np.split(idx,np.where(np.diff(idx)>1)[0]+1);run=max(runs,key=len)
    a,bb=(run[0]+2)*h,(run[-1]-1)*h
    seg=y[a:bb];an=hilbert(seg);ph=np.unwrap(np.angle(an));t=np.arange(len(seg))/r
    p=np.polyfit(t,ph,1);hz=p[0]/2/np.pi;res=ph-np.polyval(p,t)
    jump=np.abs(np.diff(res));am=np.abs(an)
    print(f'单音段 {a/r:.2f}-{bb/r:.2f}s 频率 {hz:.3f} Hz (偏差 {(hz/1000-1)*1e6:.0f} ppm) 相位残差rms {res.std():.3f} rad 最大相位跳 {jump.max():.3f} rad  幅度波动 {db(am.max()/am.min()):.1f} dB')
    raw=x[a:bb]*np.hanning(bb-a);S=np.abs(np.fft.rfft(raw));fr=np.fft.rfftfreq(bb-a,1/r)
    k=np.argmax(S);P=S**2;sig=P[k-6:k+7].sum();
    hs=[P[np.argmin(abs(fr-m*hz))-6:np.argmin(abs(fr-m*hz))+7].sum() for m in range(2,8)]
    print(f'  基波 {db(np.sqrt(sig/P.sum()*(raw**2).sum()/ (np.hanning(bb-a)**2).mean()/(bb-a)))[()] :.1f} dBFS; THD {10*np.log10(sum(hs)/sig):.1f} dB; SINAD {10*np.log10(sig/(P.sum()-sig)):.1f} dB')
# 静音底噪（包络最低 10%）
q=np.sort(env);print(f'底噪 RMS(最低10%包络) {q[:max(1,n//10)].mean():.1f} dBFS, 最高 {q[-1]:.1f} dBFS, 动态 {q[-1]-q[:max(1,n//10)].mean():.1f} dB')

bands=[(20,100),(100,300),(300,1000),(1000,3400),(3400,7000)]
qi=np.argsort(env)[:max(3,n//10)];seg=np.concatenate([x[i*h:(i+1)*h] for i in sorted(qi)])
fr,P=welch(seg,r,nperseg=2048);df=fr[1]-fr[0]
print('底噪分频段 dBFS:',' '.join(f"{a}-{b}Hz {10*np.log10(P[(fr>=a)&(fr<b)].sum()*df+1e-15):.1f}" for a,b in bands))

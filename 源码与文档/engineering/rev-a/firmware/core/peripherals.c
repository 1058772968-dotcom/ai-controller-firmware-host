#include "peripherals.h"
#include <string.h>
#define DRV 0x5a
#define GAUGE 0x36
static bool rd(ak_peripherals *p,uint8_t a,uint8_t r,uint8_t *d,size_t n) {return p->io.read(p->io.context,a,r,d,n);}
static bool wr(ak_peripherals *p,uint8_t a,uint8_t r,uint8_t d) {return p->io.write(p->io.context,a,r,&d,1);}
static void enable(ak_peripherals *p,bool on) {p->io.enable_haptic(p->io.context,on);p->enabled=on;}
static void fail(ak_peripherals *p) {enable(p,false);p->state=AK_HAP_FAILED;}
static bool stop(ak_peripherals *p) {
    /* EN retains registers. Clear GO before gating, or latch failure so the
       next enable can never resume a cancelled calibration/waveform. */
    bool ok=!p->enabled || wr(p,DRV,0x0c,0);
    enable(p,false);if(!ok)p->state=AK_HAP_FAILED;return ok;
}
bool ak_haptic_ready(const ak_peripherals *p) {return p->state==AK_HAP_READY || p->state==AK_HAP_PLAY_WAKE || p->state==AK_HAP_PLAY;}
void ak_peripherals_init(ak_peripherals *p,ak_i2c_io io,uint32_t now) {
    memset(p,0,sizeof(*p));p->io=io;p->since=p->quiet_since=p->last_gauge=now;enable(p,false);
}
static bool setup(ak_peripherals *p) {
    uint8_t status;
    if(!rd(p,DRV,0,&status,1) || (status&0xe0)!=0xe0 || (status&3))return false;
    /* C10-100 R006 recommends ~30% voltage reduction with auto-resonance.
       Use a 1.4 Vrms development starting point at 175 Hz, not its 2 V
       sine rating. TI Eq 5, sample=300us:
       floor(1.4*sqrt(1-(4*.0003+.0003)*175)/.02058) = 58.
       Eq 9: floor(1.45*sqrt(2)/.02122)=96 peak clamp.
       Actual mounted actuator voltage/temperature still requires measurement.
       Drive time rounded to 2.8ms => 23; no OTP writes. */
    const uint8_t config[][2]={{0x0c,0},{0x01,0x07},{0x03,6},{0x16,58},{0x17,96},
        {0x1a,0xb6},{0x1b,0x97},{0x1c,0xf5},{0x1d,0xa0},{0x1e,0x30},{0x1f,0x80},{0x0c,1}};
    for(size_t i=0;i<sizeof(config)/sizeof(config[0]);i++)if(!wr(p,DRV,config[i][0],config[i][1]))return false;
    return true;
}
static void gauge(ak_peripherals *p) {
    uint8_t version[2],data[4];p->battery_valid=false;
    if(!rd(p,GAUGE,8,version,2) || version[0]!=0 || (version[1]&0xf0)!=0x10 || !rd(p,GAUGE,2,data,4)) {p->gauge_failed=true;return;}
    uint16_t raw=(uint16_t)((uint16_t)data[0]<<8|data[1]);
    uint16_t mv=(uint16_t)(((uint32_t)raw*625+4000)/8000);
    uint16_t soc=(uint16_t)((uint16_t)data[2]<<8|data[3]);
    /* Invalid readings are not rendered as an empty battery. No quick-start,
       POR, or custom battery model is silently programmed. */
    if(mv<2000 || mv>4500 || soc>100u*256u) {p->gauge_failed=true;return;}
    p->battery_mv=mv;p->soc_q8=soc;p->battery_valid=true;p->gauge_failed=false;
}
void ak_peripherals_step(ak_peripherals *p,uint32_t now,bool inhibit,bool feedback) {
    if(inhibit) {
        stop(p);p->quiet_since=now;
        if(p->state==AK_HAP_WAKE || p->state==AK_HAP_CAL)p->state=AK_HAP_IDLE;
        else if(p->state==AK_HAP_PLAY_WAKE || p->state==AK_HAP_PLAY)p->state=AK_HAP_READY;
        p->request_seen=feedback;
    }
    if((uint32_t)(now-p->last_gauge)>=1000) {p->last_gauge=now;gauge(p);}
    if(inhibit || p->state==AK_HAP_FAILED)return;
    if(!feedback) {
        p->request_seen=false;
        if(p->state==AK_HAP_PLAY_WAKE || p->state==AK_HAP_PLAY) {if(stop(p))p->state=AK_HAP_READY;}
    }
    switch(p->state) {
    case AK_HAP_IDLE:
        if((uint32_t)(now-p->quiet_since)>=1000) {enable(p,true);p->since=now;p->state=AK_HAP_WAKE;}
        break;
    case AK_HAP_WAKE:
        if((uint32_t)(now-p->since)<2)break;
        if(!setup(p)) {fail(p);break;}
        p->since=now;p->last_status=now;p->state=AK_HAP_CAL;break;
    case AK_HAP_CAL: {
        if((uint32_t)(now-p->since)>1600) {fail(p);break;}
        if((uint32_t)(now-p->last_status)<10)break;
        p->last_status=now;uint8_t go,status,cal[3];
        if(!rd(p,DRV,0x0c,&go,1)) {fail(p);break;}
        if(go&1)break;
        if(!rd(p,DRV,0,&status,1) || (status&0x0b) || !rd(p,DRV,0x18,cal,3)) {fail(p);break;}
        p->cal_comp=cal[0];p->cal_bemf=cal[1];p->cal_feedback=cal[2];
        if(!wr(p,DRV,1,0)) {fail(p);break;}
        enable(p,false);p->state=AK_HAP_READY;break;
    }
    case AK_HAP_READY:
        if(feedback && !p->request_seen) {enable(p,true);p->since=now;p->state=AK_HAP_PLAY_WAKE;p->request_seen=true;}
        break;
    case AK_HAP_PLAY_WAKE:
        if((uint32_t)(now-p->since)<2)break;
        if(!wr(p,DRV,1,0) || !wr(p,DRV,4,1) || !wr(p,DRV,5,0) || !wr(p,DRV,0x0c,1)) {fail(p);break;}
        p->state=AK_HAP_PLAY;p->last_status=now;break;
    case AK_HAP_PLAY: {
        /* Independent watchdog prevents a stuck request from continuous drive. */
        if((uint32_t)(now-p->since)>=80) {if(stop(p))p->state=AK_HAP_READY;break;}
        if((uint32_t)(now-p->last_status)>=10) {
            uint8_t status;p->last_status=now;
            if(!rd(p,DRV,0,&status,1) || (status&3))fail(p);
        }
        break;
    }
    case AK_HAP_FAILED:break;
    }
}

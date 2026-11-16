#include "peripherals.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
typedef struct {uint8_t drv[256],gauge[256];bool on,fail_read,fail_write;unsigned writes,enable_count;} fake_bus;
static bool read_bus(void *v,uint8_t a,uint8_t r,uint8_t *d,size_t n) {
    fake_bus *b=v;if(b->fail_read)return false;
    if(a==0x5a && !b->on)return false;
    assert(a==0x5a || a==0x36);memcpy(d,(a==0x5a?b->drv:b->gauge)+r,n);return true;
}
static bool write_bus(void *v,uint8_t a,uint8_t r,const uint8_t *d,size_t n) {
    fake_bus *b=v;if(b->fail_write)return false;
    assert(a==0x5a && b->on);assert(r!=0xfe);memcpy(b->drv+r,d,n);b->writes++;return true;
}
static void enable(void *v,bool on) {fake_bus *b=v;b->on=on;if(on)b->enable_count++;}
static void init(ak_peripherals *p,fake_bus *b,uint32_t t) {
    memset(b,0,sizeof(*b));b->drv[0]=0xe0;b->gauge[9]=0x12;
    /* 0xc800 * 78.125uV = 4.000V, SOC 75.5%. */
    b->gauge[2]=0xc8;b->gauge[3]=0;b->gauge[4]=75;b->gauge[5]=128;
    ak_peripherals_init(p,(ak_i2c_io){b,read_bus,write_bus,enable},t);
}
static void calibrated(ak_peripherals *p,fake_bus *b,uint32_t t) {
    ak_peripherals_step(p,t+1000,false,false);assert(b->on && !ak_haptic_ready(p));
    ak_peripherals_step(p,t+1002,false,false);assert(p->state==AK_HAP_CAL && b->drv[12]==1);
    assert(b->drv[27]==0x97 && b->drv[30]==0x30);
    /* Evaluate the actual written registers against the motor's derated
       starting limits, including its nominal resonance tolerance. */
    double nominal=.02058*b->drv[22]/sqrt(1-.0015*175);
    double high_frequency=.02058*b->drv[22]/sqrt(1-.0015*183);
    double clamp_rms=.02122*b->drv[23]/sqrt(2.0);
    assert(nominal>1.38 && nominal<=1.4 && high_frequency<1.42);
    assert(clamp_rms>=1.4 && clamp_rms<=1.45);
    b->drv[12]=0;b->drv[24]=37;b->drv[25]=91;b->drv[26]=0xb5;
    ak_peripherals_step(p,t+2012,false,false);
    assert(ak_haptic_ready(p) && !b->on && p->cal_comp==37 && p->cal_feedback==0xb5);
}
int main(void) {
    ak_peripherals p;fake_bus b;init(&p,&b,0);assert(!b.on && !p.battery_valid);
    calibrated(&p,&b,0);assert(p.battery_valid && p.battery_mv==4000 && p.soc_q8==19328);
    ak_peripherals_step(&p,2100,false,true);assert(b.on && p.state==AK_HAP_PLAY_WAKE);
    ak_peripherals_step(&p,2102,false,true);assert(p.state==AK_HAP_PLAY && b.drv[4]==1 && b.drv[5]==0);
    ak_peripherals_step(&p,2103,true,true);assert(!b.on && b.drv[12]==0 && ak_haptic_ready(&p));
    ak_peripherals_step(&p,2200,false,true);assert(!b.on); /* no replay after interlock */
    ak_peripherals_step(&p,2201,false,false);ak_peripherals_step(&p,2202,false,true);ak_peripherals_step(&p,2204,false,true);
    ak_peripherals_step(&p,2282,false,true);assert(!b.on && b.drv[12]==0); /* independent 80ms limit */
    ak_peripherals_step(&p,2500,false,true);assert(!b.on);
    b.fail_read=true;ak_peripherals_step(&p,3200,false,false);assert(!p.battery_valid && p.gauge_failed);
    b.fail_read=false;b.gauge[4]=101;ak_peripherals_step(&p,4200,false,false);assert(!p.battery_valid);
    init(&p,&b,0);ak_peripherals_step(&p,1000,false,false);ak_peripherals_step(&p,1002,false,false);
    ak_peripherals_step(&p,1100,true,false);assert(!b.on && b.drv[12]==0 && p.state==AK_HAP_IDLE);
    ak_peripherals_step(&p,2099,false,false);assert(!b.on);ak_peripherals_step(&p,2100,false,false);assert(b.on);
    init(&p,&b,0);ak_peripherals_step(&p,1000,false,false);ak_peripherals_step(&p,1002,false,false);
    b.drv[12]=0;b.drv[0]=0xe8;ak_peripherals_step(&p,1020,false,false);assert(p.state==AK_HAP_FAILED && !b.on);
    init(&p,&b,0);ak_peripherals_step(&p,1000,false,false);ak_peripherals_step(&p,1002,false,false);
    ak_peripherals_step(&p,2700,false,false);assert(p.state==AK_HAP_FAILED && !b.on); /* GO stuck */
    init(&p,&b,0);b.drv[0]=0x60;ak_peripherals_step(&p,1000,false,false);ak_peripherals_step(&p,1002,false,false);assert(p.state==AK_HAP_FAILED);
    init(&p,&b,0);calibrated(&p,&b,0);ak_peripherals_step(&p,2100,false,true);b.fail_write=true;
    ak_peripherals_step(&p,2101,true,false);assert(p.state==AK_HAP_FAILED && !b.on);
    b.fail_write=false;ak_peripherals_step(&p,5000,false,true);assert(!b.on); /* retained GO cannot resume */
    uint32_t near_wrap=UINT32_MAX-500;init(&p,&b,near_wrap);calibrated(&p,&b,near_wrap);
    puts("PASS gauge decoding/validity; haptic voltage registers, measured calibration completion, cancellation, timeout, bus failures, no replay, independent 80ms limit and clock wrap; fake I2C bus, no physical actuator");
}

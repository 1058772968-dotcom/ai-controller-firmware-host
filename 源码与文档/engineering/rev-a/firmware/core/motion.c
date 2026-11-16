#include "motion.h"
#include <math.h>
#include <string.h>
void ak_motion_init(ak_motion *m) {memset(m,0,sizeof(*m));m->gain=8.0f;}
void ak_motion_recenter(ak_motion *m) {m->fraction_x=0;m->fraction_y=0;}
bool ak_motion_step(ak_motion *m,const float g[3],const float a[3],float dt,int16_t *dx,int16_t *dy) {
    *dx=*dy=0;
    for(unsigned i=0;i<3;i++)if(!isfinite(g[i])||!isfinite(a[i])) {ak_motion_recenter(m);return false;}
    if(!isfinite(dt)||dt<=0||dt>.05f) {ak_motion_recenter(m);return false;}
    float gravity=a[0]*a[0]+a[1]*a[1]+a[2]*a[2];
    bool stationary=gravity>.85f && gravity<1.15f;
    for(unsigned i=0;i<3;i++)stationary=stationary && fabsf(g[i])<3.0f;
    if(!m->calibrated) {
        if(!stationary) {m->stationary_samples=0;memset(m->sum,0,sizeof(m->sum));return false;}
        for(unsigned i=0;i<3;i++)m->sum[i]+=g[i];
        if(++m->stationary_samples>=120) {for(unsigned i=0;i<3;i++)m->bias[i]=m->sum[i]/120.0f;m->calibrated=true;}
        return false;
    }
    // Board +Y points toward the thumb keys; +X is right. No magnetometer:
    // relative gyro motion is intentional; no absolute heading claim.
    float yaw=g[1]-m->bias[1],pitch=g[0]-m->bias[0];
    if(fabsf(yaw)<.4f)yaw=0;
    if(fabsf(pitch)<.4f)pitch=0;
    m->fraction_x+=yaw*dt*m->gain;m->fraction_y-=pitch*dt*m->gain;
    float x=fminf(127,fmaxf(-127,m->fraction_x)),y=fminf(127,fmaxf(-127,m->fraction_y));
    *dx=(int16_t)x;*dy=(int16_t)y;
    // Discard excess instead of replaying a cursor jump after a long stall.
    m->fraction_x=x-*dx;m->fraction_y=y-*dy;
    return true;
}

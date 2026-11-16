#include "motion.h"
#include "audio_filter.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static double tone(double hz) {
    ak_audio_filter f={0};int16_t input[480],output[160];double sum=0;unsigned count=0;
    for(unsigned block=0;block<100;block++) {
        for(unsigned i=0;i<480;i++)input[i]=(int16_t)(12000*sin(6.283185307179586*hz*(block*480+i)/48000));
        assert(ak_audio_filter_decimate(&f,input,480,output)==160);
        if(block)for(unsigned i=0;i<160;i++) {sum+=(double)output[i]*output[i];count++;}
    }
    return sqrt(sum/count);
}
int main(void) {
    ak_motion m;ak_motion_init(&m);float a[3]={0,0,1},g[3]={0,5,0};int16_t x,y;
    for(unsigned i=0;i<200;i++)assert(!ak_motion_step(&m,g,a,1.f/240,&x,&y));
    assert(!m.calibrated);
    g[0]=.5f;g[1]=-.3f;g[2]=.1f;
    for(unsigned i=0;i<120;i++)ak_motion_step(&m,g,a,1.f/240,&x,&y);
    assert(m.calibrated);
    for(unsigned i=0;i<2400;i++) {assert(ak_motion_step(&m,g,a,1.f/240,&x,&y));assert(!x && !y);}
    g[1]+=10;int total=0;
    for(unsigned i=0;i<240;i++) {ak_motion_step(&m,g,a,1.f/240,&x,&y);total+=x;assert(y==0);}
    assert(total>=79 && total<=80);
    assert(!ak_motion_step(&m,g,a,.1f,&x,&y));assert(!x && !y);
    g[0]=NAN;assert(!ak_motion_step(&m,g,a,.004f,&x,&y));
    double pass=tone(1000),stop=tone(12000);
    assert(pass>8200 && pass<8700);assert(stop/pass<.001);
    ak_audio_filter f={0};int16_t in[7]={3000,4000,5000,6000,7000,8000,9000},out[3];
    assert(ak_audio_filter_decimate(&f,in,7,out)==2);
    ak_audio_filter_reset(&f);memset(in,0,sizeof(in));
    assert(ak_audio_filter_decimate(&f,in,7,out)==2);assert(out[0]==0 && out[1]==0);
    printf("PASS stationary calibration, moving-start rejection, drift/deadband, angle integration, invalid/stalled samples, 3:1 streaming decimation and reset. 1kHz RMS %.3f; 12kHz RMS %.3f; rejection bound %.2f dB (0.5 LSB measurement floor)\n",pass,stop,20*log10(fmax(stop,.5)/pass));
}

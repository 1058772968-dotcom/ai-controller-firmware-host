#include "audio_filter.h"
#include "audio_coefficients.h"
#include <string.h>
void ak_audio_filter_reset(ak_audio_filter *f) {memset(f,0,sizeof(*f));}
size_t ak_audio_filter_decimate(ak_audio_filter *f,const int16_t *in,size_t n,int16_t *out) {
    size_t count=0;
    for(size_t i=0;i<n;i++) {
        f->history[f->cursor]=in[i];f->cursor=(f->cursor+1)%63;
        if(++f->phase!=3)continue;
        f->phase=0;float value=0;unsigned pos=f->cursor;
        for(unsigned j=0;j<63;j++) {pos=(pos+62)%63;value+=coefficients[j]*f->history[pos];}
        if(value>32767)value=32767;
        if(value<-32768)value=-32768;
        out[count++]=(int16_t)value;
    }
    return count;
}

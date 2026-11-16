#include "audio_wire.h"
#include <string.h>
static void put32(uint8_t *p,uint32_t v) {for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(i*8));}
static uint32_t get32(const uint8_t *p) {return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
size_t ak_audio_frame(uint8_t *out,size_t cap,uint8_t kind,uint32_t session,uint32_t stream,uint32_t sequence,const int16_t *pcm,size_t samples) {
    if(!out || !session || kind<AK_AUDIO_HELLO || kind>AK_AUDIO_PING || samples>AK_AUDIO_SAMPLES || cap<20+samples*2)return 0;
    if(kind==AK_AUDIO_DATA ? (!pcm || !samples || !stream) : samples!=0)return 0;
    if((kind==AK_AUDIO_HELLO || kind==AK_AUDIO_PING) && stream)return 0;
    if((kind==AK_AUDIO_BEGIN || kind==AK_AUDIO_END) && !stream)return 0;
    memcpy(out,"AKAU",4);out[4]=1;out[5]=kind;out[6]=(uint8_t)(samples*2);out[7]=(uint8_t)((samples*2)>>8);
    put32(out+8,session);put32(out+12,stream);put32(out+16,sequence);
    for(size_t i=0;i<samples;i++) {out[20+i*2]=(uint8_t)pcm[i];out[21+i*2]=(uint8_t)((uint16_t)pcm[i]>>8);}
    return 20+samples*2;
}
bool ak_audio_ack(const uint8_t *data,size_t size,uint32_t session,uint32_t stream,uint32_t sequence) {
    return data && size==20 && !memcmp(data,"AKAU",4) && data[4]==1 && data[5]==AK_AUDIO_ACK && !data[6] && !data[7] && get32(data+8)==session && get32(data+12)==stream && get32(data+16)==sequence;
}

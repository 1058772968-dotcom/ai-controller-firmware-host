#include "audio_wire.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    uint8_t b[AK_AUDIO_PACKET];int16_t pcm[]={0x1234,-32768,32767,-1};
    assert(ak_audio_frame(b,sizeof(b),AK_AUDIO_DATA,0x78563412,7,9,pcm,4)==28);
    const uint8_t expected[]={0x41,0x4b,0x41,0x55,1,3,8,0,0x12,0x34,0x56,0x78,7,0,0,0,9,0,0,0,0x34,0x12,0,0x80,0xff,0x7f,0xff,0xff};
    assert(!memcmp(b,expected,sizeof(expected)));
    assert(!ak_audio_frame(b,sizeof(b),AK_AUDIO_DATA,1,1,1,pcm,161));
    assert(!ak_audio_frame(b,27,AK_AUDIO_DATA,1,1,1,pcm,4));
    assert(!ak_audio_frame(b,sizeof(b),AK_AUDIO_DATA,1,0,1,pcm,4));
    assert(!ak_audio_frame(b,sizeof(b),AK_AUDIO_HELLO,1,1,1,NULL,0));
    assert(!ak_audio_frame(b,sizeof(b),AK_AUDIO_END,1,1,1,pcm,4));
    assert(ak_audio_frame(b,sizeof(b),AK_AUDIO_PING,42,0,77,NULL,0)==20);b[5]=AK_AUDIO_ACK;
    assert(ak_audio_ack(b,20,42,0,77));assert(!ak_audio_ack(b,20,43,0,77));assert(!ak_audio_ack(b,20,42,1,77));assert(!ak_audio_ack(b,20,42,0,78));assert(!ak_audio_ack(b,19,42,0,77));
    b[6]=2;assert(!ak_audio_ack(b,20,42,0,77));
    puts("PASS little-endian signed PCM cross-language vector; bounded frame size/type; ACK session/stream/sequence/length validation");
    return 0;
}

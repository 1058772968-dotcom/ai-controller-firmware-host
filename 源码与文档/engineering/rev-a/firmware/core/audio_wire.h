#ifndef AIKEY_AUDIO_WIRE_H
#define AIKEY_AUDIO_WIRE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define AK_AUDIO_HEADER 20
#define AK_AUDIO_SAMPLES 160
#define AK_AUDIO_PACKET (AK_AUDIO_HEADER+AK_AUDIO_SAMPLES*2)
enum {AK_AUDIO_HELLO=1,AK_AUDIO_BEGIN,AK_AUDIO_DATA,AK_AUDIO_END,AK_AUDIO_PING,AK_AUDIO_ACK};
size_t ak_audio_frame(uint8_t *,size_t,uint8_t,uint32_t,uint32_t,uint32_t,const int16_t *,size_t);
bool ak_audio_ack(const uint8_t *,size_t,uint32_t,uint32_t,uint32_t);
#endif

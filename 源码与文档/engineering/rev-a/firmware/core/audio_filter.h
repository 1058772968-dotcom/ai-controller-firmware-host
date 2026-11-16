#ifndef AK_AUDIO_FILTER_H
#define AK_AUDIO_FILTER_H
#include <stdint.h>
#include <stddef.h>
typedef struct {float history[63];unsigned cursor,phase;} ak_audio_filter;
void ak_audio_filter_reset(ak_audio_filter *f);
size_t ak_audio_filter_decimate(ak_audio_filter *f,const int16_t *input,size_t n,int16_t *output);
#endif

#ifndef AIKEY_WIFI_AUDIO_H
#define AIKEY_WIFI_AUDIO_H
#include "esp_err.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
esp_err_t ak_wifi_audio_init(void);
void ak_wifi_audio_context(uint32_t session,bool enabled,bool permit);
bool ak_wifi_audio_ready(uint32_t session);
void ak_wifi_audio_push(const int16_t *,size_t);
bool ak_wifi_audio_take_fault(void);
#endif

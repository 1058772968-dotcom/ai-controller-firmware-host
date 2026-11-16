#pragma once
#include "esp_err.h"
#include <stdbool.h>
esp_err_t ak_audio_init(void);
void ak_audio_set(bool powered,bool permitted);
void ak_audio_route(bool wireless);
bool ak_audio_failed(void);

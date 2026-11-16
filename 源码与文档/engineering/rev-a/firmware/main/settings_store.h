#ifndef AIKEY_SETTINGS_STORE_H
#define AIKEY_SETTINGS_STORE_H
#include "esp_err.h"
#include "settings.h"
esp_err_t ak_settings_load(void);
const uint8_t *ak_settings_current(void);
bool ak_settings_configured(void);
ak_settings_io ak_settings_backend(void);
#endif

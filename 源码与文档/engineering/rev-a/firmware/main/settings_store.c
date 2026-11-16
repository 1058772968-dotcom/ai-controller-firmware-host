#include "settings_store.h"
#include "ble_transport.h"
#include "nvs.h"
#include <string.h>
static uint8_t boot_settings[AK_SETTINGS_SIZE];static bool available,persisted;
esp_err_t ak_settings_load(void) {
    nvs_handle_t handle;esp_err_t e=nvs_open("aikey",NVS_READWRITE,&handle);if(e!=ESP_OK)return e;
    size_t length=sizeof(boot_settings);e=nvs_get_blob(handle,"wifi",boot_settings,&length);nvs_close(handle);
    if(e==ESP_ERR_NVS_NOT_FOUND) {available=persisted=false;return ESP_OK;}
    if(e!=ESP_OK || length!=sizeof(boot_settings) || !ak_settings_valid(boot_settings)) {memset(boot_settings,0,sizeof(boot_settings));return ESP_ERR_INVALID_STATE;}
    available=persisted=true;return ESP_OK;
}
const uint8_t *ak_settings_current(void) {return available?boot_settings:NULL;}
bool ak_settings_configured(void) {return persisted;}
static bool save(void *unused,const uint8_t bytes[AK_SETTINGS_SIZE]) {
    (void)unused;if(!ak_settings_valid(bytes))return false;
    nvs_handle_t handle;esp_err_t e=nvs_open("aikey",NVS_READWRITE,&handle);if(e!=ESP_OK)return false;
    e=nvs_set_blob(handle,"wifi",bytes,AK_SETTINGS_SIZE);if(e==ESP_OK)e=nvs_commit(handle);nvs_close(handle);
    if(e==ESP_OK)persisted=true;
    /* Apply after EN reset; do not replace an active transport's credentials. */
    return e==ESP_OK;
}
static bool forget(void *unused) {(void)unused;return ak_ble_forget_bonds();}
ak_settings_io ak_settings_backend(void) {return (ak_settings_io){NULL,save,forget};}

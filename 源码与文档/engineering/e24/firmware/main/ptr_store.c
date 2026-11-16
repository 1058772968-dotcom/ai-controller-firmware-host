#include "ptr_store.h"
#include "nvs.h"

bool ptr_store_load(ak_pointer_cfg *cfg)
{
    nvs_handle_t h;
    if (nvs_open("e24", NVS_READONLY, &h) != ESP_OK) return false;
    uint8_t w[AK_POINTER_WIRE_SIZE];
    size_t n = sizeof w;
    bool ok = nvs_get_blob(h, "ptr", w, &n) == ESP_OK && n == sizeof w && ak_pointer_cfg_decode(w, cfg);
    nvs_close(h);
    return ok;
}

bool ptr_store_save(const uint8_t w[AK_POINTER_WIRE_SIZE])
{
    nvs_handle_t h;
    if (nvs_open("e24", NVS_READWRITE, &h) != ESP_OK) return false;
    bool ok = nvs_set_blob(h, "ptr", w, AK_POINTER_WIRE_SIZE) == ESP_OK && nvs_commit(h) == ESP_OK;
    nvs_close(h);
    return ok;
}

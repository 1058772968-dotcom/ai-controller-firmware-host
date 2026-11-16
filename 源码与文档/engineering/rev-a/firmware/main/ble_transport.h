#pragma once
#include "esp_err.h"
#include "protocol.h"
esp_err_t ak_ble_init(void);
bool ak_ble_connected(void);
bool ak_ble_ready(void);
bool ak_ble_hid_available(void);
uint32_t ak_ble_generation(void);
void ak_ble_drop_link(void);
void ak_ble_set_active(bool active);
void ak_ble_flush(void);
bool ak_ble_pop_command(ak_wire_command *out);
bool ak_ble_pop_event(uint8_t out[AK_WIRE_SIZE]);
void ak_ble_queue_event(const ak_controller *,const ak_event *);
bool ak_ble_take_overflow(void);
bool ak_ble_forget_bonds(void);
bool ak_ble_mouse(uint8_t buttons,int8_t x,int8_t y);
bool ak_ble_state(const uint8_t packet[AK_WIRE_SIZE]);

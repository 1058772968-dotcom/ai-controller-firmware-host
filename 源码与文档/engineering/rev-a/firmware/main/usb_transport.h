#pragma once
void ak_usb_flush(void);
#include "controller.h"
#include "protocol.h"
#include "esp_err.h"
esp_err_t ak_usb_init(void);
bool ak_usb_pop_command(ak_wire_command *);
bool ak_usb_pop_event(uint8_t packet[AK_WIRE_SIZE]);
void ak_usb_queue_event(const ak_controller *,const ak_event *);
bool ak_usb_take_overflow(void);
bool ak_usb_pop_config(uint8_t out[32]);
bool ak_usb_config_reply(const uint8_t packet[32]);
bool ak_usb_mounted(void);
bool ak_usb_suspended(void);
bool ak_usb_ready(void);
bool ak_usb_mouse(uint8_t buttons,int8_t x,int8_t y);
bool ak_usb_state(const uint8_t packet[AK_WIRE_SIZE]);

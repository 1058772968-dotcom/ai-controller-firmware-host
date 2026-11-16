#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef struct { uint32_t bit_rate; } cdc_line_coding_t;
typedef struct {
  int type;
  union { struct { bool dtr, rts; } line_state_changed_data; struct { const cdc_line_coding_t *p_line_coding; } line_coding_changed_data; };
} cdcacm_event_t;
typedef void (*tusb_cdcacm_callback_t)(int itf, cdcacm_event_t *e);
#define TINYUSB_USBDEV_0 0
#define TINYUSB_CDC_ACM_0 0
typedef struct { int usb_dev, cdc_port; tusb_cdcacm_callback_t callback_line_state_changed, callback_line_coding_changed; } tinyusb_config_cdcacm_t;
esp_err_t tusb_cdc_acm_init(const tinyusb_config_cdcacm_t *c);
size_t tinyusb_cdcacm_write_queue(int itf, const uint8_t *b, size_t n);
esp_err_t tinyusb_cdcacm_write_flush(int itf, uint32_t timeout);
uint32_t tud_cdc_n_write_available(uint8_t itf);

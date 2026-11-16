#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
typedef struct __attribute__((packed)) {
  uint8_t bLength, bDescriptorType; uint16_t bcdUSB; uint8_t bDeviceClass, bDeviceSubClass, bDeviceProtocol, bMaxPacketSize0;
  uint16_t idVendor, idProduct, bcdDevice; uint8_t iManufacturer, iProduct, iSerialNumber, bNumConfigurations;
} tusb_desc_device_t;
#define TUSB_DESC_DEVICE 1
#define TUSB_CLASS_MISC 0xEF
#define MISC_SUBCLASS_COMMON 2
#define MISC_PROTOCOL_IAD 1
#define HID_ITF_PROTOCOL_NONE 0
#define TUSB_DESC_CONFIG_ATT_SELF_POWERED 0x40
#define U16LE(x) (uint8_t)((x) & 0xff), (uint8_t)(((x) >> 8) & 0xff)
#define TUD_CONFIG_DESC_LEN 9
#define TUD_CONFIG_DESCRIPTOR(num, itf, str, len, att, ma) 9, 2, U16LE(len), itf, num, str, 0x80 | (att), (ma) / 2
#define TUD_HID_INOUT_DESC_LEN (9 + 9 + 7 + 7)
#define TUD_HID_INOUT_DESCRIPTOR(itf, str, boot, rlen, epout, epin, sz, iv) \
  9, 4, itf, 0, 2, 3, 0, boot, str, 9, 0x21, U16LE(0x0111), 0, 1, 0x22, U16LE(rlen), \
  7, 5, epout, 3, U16LE(sz), iv, 7, 5, epin, 3, U16LE(sz), iv
#define TUD_CDC_DESC_LEN (8 + 9 + 5 + 5 + 4 + 5 + 7 + 9 + 7 + 7)
#define TUD_CDC_DESCRIPTOR(itf, str, ntf, nsz, eo, ei, sz) \
  8, 11, itf, 2, 2, 2, 0, 0, 9, 4, itf, 0, 1, 2, 2, 0, str, 5, 0x24, 0, U16LE(0x0120), 5, 0x24, 1, 0, (itf) + 1, \
  4, 0x24, 2, 6, 5, 0x24, 6, itf, (itf) + 1, 7, 5, ntf, 3, U16LE(nsz), 1, 9, 4, (itf) + 1, 0, 2, 10, 0, 0, 0, \
  7, 5, eo, 2, U16LE(sz), 0, 7, 5, ei, 2, U16LE(sz), 0
/* UAC 只保留 IAD 和两个接口描述符：模拟器不跑音频类，只核对接口数和总长 */
#define TUD_AUDIO20_MIC_ONE_CH_DESC_LEN (8 + 9 + 9)
#define TUD_AUDIO20_MIC_ONE_CH_DESCRIPTOR(itf, str, nb, bits, ep, sz) \
  8, 11, itf, 2, 1, 0, 0x20, 0, 9, 4, itf, 0, 0, 1, 1, 0x20, str, 9, 4, (itf) + 1, 0, 0, 1, 2, 0x20, 0
typedef struct {
  const tusb_desc_device_t *device_descriptor; const char **string_descriptor; int string_descriptor_count;
  bool external_phy; const uint8_t *configuration_descriptor; bool self_powered; int vbus_monitor_io;
} tinyusb_config_t;
esp_err_t tinyusb_driver_install(const tinyusb_config_t *cfg);

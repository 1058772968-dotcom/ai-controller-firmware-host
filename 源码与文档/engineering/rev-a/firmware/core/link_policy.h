#ifndef AIKEY_LINK_POLICY_H
#define AIKEY_LINK_POLICY_H
#include "controller.h"
typedef enum { LINK_NONE,LINK_USB,LINK_BLE } link_type;
typedef struct { bool usb_mounted,usb_suspended,ble_connected;uint32_t ble_generation; } ak_link_inputs;
typedef struct { link_type active;uint32_t ble_generation; } ak_link_policy;
typedef void (*ak_before_handoff)(void *,link_type old_link,link_type new_link);
bool ak_link_update(ak_link_policy *,ak_controller *,ak_link_inputs,uint8_t raw_keys,uint32_t now_ms,ak_before_handoff,void *);
#endif

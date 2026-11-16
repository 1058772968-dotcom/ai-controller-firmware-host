#include "link_policy.h"
bool ak_link_update(ak_link_policy *p,ak_controller *c,ak_link_inputs inputs,uint8_t raw,uint32_t now,ak_before_handoff before,void *context) {
    /* USB suspension retains ownership priority but emits no input. */
    link_type selected=inputs.usb_mounted?LINK_USB:inputs.usb_suspended?LINK_NONE:inputs.ble_connected?LINK_BLE:LINK_NONE;
    bool changed=selected!=p->active || (selected==LINK_BLE && inputs.ble_generation!=p->ble_generation);
    p->ble_generation=inputs.ble_generation;
    if(!changed)return false;
    if(before)before(context,p->active,selected);
    ak_poll(c,raw,now);ak_disconnect(c,now);
    p->active=selected;
    return true;
}

#include "link_policy.h"
#include "board_config.h"
#include <assert.h>
#include <stdio.h>
static unsigned handoffs;
static void before(void *context,link_type old,link_type next) {
    ak_link_policy *p=context;assert(p->active==old);assert(next>=LINK_NONE && next<=LINK_BLE);handoffs++;
}
static uint32_t time_ms;
static void key(ak_controller *c,uint8_t mask) {ak_poll(c,mask,++time_ms);time_ms+=AK_DEBOUNCE_MS;ak_poll(c,mask,time_ms);}
static void grant(ak_controller *c) {assert(ak_command(c,c->session,1,AK_HELLO,0,++time_ms)==AK_OK);assert(ak_command(c,c->session,2,AK_CLAIM,0,++time_ms)==AK_OK);}
int main(void) {
    ak_link_policy p={0};ak_controller c;ak_init(&c,123,0,0,NULL,NULL);
    ak_link_inputs i={.ble_connected=true,.ble_generation=1};
    assert(ak_link_update(&p,&c,i,0,++time_ms,before,&p));assert(p.active==LINK_BLE);
    key(&c,AK_L);assert(c.hid_buttons==AK_L);
    uint32_t session=c.session;i.usb_mounted=true;
    assert(ak_link_update(&p,&c,i,AK_L,++time_ms,before,&p));assert(p.active==LINK_USB);
    assert(c.session!=session && !c.hid_buttons && c.blocked&AK_L);
    key(&c,AK_L);assert(!c.hid_buttons);key(&c,0);key(&c,AK_L);assert(c.hid_buttons==AK_L);
    puts("PASS BLE-to-USB handoff releases/quarantines held input; release then new press is required");

    i.usb_mounted=false;i.usb_suspended=true;
    assert(ak_link_update(&p,&c,i,AK_L,++time_ms,before,&p));assert(p.active==LINK_NONE && !c.hid_buttons);
    unsigned calls=handoffs;session=c.session;i.ble_generation++;
    assert(!ak_link_update(&p,&c,i,AK_L,++time_ms,before,&p));assert(handoffs==calls && c.session==session);
    i.usb_suspended=false;assert(ak_link_update(&p,&c,i,AK_L,++time_ms,before,&p));assert(p.active==LINK_BLE && !c.hid_buttons);
    puts("PASS suspended USB prevents rerouting to BLE; wireless background changes do not replay input");

    key(&c,0);grant(&c);key(&c,AK_VOICE);
    assert(ak_command(&c,c.session,3,AK_RECORD,1,++time_ms)==AK_OK);
    time_ms+=50;ak_poll(&c,AK_VOICE,time_ms);assert(c.recording && c.mic_ready);
    session=c.session;i.ble_generation++;
    assert(ak_link_update(&p,&c,i,AK_VOICE,++time_ms,before,&p));
    assert(!c.recording && !c.mic_ready && !c.mic_power && !c.haptic && !c.host_connected);
    assert(ak_command(&c,session,4,AK_RECORD,1,++time_ms)==AK_BAD_SESSION);
    grant(&c);assert(ak_command(&c,c.session,3,AK_RECORD,1,++time_ms)==AK_HELD);
    key(&c,0);key(&c,AK_VOICE);assert(ak_command(&c,c.session,4,AK_RECORD,1,++time_ms)==AK_OK);
    puts("PASS BLE subscription/encryption generation change cuts recording and rejects stale or still-held grants");

    i.usb_mounted=true;assert(ak_link_update(&p,&c,i,AK_VOICE,++time_ms,before,&p));
    assert(!c.mic_power && !c.recording);key(&c,0);grant(&c);
    assert(ak_command(&c,c.session,3,AK_DRAW,1,++time_ms)==AK_OK && c.drawing);
    i.usb_mounted=false;i.ble_connected=false;
    assert(ak_link_update(&p,&c,i,0,++time_ms,before,&p));assert(p.active==LINK_NONE && !c.drawing && !c.haptic && !c.host_connected);
    session=c.session;i.ble_connected=true;i.ble_generation++;
    assert(ak_link_update(&p,&c,i,AK_R,++time_ms,before,&p));assert(!c.hid_buttons && c.blocked&AK_R && c.session!=session);
    puts("PASS disconnect cancels drawing; a key pressed offline is quarantined after reconnect");
    return 0;
}

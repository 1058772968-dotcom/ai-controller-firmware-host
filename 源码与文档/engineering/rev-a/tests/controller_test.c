#include "controller.h"
#include "board_config.h"
#include <assert.h>
#include <stdio.h>
#include <stdint.h>

static unsigned edges, resets, centers, count;
static uint32_t now;
static void capture(void *context,const ak_event *e) {
    (void)context; count++;
    if(e->type==AK_EDGE)edges++;
    if(e->type==AK_RESET_INPUT)resets++;
    if(e->type==AK_CENTER)centers++;
}
static void init(ak_controller *c,uint32_t session,uint8_t held,uint32_t start) {
    now=start;ak_init(c,session,held,now,capture,0);
}
static void tick(ak_controller *c,uint8_t mask,uint32_t ms) {
    now+=ms;ak_poll(c,mask,now);
}
static void key(ak_controller *c,uint8_t mask) {
    tick(c,mask,1);tick(c,mask,AK_DEBOUNCE_MS);
}
static ak_result cmd(ak_controller *c,uint32_t seq,uint8_t command,uint8_t value) {
    return ak_command(c,c->session,seq,command,value,++now);
}
int main(void) {
    ak_controller c;
    init(&c,42,0,0);
    assert(AK_DEBOUNCE_MS>20); /* Manufacturer endurance bounce limit: 20 ms. */
    tick(&c,AK_L,1);tick(&c,AK_L,19);assert(c.hid_buttons==0);
    tick(&c,0,1);tick(&c,AK_L,1);tick(&c,AK_L,AK_DEBOUNCE_MS-1);
    assert(c.hid_buttons==0 && edges==0);
    tick(&c,AK_L,1);assert(c.hid_buttons==AK_L && edges==1);
    key(&c,AK_L|AK_R);assert(c.hid_buttons==(AK_L|AK_R));
    tick(&c,0,1);tick(&c,0,20);assert(c.hid_buttons==(AK_L|AK_R));
    tick(&c,AK_L|AK_R,1);tick(&c,0,1);tick(&c,0,AK_DEBOUNCE_MS);
    assert(c.hid_buttons==0 && edges==3);
    puts("PASS rated 20 ms press/release bounce; simultaneous mouse buttons; no duplicate edges");

    init(&c,42,AK_L|AK_VOICE,0);
    tick(&c,AK_L|AK_VOICE,50);assert(c.hid_buttons==0 && !c.mic_power);
    key(&c,0);key(&c,AK_L);assert(c.hid_buttons==AK_L);
    puts("PASS boot-held keys require release before activation");

    init(&c,43,0,0);
    key(&c,AK_L|AK_VOICE); /* Pressed while no transport was active. */
    ak_disconnect(&c,++now); /* Transport selection/resume boundary. */
    tick(&c,AK_L|AK_VOICE,100);assert(c.hid_buttons==0 && !c.mic_power);
    key(&c,0);key(&c,AK_L);assert(c.hid_buttons==AK_L);
    puts("PASS held keys are quarantined at transport resume until release");

    init(&c,42,0,0);
    assert(cmd(&c,1,AK_HELLO,0)==AK_OK);
    key(&c,AK_L);assert(cmd(&c,2,AK_CLAIM,0)==AK_HELD);
    key(&c,0);assert(cmd(&c,3,AK_CLAIM,0)==AK_OK);
    key(&c,AK_L);assert(c.hid_buttons==0 && c.owner==AK_HOST);
    assert(cmd(&c,4,AK_RELEASE,0)==AK_OK);
    tick(&c,AK_L,30);assert(c.hid_buttons==0);
    key(&c,0);key(&c,AK_R);assert(c.hid_buttons==AK_R);
    puts("PASS ownership ACK gates HID; no click replay after return");

    key(&c,0);assert(cmd(&c,5,AK_CLAIM,0)==AK_OK);
    assert(cmd(&c,6,AK_RECORD,1)==AK_HELD);
    key(&c,AK_VOICE);assert(cmd(&c,7,AK_RECORD,1)==AK_OK);
    assert(c.mic_power && !c.mic_ready);
    uint32_t started=now;
    assert(cmd(&c,8,AK_DRAW,1)==AK_CONFLICT);
    assert(cmd(&c,9,AK_FEEDBACK,1)==AK_CONFLICT && !c.haptic);
    tick(&c,AK_VOICE,started+49-now);assert(!c.mic_ready);
    tick(&c,AK_VOICE,1);assert(c.mic_ready);
    tick(&c,0,1);assert(!c.mic_power && !c.recording);
    assert(c.buttons&AK_VOICE); /* Privacy cutoff precedes debounced edge. */
    puts("PASS trigger and grant; mic warmup; raw release cutoff; mutual exclusion");

    key(&c,0);assert(cmd(&c,10,AK_DRAW,1)==AK_OK);
    key(&c,AK_VOICE);assert(cmd(&c,11,AK_RECORD,1)==AK_CONFLICT);
    assert(cmd(&c,12,AK_DRAW,0)==AK_OK);
    assert(!c.recording && !c.haptic);
    puts("PASS rejected recording is not queued for later");

    assert(cmd(&c,13,AK_FEEDBACK,1)==AK_OK);
    tick(&c,AK_VOICE,79);assert(c.haptic);
    tick(&c,AK_VOICE,1);assert(!c.haptic);
    assert(cmd(&c,14,AK_RECORD,1)==AK_OK);
    assert(cmd(&c,15,AK_KEEPALIVE,0)==AK_OK);
    tick(&c,AK_VOICE,AK_HOST_LEASE_MS);assert(!c.mic_power && !c.host_connected && c.owner==AK_POINTER);
    assert(c.session!=42);
    assert(ak_command(&c,42,16,AK_CLAIM,0,++now)==AK_BAD_SESSION);
    assert(cmd(&c,1,AK_HELLO,0)==AK_OK);
    assert(cmd(&c,2,AK_CLAIM,0)==AK_OK);
    assert(cmd(&c,3,AK_RECORD,1)==AK_HELD);
    puts("PASS haptic limit; lease timeout; stale session; reconnect-held trigger");

    assert(cmd(&c,4,AK_RECENTER,0)==AK_OK);
    unsigned previous=centers;
    assert(cmd(&c,4,AK_RECENTER,0)==AK_STALE);
    assert(cmd(&c,3,AK_RECENTER,0)==AK_STALE);assert(centers==previous);
    assert(cmd(&c,5,99,0)==AK_INVALID);
    puts("PASS duplicate, reordered and invalid commands have no repeated effect");

    init(&c,123,0,UINT32_MAX-100);
    assert(cmd(&c,UINT32_MAX,AK_HELLO,0)==AK_OK);
    assert(cmd(&c,0,AK_CLAIM,0)==AK_OK);
    key(&c,AK_VOICE);assert(cmd(&c,1,AK_RECORD,1)==AK_OK);
    tick(&c,AK_VOICE,50);assert(c.mic_ready);
    assert(cmd(&c,2,AK_KEEPALIVE,0)==AK_OK);
    tick(&c,AK_VOICE,AK_HOST_LEASE_MS-1);assert(c.mic_power);
    tick(&c,AK_VOICE,1);assert(!c.mic_power);
    puts("PASS timer and command sequence wraparound");

    init(&c,234,0,0);
    cmd(&c,1,AK_HELLO,0);cmd(&c,2,AK_CLAIM,0);key(&c,AK_VOICE);
    assert(cmd(&c,3,AK_RECORD,1)==AK_OK);ak_fault(&c,7,++now);
    assert(!c.mic_power && !c.haptic && !c.host_connected && c.hid_buttons==0);
    puts("PASS driver fault fails closed");
    init(&c,345,0,0);c.hardware_faults=2;
    cmd(&c,1,AK_HELLO,0);cmd(&c,2,AK_CLAIM,0);key(&c,AK_VOICE);
    assert(cmd(&c,3,AK_RECORD,1)==AK_INVALID);assert(!c.mic_power);
    ak_disconnect(&c,++now);assert(c.hardware_faults==2);
    puts("PASS latched capture fault blocks recording after reconnect");
    printf("All controller checks passed; %u events inspected, %u resets\n",count,resets);
    return 0;
}

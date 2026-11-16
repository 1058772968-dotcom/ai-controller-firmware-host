#include "controller.h"
#include "board_config.h"
#include <string.h>

static uint32_t elapsed(uint32_t now, uint32_t before) { return now-before; }
static bool newer(uint32_t seq, uint32_t last) {
    const uint32_t distance=seq-last;
    return distance!=0 && distance<UINT32_C(0x80000000);
}
static void event(ak_controller *c, uint8_t type, uint8_t value) {
    ak_event e={c->session, ++c->event_sequence, c->now_ms, type,
                (uint8_t)(c->buttons & (uint8_t)~c->blocked), c->owner, value};
    if(c->emit) c->emit(c->context,&e);
}
static void stop_mic(ak_controller *c) {
    const bool was_on=c->recording || c->mic_power;
    c->recording=false; c->mic_power=false; c->mic_ready=false;
    if(was_on) event(c,AK_MIC,0);
}
static void stop_haptic(ak_controller *c) {
    if(c->haptic) { c->haptic=false; event(c,AK_HAPTIC,0); }
}
static void release_inputs(ak_controller *c) {
    stop_mic(c); stop_haptic(c);
    if(c->drawing) { c->drawing=false; event(c,AK_DRAW_STATE,0); }
    c->blocked |= c->buttons | c->raw;
    c->hid_buttons=0; c->owner=AK_POINTER;
    event(c,AK_RESET_INPUT,0);
    event(c,AK_OWNER,AK_POINTER);
}
void ak_init(ak_controller *c,uint32_t session,uint8_t boot_buttons,uint32_t now_ms,ak_emit emit,void *context) {
    memset(c,0,sizeof(*c));
    c->session=session ? session : 1;
    c->now_ms=now_ms;c->emit=emit;c->context=context;
    c->raw=c->buttons=c->blocked=boot_buttons & AK_ALL;
    for(unsigned i=0;i<4;i++) c->changed_ms[i]=now_ms;
}
bool ak_pointer_allowed(const ak_controller *c) {
    return c->owner==AK_POINTER && !c->recording && !c->drawing;
}
bool ak_mic_permitted(const ak_controller *c) {
    return c->recording && c->mic_power && c->mic_ready && c->owner==AK_HOST && c->host_connected &&
           (c->raw & c->buttons & (uint8_t)~c->blocked & AK_VOICE);
}
void ak_mic_abort(ak_controller *c,uint32_t now_ms) { c->now_ms=now_ms; stop_mic(c); }
void ak_poll(ak_controller *c,uint8_t raw_buttons,uint32_t now_ms) {
    c->now_ms=now_ms;raw_buttons &= AK_ALL;
    if(c->host_connected && elapsed(now_ms,c->lease_ms)>=AK_HOST_LEASE_MS) {
        const bool active=c->owner==AK_HOST || c->recording || c->drawing || c->haptic;
        c->host_connected=false;
        if(active) {
            release_inputs(c);
            c->session++; if(!c->session) c->session=1;
            c->event_sequence=0; c->command_seen=false;
        }
    }
    /* A physical release cuts microphone power without waiting for debounce. */
    if(!(raw_buttons & AK_VOICE)) stop_mic(c);
    for(unsigned i=0;i<4;i++) {
        uint8_t bit=(uint8_t)(1u<<i);
        if((raw_buttons ^ c->raw) & bit) c->changed_ms[i]=now_ms;
    }
    c->raw=raw_buttons;
    uint8_t previous=c->buttons;
    for(unsigned i=0;i<4;i++) {
        uint8_t bit=(uint8_t)(1u<<i);
        if(elapsed(now_ms,c->changed_ms[i])>=AK_DEBOUNCE_MS) {
            c->buttons=(c->buttons & (uint8_t)~bit) | (raw_buttons & bit);
            if(!(raw_buttons & bit)) c->blocked &= (uint8_t)~bit;
        }
    }
    if(c->buttons != previous) event(c,AK_EDGE,(uint8_t)(c->buttons ^ previous));
    c->hid_buttons=ak_pointer_allowed(c) ? (c->buttons & (uint8_t)~c->blocked & (AK_L|AK_R)) : 0;
    if(c->recording && c->mic_power && !c->mic_ready && elapsed(now_ms,c->mic_started_ms)>=AK_MIC_SETTLE_MS) {
        c->mic_ready=true;event(c,AK_MIC,2);
    }
    if(c->haptic && elapsed(now_ms,c->haptic_started_ms)>=80) stop_haptic(c);
}
ak_result ak_command(ak_controller *c,uint32_t session,uint32_t sequence,uint8_t command,uint8_t value,uint32_t now_ms) {
    ak_poll(c,c->raw,now_ms);
    if(session!=c->session) return AK_BAD_SESSION;
    if(c->command_seen && !newer(sequence,c->command_sequence)) return AK_STALE;
    if(command<AK_HELLO || command>AK_RECENTER || value>1) return AK_INVALID;
    if(command!=AK_HELLO && !c->host_connected) return AK_NOT_CONNECTED;
    /* Syntactically valid commands are consumed even if an interlock rejects them. */
    c->command_seen=true;c->command_sequence=sequence;
    ak_result result=AK_OK;
    switch(command) {
    case AK_HELLO:
        c->host_connected=true;c->lease_ms=now_ms;
        break;
    case AK_KEEPALIVE: c->lease_ms=now_ms; break;
    case AK_CLAIM:
        if((c->buttons | c->raw) & (AK_L|AK_R)) { result=AK_HELD;break; }
        c->blocked|=c->buttons|c->raw;
        c->owner=AK_HOST;c->hid_buttons=0;c->lease_ms=now_ms;
        event(c,AK_OWNER,AK_HOST);break;
    case AK_RELEASE: release_inputs(c); c->lease_ms=now_ms; break;
    case AK_RECORD:
        if(!value) { stop_mic(c); break; }
        if(c->hardware_faults & 2) {result=AK_INVALID;break;}
        if(c->owner!=AK_HOST || c->drawing) { result=AK_CONFLICT;break; }
        if(!(c->buttons & c->raw & (uint8_t)~c->blocked & AK_VOICE)) { result=AK_HELD;break; }
        if(!c->recording) {
            stop_haptic(c);c->recording=true;c->mic_power=true;c->mic_ready=false;
            c->mic_started_ms=now_ms;event(c,AK_MIC,1);
        }
        break;
    case AK_DRAW:
        if(value && (c->owner!=AK_HOST || c->recording)) { result=AK_CONFLICT;break; }
        if(value) stop_haptic(c);
        c->drawing=value;event(c,AK_DRAW_STATE,value);break;
    case AK_FEEDBACK:
        if(value && (c->hardware_faults & 4)) { result=AK_INVALID;break; }
        if(c->recording || c->drawing || c->owner!=AK_HOST) { result=AK_CONFLICT;break; }
        c->haptic=value;if(value)c->haptic_started_ms=now_ms;
        event(c,AK_HAPTIC,value);break;
    case AK_RECENTER:
        if(c->recording || c->drawing) { result=AK_CONFLICT;break; }
        event(c,AK_CENTER,0);break;
    default: result=AK_INVALID;break;
    }
    event(c,AK_ACK,(uint8_t)result);
    return result;
}
void ak_disconnect(ak_controller *c,uint32_t now_ms) {
    c->now_ms=now_ms;c->host_connected=false;release_inputs(c);
    c->session++;if(!c->session)c->session=1;
    c->event_sequence=0;c->command_seen=false;
}
void ak_fault(ak_controller *c,uint8_t code,uint32_t now_ms) {
    ak_disconnect(c,now_ms);event(c,AK_FAULT,code);
}

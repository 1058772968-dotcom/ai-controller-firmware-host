#ifndef AIKEY_CONTROLLER_H
#define AIKEY_CONTROLLER_H
#include <stdbool.h>
#include <stdint.h>

enum { AK_L=1, AK_R=2, AK_VOICE=4, AK_SIDE=8, AK_ALL=15 };
typedef enum { AK_POINTER=0, AK_HOST=1 } ak_owner;
typedef enum { AK_HELLO=1, AK_CLAIM, AK_KEEPALIVE, AK_RELEASE,
               AK_RECORD, AK_DRAW, AK_FEEDBACK, AK_RECENTER } ak_command_type;
typedef enum { AK_EDGE=1, AK_OWNER, AK_MIC, AK_DRAW_STATE, AK_HAPTIC,
               AK_RESET_INPUT, AK_CENTER, AK_ACK, AK_FAULT } ak_event_type;
typedef enum { AK_OK=0, AK_BAD_SESSION, AK_STALE, AK_NOT_CONNECTED,
               AK_HELD, AK_CONFLICT, AK_INVALID } ak_result;

typedef struct {
    uint32_t session, sequence, time_ms;
    uint8_t type, buttons, owner, value;
} ak_event;
typedef void (*ak_emit)(void *context, const ak_event *event);
typedef struct {
    uint32_t session, command_sequence, event_sequence, now_ms, lease_ms;
    uint32_t changed_ms[4], mic_started_ms, haptic_started_ms;
    uint8_t raw, buttons, blocked, owner, hid_buttons, hardware_faults;
    uint16_t battery_mv, soc_q8;
    bool battery_valid, haptic_calibrated;
    bool host_connected, command_seen, recording, drawing, mic_power, mic_ready, haptic, calibrated;
    ak_emit emit;
    void *context;
} ak_controller;

void ak_init(ak_controller *, uint32_t session, uint8_t boot_buttons, uint32_t now_ms, ak_emit, void *);
void ak_poll(ak_controller *, uint8_t raw_buttons, uint32_t now_ms);
ak_result ak_command(ak_controller *, uint32_t session, uint32_t sequence,
                     uint8_t command, uint8_t value, uint32_t now_ms);
void ak_disconnect(ak_controller *, uint32_t now_ms);
/* 隐私闸门（规格 AUD 02）：按住 V + HOST 归属 + 已允许录音 + 麦克风稳定，四项同时成立才放行 PCM */
bool ak_mic_permitted(const ak_controller *c);
/* 采集故障或队列溢出：结束录音，等主机重新请求 */
void ak_mic_abort(ak_controller *c, uint32_t now_ms);
void ak_fault(ak_controller *, uint8_t code, uint32_t now_ms);
bool ak_pointer_allowed(const ak_controller *);
#endif

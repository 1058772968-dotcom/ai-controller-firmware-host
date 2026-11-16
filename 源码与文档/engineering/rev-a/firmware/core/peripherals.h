#ifndef AIKEY_PERIPHERALS_H
#define AIKEY_PERIPHERALS_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef struct {
    void *context;
    bool (*read)(void *,uint8_t,uint8_t,uint8_t *,size_t);
    bool (*write)(void *,uint8_t,uint8_t,const uint8_t *,size_t);
    void (*enable_haptic)(void *,bool);
} ak_i2c_io;
typedef enum { AK_HAP_IDLE,AK_HAP_WAKE,AK_HAP_CAL,AK_HAP_READY,AK_HAP_PLAY_WAKE,AK_HAP_PLAY,AK_HAP_FAILED } ak_hap_state;
typedef struct {
    ak_i2c_io io;
    ak_hap_state state;
    uint32_t since,quiet_since,last_gauge,last_status;
    uint16_t battery_mv,soc_q8;
    uint8_t cal_comp,cal_bemf,cal_feedback;
    bool battery_valid,gauge_failed,enabled,request_seen;
} ak_peripherals;
void ak_peripherals_init(ak_peripherals *,ak_i2c_io,uint32_t);
/* inhibit is based on raw voice/side keys as well as recording/drawing state. */
void ak_peripherals_step(ak_peripherals *,uint32_t,bool inhibit,bool feedback);
bool ak_haptic_ready(const ak_peripherals *);
#endif

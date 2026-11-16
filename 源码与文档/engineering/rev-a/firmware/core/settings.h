#ifndef AIKEY_SETTINGS_H
#define AIKEY_SETTINGS_H
#include <stdbool.h>
#include <stdint.h>
#define AK_SETTINGS_SIZE 160
#define AK_SETTINGS_FRAME_SIZE 32
enum {AK_CFG_BEGIN=1,AK_CFG_CHUNK,AK_CFG_COMMIT,AK_CFG_ABORT,AK_CFG_STATUS,AK_CFG_FORGET_BOND};
enum {AK_CFG_OK=0,AK_CFG_FRAME,AK_CFG_SESSION,AK_CFG_BUSY,AK_CFG_ORDER,AK_CFG_VALUE,AK_CFG_STORAGE};
typedef struct {
    uint8_t bytes[AK_SETTINGS_SIZE];uint32_t session,transaction;
    uint16_t received;bool active;
} ak_settings_stage;
typedef struct {
    void *context;
    bool (*save)(void *,const uint8_t [AK_SETTINGS_SIZE]);
    bool (*forget_bond)(void *);
} ak_settings_io;
bool ak_settings_valid(const uint8_t [AK_SETTINGS_SIZE]);
void ak_settings_reset(ak_settings_stage *);
/* USB report ID 3 only; not a BLE control command. Status does not expose keys. */
bool ak_settings_process(ak_settings_stage *,ak_settings_io,uint32_t current_session,
                         bool idle,bool configured,const uint8_t *,unsigned length,
                         uint8_t reply[AK_SETTINGS_FRAME_SIZE]);
#endif

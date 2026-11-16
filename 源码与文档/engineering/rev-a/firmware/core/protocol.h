#ifndef AIKEY_PROTOCOL_H
#define AIKEY_PROTOCOL_H
#include "controller.h"
#include <stddef.h>
#define AK_WIRE_SIZE 32
typedef struct { uint32_t session,sequence;uint8_t command,value; } ak_wire_command;
uint16_t ak_crc16(const uint8_t *,size_t);
bool ak_decode_command(const uint8_t *,size_t,ak_wire_command *);
void ak_encode_state(const ak_controller *,const ak_event *,uint8_t out[AK_WIRE_SIZE]);
void ak_encode_motion(const ak_controller *,int16_t x,int16_t y,uint8_t out[AK_WIRE_SIZE]);
#endif

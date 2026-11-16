/* Host-only adapter around the exact firmware core. No ESP peripheral emulation. */
#include "controller.h"
#include "protocol.h"
#include <string.h>
static ak_controller state;
static unsigned read_index,write_index;
static uint8_t events[256][AK_WIRE_SIZE];
static void emit(void *ctx,const ak_event *event) {
    (void)ctx;
    if(write_index-read_index>=256) { read_index=write_index;ak_disconnect(&state,state.now_ms);return; }
    ak_encode_state(&state,event,events[write_index++%256]);
}
void ak_sim_init(uint32_t session,uint8_t buttons,uint32_t now) {
    read_index=write_index=0;ak_init(&state,session,buttons,now,emit,0);
}
void ak_sim_poll(uint8_t buttons,uint32_t now) {ak_poll(&state,buttons,now);}
int ak_sim_command(const uint8_t *packet,uint32_t now) {
    ak_wire_command command;
    if(!ak_decode_command(packet,AK_WIRE_SIZE,&command))return -1;
    return ak_command(&state,command.session,command.sequence,command.command,command.value,now);
}
int ak_sim_pop(uint8_t *packet) {
    if(read_index==write_index)return 0;
    memcpy(packet,events[read_index++%256],AK_WIRE_SIZE);return 1;
}
void ak_sim_state(uint8_t *packet) {ak_encode_state(&state,0,packet);}
void ak_sim_disconnect(uint32_t now) {ak_disconnect(&state,now);}

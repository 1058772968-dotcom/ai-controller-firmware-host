#include "protocol.h"
#include <string.h>
static uint32_t get32(const uint8_t *p) { return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static void put32(uint8_t *p,uint32_t v) { for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i)); }
uint16_t ak_crc16(const uint8_t *data,size_t n) {
    uint16_t crc=0xffff;
    for(size_t i=0;i<n;i++) { crc^=(uint16_t)data[i]<<8; for(unsigned bit=0;bit<8;bit++)crc=(crc & 0x8000)?(uint16_t)((crc<<1)^0x1021):(uint16_t)(crc<<1); }
    return crc;
}
bool ak_decode_command(const uint8_t *data,size_t n,ak_wire_command *out) {
    if(!data || !out || n!=AK_WIRE_SIZE || data[0]!=1 || data[1]<AK_HELLO || data[1]>AK_RECENTER || data[16]>1)return false;
    uint16_t crc=ak_crc16(data,30);
    if(data[30]!=(uint8_t)crc || data[31]!=(uint8_t)(crc>>8))return false;
    /* Reserved bytes must be zero, so extensions cannot silently change meaning. */
    if(data[2] || data[3])return false;
    for(unsigned i=12;i<30;i++)if(i!=16 && data[i])return false;
    out->command=data[1];out->session=get32(data+4);out->sequence=get32(data+8);out->value=data[16];return true;
}
void ak_encode_state(const ak_controller *c,const ak_event *e,uint8_t out[AK_WIRE_SIZE]) {
    memset(out,0,AK_WIRE_SIZE);out[0]=1;out[1]=e?e->type:0x80;
    out[2]=c->owner;out[3]=c->buttons & (uint8_t)~c->blocked;
    put32(out+4,c->session);put32(out+8,e?e->sequence:c->event_sequence);put32(out+12,c->now_ms);
    out[16]=(uint8_t)((c->host_connected?1:0)|(c->mic_power?2:0)|(c->mic_ready?4:0)|(c->drawing?8:0)|(c->haptic?16:0)|(c->calibrated?32:0));
    out[17]=e?e->value:0;out[18]=c->hid_buttons;out[19]=c->hardware_faults;put32(out+24,c->command_sequence);
    if(!e) {
        out[20]=(uint8_t)c->battery_mv;out[21]=(uint8_t)(c->battery_mv>>8);
        out[22]=(uint8_t)c->soc_q8;out[23]=(uint8_t)(c->soc_q8>>8);
    }
    out[28]=(uint8_t)((c->battery_valid?1:0)|(c->haptic_calibrated?2:0));
    uint16_t crc=ak_crc16(out,30);out[30]=(uint8_t)crc;out[31]=(uint8_t)(crc>>8);
}
void ak_encode_motion(const ak_controller *c,int16_t x,int16_t y,uint8_t out[AK_WIRE_SIZE]) {
    ak_encode_state(c,NULL,out);out[1]=0x81;
    out[20]=(uint8_t)x;out[21]=(uint8_t)((uint16_t)x>>8);out[22]=(uint8_t)y;out[23]=(uint8_t)((uint16_t)y>>8);
    uint16_t crc=ak_crc16(out,30);out[30]=(uint8_t)crc;out[31]=(uint8_t)(crc>>8);
}

#include "protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static void crc(uint8_t *b){uint16_t c=ak_crc16(b,30);b[30]=(uint8_t)c;b[31]=(uint8_t)(c>>8);}
int main(void) {
    assert(ak_crc16((const uint8_t *)"123456789",9)==0x29b1);
    uint8_t good[32]={1,AK_RECORD,0,0,0x78,0x56,0x34,0x12,4};good[16]=1;crc(good);
    ak_wire_command out;
    assert(ak_decode_command(good,32,&out));assert(out.session==0x12345678 && out.sequence==4 && out.command==AK_RECORD && out.value==1);
    for(unsigned n=0;n<32;n++)assert(!ak_decode_command(good,n,&out));
    assert(!ak_decode_command(good,33,&out));
    for(unsigned i=0;i<32;i++)for(unsigned bit=0;bit<8;bit++) {
        uint8_t b[32];memcpy(b,good,32);b[i]^=1u<<bit;
        assert(!ak_decode_command(b,32,&out));
    }
    for(unsigned i=12;i<30;i++)if(i!=16) {uint8_t b[32];memcpy(b,good,32);b[i]=1;crc(b);assert(!ak_decode_command(b,32,&out));}
    good[1]=255;crc(good);assert(!ak_decode_command(good,32,&out));
    ak_controller c;ak_init(&c,0x12345678,0,1234,NULL,NULL);
    uint8_t state[32];ak_encode_state(&c,NULL,state);assert(state[0]==1 && state[1]==0x80 && state[4]==0x78 && state[7]==0x12);
    uint16_t expected=ak_crc16(state,30);assert(state[30]==(uint8_t)expected && state[31]==(uint8_t)(expected>>8));
    c.battery_mv=4021;c.soc_q8=19328;c.battery_valid=true;c.haptic_calibrated=true;
    ak_encode_state(&c,NULL,state);assert(state[20]==0xb5 && state[21]==0x0f && state[22]==0x80 && state[23]==75 && state[28]==3);
    c.battery_valid=false;ak_encode_state(&c,NULL,state);assert(state[28]==2);
    c.hardware_faults=2;c.calibrated=true;ak_encode_motion(&c,-127,99,state);
    assert(state[1]==0x81 && state[19]==2 && (state[16]&32));
    assert(state[20]==0x81 && state[21]==0xff && state[22]==99 && state[23]==0);
    expected=ak_crc16(state,30);assert(state[30]==(uint8_t)expected && state[31]==(uint8_t)(expected>>8));
    puts("PASS CRC reference vector; little-endian command; 256 bit corruptions; truncation/oversize; reserved/unknown commands; state/motion/fault frames");
}

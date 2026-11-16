#include "settings.h"
#include "protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static unsigned saved,forgotten;static bool storage_ok=true;static uint8_t stored[160];
static bool save(void *p,const uint8_t b[160]) {(void)p;if(!storage_ok)return false;memcpy(stored,b,160);saved++;return true;}
static bool forget(void *p) {(void)p;forgotten++;return true;}
static uint8_t blob[160],frame[32],reply[32];static ak_settings_stage stage;
static ak_settings_io io={NULL,save,forget};
static void packet(uint8_t op,unsigned offset) {
    memset(frame,0,32);frame[0]=1;frame[1]=op;frame[2]=(uint8_t)offset;frame[3]=(uint8_t)(offset>>8);frame[4]=42;frame[8]=73;
    if(op==AK_CFG_BEGIN)frame[12]=160;
    if(op==AK_CFG_CHUNK && offset<160)memcpy(frame+12,blob+offset,16);
    uint16_t crc=ak_crc16(frame,30);frame[30]=(uint8_t)crc;frame[31]=(uint8_t)(crc>>8);
}
static uint8_t call(uint8_t op,unsigned offset) {packet(op,offset);assert(ak_settings_process(&stage,io,42,true,false,frame,32,reply));return reply[2];}
static void upload(void) {assert(call(AK_CFG_BEGIN,0)==0);for(unsigned i=0;i<160;i+=16)assert(call(AK_CFG_CHUNK,i)==0);}
int main(void) {
    blob[0]=1;blob[1]=4;blob[2]=8;memcpy(blob+4,"test",4);memcpy(blob+36,"password",8);memcpy(blob+100,"192.168.1.2",11);blob[116]=0xbe;blob[117]=0x22;memset(blob+118,0x5a,32);
    assert(ak_settings_valid(blob));upload();assert(call(AK_CFG_COMMIT,160)==0 && saved==1 && !memcmp(stored,blob,160));
    for(unsigned i=0;i<160;i++)assert(!stage.bytes[i]);
    assert(call(AK_CFG_COMMIT,160)==AK_CFG_ORDER && saved==1);
    puts("PASS complete transaction saved exactly once; staging credentials zeroed; duplicate commit rejected");
    assert(call(AK_CFG_BEGIN,0)==0);assert(call(AK_CFG_CHUNK,16)==AK_CFG_ORDER);assert(call(AK_CFG_CHUNK,0)==0);assert(call(AK_CFG_CHUNK,0)==AK_CFG_ORDER);
    assert(call(AK_CFG_COMMIT,16)==AK_CFG_ORDER);assert(!stage.active);assert(saved==1);
    puts("PASS missing/reordered/duplicated chunks cannot become persisted settings");
    assert(call(AK_CFG_BEGIN,0)==0);packet(AK_CFG_CHUNK,0);assert(ak_settings_process(&stage,io,43,true,false,frame,32,reply));assert(reply[2]==AK_CFG_SESSION && !stage.active);
    assert(call(AK_CFG_BEGIN,0)==0);packet(AK_CFG_CHUNK,0);assert(ak_settings_process(&stage,io,42,false,false,frame,32,reply));assert(reply[2]==AK_CFG_BUSY && !stage.active);
    assert(call(AK_CFG_BEGIN,0)==0);packet(AK_CFG_CHUNK,0);frame[15]^=1;assert(ak_settings_process(&stage,io,42,true,false,frame,32,reply));assert(reply[2]==AK_CFG_FRAME && !stage.received);
    puts("PASS stale session, active operation and corrupted frame do not alter saved settings");
    storage_ok=false;upload();assert(call(AK_CFG_COMMIT,160)==AK_CFG_STORAGE && saved==1 && !stage.active);storage_ok=true;
    blob[118]=0;memset(blob+118,0,32);assert(!ak_settings_valid(blob));memset(blob+118,0x5a,32);
    blob[2]=7;assert(!ak_settings_valid(blob));blob[2]=8;memcpy(blob+100,"224.168.1.2",11);assert(!ak_settings_valid(blob));memcpy(blob+100,"192.168.1.2",11);
    blob[150]=1;assert(!ak_settings_valid(blob));blob[150]=0;
    assert(call(AK_CFG_FORGET_BOND,0)==0 && forgotten==1);assert(call(AK_CFG_STATUS,0)==0);
    assert(!memcmp(reply+16,(uint8_t[14]){0},14));
    puts("PASS storage failure, invalid network/key fields and reserved data fail closed; status exposes no credentials");
    return 0;
}

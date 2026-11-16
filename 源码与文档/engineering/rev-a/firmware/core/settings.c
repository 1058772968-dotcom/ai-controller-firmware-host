#include "settings.h"
#include "protocol.h"
#include <string.h>
static uint16_t get16(const uint8_t *p) {return (uint16_t)p[0]|(uint16_t)p[1]<<8;}
static uint32_t get32(const uint8_t *p) {return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put32(uint8_t *p,uint32_t v) {for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
static bool zero(const uint8_t *p,unsigned n) {for(unsigned i=0;i<n;i++)if(p[i])return false;return true;}
void ak_settings_reset(ak_settings_stage *s) {
    /* Volatile stores prevent removal of credential zeroization. */
    volatile uint8_t *p=(volatile uint8_t *)s;for(unsigned i=0;i<sizeof(*s);i++)p[i]=0;
}
bool ak_settings_valid(const uint8_t b[AK_SETTINGS_SIZE]) {
    if(!b || b[0]!=1 || b[1]<1 || b[1]>32 || b[2]<8 || b[2]>63 || b[3])return false;
    if(!zero(b+4+b[1],32-b[1]) || !zero(b+36+b[2],64-b[2]) || !zero(b+150,10))return false;
    for(unsigned i=0;i<b[1];i++)if(!b[4+i])return false;
    for(unsigned i=0;i<b[2];i++)if(b[36+i]<32 || b[36+i]>126)return false;
    /* Bounded dotted IPv4, no DNS or multicast/broadcast endpoint. */
    unsigned at=100,octets[4]={0};
    for(unsigned part=0;part<4;part++) {
        unsigned count=0,value=0;
        while(at<116 && b[at]>='0' && b[at]<='9') {value=value*10+b[at++]-'0';count++;}
        if(!count || count>3 || value>255)return false;
        octets[part]=value;
        if(part<3) {if(at>=116 || b[at++]!='.')return false;}
    }
    if(at>=116 || !zero(b+at,116-at) || !octets[0] || octets[0]>=224 || octets[3]==255)return false;
    return get16(b+116)>=1024 && !zero(b+118,32);
}
bool ak_settings_process(ak_settings_stage *s,ak_settings_io io,uint32_t session,
                         bool idle,bool configured,const uint8_t *in,unsigned length,uint8_t out[32]) {
    if(!s || !in || !out || length!=32)return false;
    if(s->session!=session) {ak_settings_reset(s);s->session=session;}
    uint8_t code=AK_CFG_OK,op=in[1];uint32_t tx=get32(in+8);uint16_t offset=get16(in+2);
    bool format=in[0]==1 && op>=AK_CFG_BEGIN && op<=AK_CFG_FORGET_BOND && !in[28] && !in[29] && get16(in+30)==ak_crc16(in,30);
    if(!format)code=AK_CFG_FRAME;
    else if(get32(in+4)!=session)code=AK_CFG_SESSION;
    else if(op!=AK_CFG_STATUS && !idle) {ak_settings_reset(s);s->session=session;code=AK_CFG_BUSY;}
    else if(op==AK_CFG_STATUS) {if(offset || !zero(in+12,16))code=AK_CFG_VALUE;}
    else if(op==AK_CFG_ABORT) {if(offset || !zero(in+12,16))code=AK_CFG_VALUE;else {ak_settings_reset(s);s->session=session;}}
    else if(op==AK_CFG_FORGET_BOND) {
        if(offset || !tx || !zero(in+12,16))code=AK_CFG_VALUE;
        else if(!io.forget_bond || !io.forget_bond(io.context))code=AK_CFG_STORAGE;
    } else if(op==AK_CFG_BEGIN) {
        if(offset || !tx || get16(in+12)!=AK_SETTINGS_SIZE || !zero(in+14,14))code=AK_CFG_VALUE;
        else {ak_settings_reset(s);s->session=session;s->transaction=tx;s->active=true;}
    } else if(!s->active || s->transaction!=tx || s->received!=offset)code=AK_CFG_ORDER;
    else if(op==AK_CFG_CHUNK) {
        if(offset>AK_SETTINGS_SIZE-16)code=AK_CFG_ORDER;
        else {memcpy(s->bytes+offset,in+12,16);s->received+=16;}
    } else if(op==AK_CFG_COMMIT) {
        if(s->received!=AK_SETTINGS_SIZE || !zero(in+12,16))code=AK_CFG_ORDER;
        else if(!ak_settings_valid(s->bytes))code=AK_CFG_VALUE;
        else if(!io.save || !io.save(io.context,s->bytes))code=AK_CFG_STORAGE;
        else configured=true;
        ak_settings_reset(s);s->session=session;
    }
    memset(out,0,32);out[0]=1;out[1]=(uint8_t)(op|0x80);out[2]=code;out[3]=configured;
    put32(out+4,session);put32(out+8,tx);out[12]=(uint8_t)s->received;out[13]=(uint8_t)(s->received>>8);
    out[14]=AK_SETTINGS_SIZE;uint16_t crc=ak_crc16(out,30);out[30]=(uint8_t)crc;out[31]=(uint8_t)(crc>>8);
    return true;
}

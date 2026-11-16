#include "audio_capture.h"
#include "wifi_audio.h"
#include "audio_filter.h"
#include "board_config.h"
#include "driver/i2s_pdm.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"
#include <stdatomic.h>
#include <string.h>
#include <math.h>

static i2s_chan_handle_t rx;
static atomic_bool power_request,permit,failed;
static atomic_bool wireless;
void ak_audio_route(bool value) {atomic_store(&wireless,value);}
static atomic_int gain_q15=32768;
static bool mute[2];static int16_t volume[2];
static void update_gain(void) {
    int gain=(mute[0]||mute[1])?0:(int)(32768.0f*powf(10.0f,(volume[0]+volume[1])/(256.0f*20.0f)));
    atomic_store(&gain_q15,gain);
}
void ak_audio_set(bool power,bool allowed) {
    bool was=atomic_exchange(&permit,allowed && power);
    atomic_store(&power_request,power);
    if(was && !allowed)tud_audio_clear_ep_in_ff();
}
bool ak_audio_failed(void) {return atomic_load(&failed);}
static void capture(void *unused) {
    (void)unused;bool running=false;ak_audio_filter filter={0};
    int16_t raw[480],pcm[160];
    for(;;) {
        bool wanted=atomic_load(&power_request);
        if(wanted!=running) {
            esp_err_t e=wanted?i2s_channel_enable(rx):i2s_channel_disable(rx);
            if(e!=ESP_OK) {atomic_store(&failed,true);atomic_store(&permit,false);vTaskDelay(pdMS_TO_TICKS(10));continue;}
            running=wanted;ak_audio_filter_reset(&filter);memset(raw,0,sizeof(raw));memset(pcm,0,sizeof(pcm));
            tud_audio_clear_ep_in_ff();
        }
        size_t n=160;
        if(running) {
            size_t bytes=0;esp_err_t e=i2s_channel_read(rx,raw,sizeof(raw),&bytes,20);
            if(e!=ESP_OK || bytes!=sizeof(raw)) {
                atomic_store(&failed,true);atomic_store(&permit,false);memset(pcm,0,sizeof(pcm));
            } else n=ak_audio_filter_decimate(&filter,raw,bytes/2,pcm);
        } else {memset(pcm,0,sizeof(pcm));vTaskDelay(pdMS_TO_TICKS(10));}
        if(!atomic_load(&permit)) {memset(pcm,0,sizeof(pcm));ak_audio_filter_reset(&filter);}
        else {int gain=atomic_load(&gain_q15);for(size_t i=0;i<n;i++)pcm[i]=(int16_t)(((int32_t)pcm[i]*gain)/32768);}
        if(atomic_load(&wireless)) {
            if(atomic_load(&permit))ak_wifi_audio_push(pcm,n);
        } else if(tud_mounted())tud_audio_write(pcm,(uint16_t)(n*2));
        memset(raw,0,sizeof(raw));memset(pcm,0,sizeof(pcm));
    }
}
esp_err_t ak_audio_init(void) {
    i2s_chan_config_t channel=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0,I2S_ROLE_MASTER);
    channel.dma_desc_num=4;channel.dma_frame_num=240;
    esp_err_t e=i2s_new_channel(&channel,NULL,&rx);if(e!=ESP_OK)return e;
    i2s_pdm_rx_config_t cfg={.clk_cfg=I2S_PDM_RX_CLK_DEFAULT_CONFIG(48000),
        .slot_cfg=I2S_PDM_RX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_MONO),
        .gpio_cfg={.clk=AK_PIN_PDM_CLK,.din=AK_PIN_PDM_DATA}};
    e=i2s_channel_init_pdm_rx_mode(rx,&cfg);if(e!=ESP_OK)return e;
    return xTaskCreatePinnedToCore(capture,"pdm_capture",4096,NULL,6,NULL,1)==pdPASS?ESP_OK:ESP_ERR_NO_MEM;
}
bool tud_audio_get_req_entity_cb(uint8_t rhport,tusb_control_request_t const *r) {
    unsigned entity=r->wIndex>>8,selector=r->wValue>>8,channel=r->wValue&255;
    if(channel>1 || (r->wIndex&255)!=1)return false;
    if(entity==4 && channel==0) {
        if(selector==AUDIO20_CS_CTRL_SAM_FREQ) {
            if(r->bRequest==AUDIO20_CS_REQ_CUR) {uint32_t hz=16000;return tud_audio_buffer_and_schedule_control_xfer(rhport,r,&hz,4);}
            if(r->bRequest==AUDIO20_CS_REQ_RANGE) {audio20_control_range_4_n_t(1) range={.wNumSubRanges=1,.subrange={{16000,16000,0}}};return tud_audio_buffer_and_schedule_control_xfer(rhport,r,&range,sizeof(range));}
        }
        if(selector==AUDIO20_CS_CTRL_CLK_VALID && r->bRequest==AUDIO20_CS_REQ_CUR) {uint8_t valid=1;return tud_audio_buffer_and_schedule_control_xfer(rhport,r,&valid,1);}
    }
    if(entity==1 && channel==0 && selector==AUDIO20_TE_CTRL_CONNECTOR && r->bRequest==AUDIO20_CS_REQ_CUR) {
        audio20_desc_channel_cluster_t cluster={.bNrChannels=1,.bmChannelConfig=0,.iChannelNames=0};
        return tud_audio_buffer_and_schedule_control_xfer(rhport,r,&cluster,sizeof(cluster));
    }
    if(entity==2) {
        if(selector==AUDIO20_FU_CTRL_MUTE && r->bRequest==AUDIO20_CS_REQ_CUR) {uint8_t value=mute[channel];return tud_audio_buffer_and_schedule_control_xfer(rhport,r,&value,1);}
        if(selector==AUDIO20_FU_CTRL_VOLUME) {
            if(r->bRequest==AUDIO20_CS_REQ_CUR)return tud_audio_buffer_and_schedule_control_xfer(rhport,r,&volume[channel],2);
            if(r->bRequest==AUDIO20_CS_REQ_RANGE) {audio20_control_range_2_n_t(1) range={.wNumSubRanges=1,.subrange={{-60*256,0,256}}};return tud_audio_buffer_and_schedule_control_xfer(rhport,r,&range,sizeof(range));}
        }
    }
    return false;
}
bool tud_audio_set_req_entity_cb(uint8_t rhport,tusb_control_request_t const *r,uint8_t *data) {
    (void)rhport;unsigned entity=r->wIndex>>8,selector=r->wValue>>8,channel=r->wValue&255;
    if((r->wIndex&255)!=1 || entity!=2 || channel>1 || r->bRequest!=AUDIO20_CS_REQ_CUR)return false;
    if(selector==AUDIO20_FU_CTRL_MUTE && r->wLength==1 && data[0]<=1)mute[channel]=data[0];
    else if(selector==AUDIO20_FU_CTRL_VOLUME && r->wLength==2) {
        int16_t v=(int16_t)((uint16_t)data[0]|(uint16_t)data[1]<<8);
        if(v>0 || v<-60*256 || v%256)return false;
        volume[channel]=v;
    } else return false;
    update_gain();return true;
}

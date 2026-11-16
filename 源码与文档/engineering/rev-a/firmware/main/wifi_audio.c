#include "wifi_audio.h"
#include "audio_wire.h"
#include "settings_store.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_tls.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

typedef struct {uint32_t session,stream;bool enabled,permit;} audio_context;
typedef struct {uint32_t session,stream;uint16_t count;int16_t pcm[AK_AUDIO_SAMPLES];} audio_chunk;
static portMUX_TYPE lock=portMUX_INITIALIZER_UNLOCKED;
static audio_context desired;
static atomic_bool ip_ready,ready,fault;
static atomic_uint ready_session;
static QueueHandle_t chunks;
static char identity[13],host[16];static uint16_t port;static uint8_t psk[32];
static audio_context snapshot(void) {audio_context c;portENTER_CRITICAL(&lock);c=desired;portEXIT_CRITICAL(&lock);return c;}
static void zero(void *p,size_t n) {volatile uint8_t *b=p;while(n--)*b++=0;}
void ak_wifi_audio_context(uint32_t session,bool enabled,bool permit) {
    bool discard;
    portENTER_CRITICAL(&lock);
    discard=desired.session!=session || !enabled || (desired.permit&&!permit);
    if(permit && (!desired.permit || desired.session!=session)) {desired.stream++;if(!desired.stream)desired.stream=1;}
    desired.session=session;desired.enabled=enabled;desired.permit=enabled&&permit;
    portEXIT_CRITICAL(&lock);
    if(discard && chunks)xQueueReset(chunks);
}
bool ak_wifi_audio_ready(uint32_t session) {return atomic_load(&ready) && atomic_load(&ready_session)==session;}
bool ak_wifi_audio_take_fault(void) {return atomic_exchange(&fault,false);}
void ak_wifi_audio_push(const int16_t *pcm,size_t count) {
    audio_context c=snapshot();if(!c.enabled || !c.permit)return;
    if(!chunks || !ak_wifi_audio_ready(c.session) || !pcm || !count || count>AK_AUDIO_SAMPLES) {atomic_store(&fault,true);return;}
    audio_chunk chunk={.session=c.session,.stream=c.stream,.count=(uint16_t)count};memcpy(chunk.pcm,pcm,count*2);
    if(xQueueSend(chunks,&chunk,0)!=pdTRUE)atomic_store(&fault,true);
    zero(&chunk,sizeof(chunk));
}
static void event(void *arg,esp_event_base_t base,int32_t id,void *data) {
    (void)arg;(void)data;
    if(base==WIFI_EVENT && id==WIFI_EVENT_STA_START)esp_wifi_connect();
    if(base==WIFI_EVENT && id==WIFI_EVENT_STA_DISCONNECTED) {
        atomic_store(&ip_ready,false);if(atomic_exchange(&ready,false))atomic_store(&fault,true);esp_wifi_connect();
    }
    if(base==IP_EVENT && id==IP_EVENT_STA_GOT_IP)atomic_store(&ip_ready,true);
}
static bool exchange(esp_tls_t *tls,uint8_t kind,uint32_t session,uint32_t stream,uint32_t seq,const int16_t *pcm,size_t count) {
    uint8_t bytes[AK_AUDIO_PACKET],ack[AK_AUDIO_HEADER];size_t size=ak_audio_frame(bytes,sizeof(bytes),kind,session,stream,seq,pcm,count),at=0;
    if(!size)return false;
    while(at<size) {ssize_t n=esp_tls_conn_write(tls,bytes+at,size-at);if(n<=0) {zero(bytes,sizeof(bytes));return false;}at+=(size_t)n;}
    zero(bytes,sizeof(bytes));at=0;
    while(at<sizeof(ack)) {ssize_t n=esp_tls_conn_read(tls,ack+at,sizeof(ack)-at);if(n<=0)return false;at+=(size_t)n;}
    return ak_audio_ack(ack,sizeof(ack),session,stream,seq);
}
static void sender(void *unused) {
    (void)unused;
    for(;;) {
        audio_context c=snapshot();
        if(!c.enabled || !c.session || !atomic_load(&ip_ready)) {vTaskDelay(pdMS_TO_TICKS(100));continue;}
        esp_tls_t *tls=esp_tls_init();if(!tls) {vTaskDelay(pdMS_TO_TICKS(500));continue;}
        const psk_hint_key_t key={.key=psk,.key_size=sizeof(psk),.hint=identity};
        const esp_tls_cfg_t cfg={.psk_hint_key=&key,.timeout_ms=500};
        bool ok=esp_tls_conn_new_sync(host,strlen(host),port,&cfg,tls)==1;
        if(ok) {
            int fd=-1,yes=1;esp_tls_get_conn_sockfd(tls,&fd);if(fd>=0)setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&yes,sizeof(yes));
            ok=exchange(tls,AK_AUDIO_HELLO,c.session,0,0,NULL,0);
        }
        audio_context current=snapshot();
        ok=ok && current.enabled && current.session==c.session;
        uint32_t sequence=1,stream=0;int64_t last=esp_timer_get_time();
        if(ok) {atomic_store(&ready_session,c.session);atomic_store(&ready,true);}
        while(ok) {
            current=snapshot();
            if(!current.enabled || current.session!=c.session || !atomic_load(&ip_ready) || atomic_load(&fault))break;
            if(sequence==UINT32_MAX) {ok=false;break;}
            if(stream && (!current.permit || current.stream!=stream)) {
                ok=exchange(tls,AK_AUDIO_END,c.session,stream,sequence++,NULL,0);stream=0;last=esp_timer_get_time();continue;
            }
            audio_chunk chunk;
            if(xQueueReceive(chunks,&chunk,pdMS_TO_TICKS(10))==pdTRUE) {
                current=snapshot();
                if(current.permit && chunk.session==c.session && chunk.stream==current.stream) {
                    if(!stream) {stream=chunk.stream;ok=exchange(tls,AK_AUDIO_BEGIN,c.session,stream,sequence++,NULL,0);}
                    current=snapshot();
                    if(ok && current.enabled && current.permit && current.session==c.session && current.stream==stream)
                        ok=exchange(tls,AK_AUDIO_DATA,c.session,stream,sequence++,chunk.pcm,chunk.count);
                    last=esp_timer_get_time();
                }
                zero(&chunk,sizeof(chunk));
            } else if(esp_timer_get_time()-last>=200000) {ok=exchange(tls,AK_AUDIO_PING,c.session,0,sequence++,NULL,0);last=esp_timer_get_time();}
        }
        bool was=atomic_exchange(&ready,false);current=snapshot();
        if(was && current.enabled && current.session==c.session)atomic_store(&fault,true);
        xQueueReset(chunks);esp_tls_conn_destroy(tls);vTaskDelay(pdMS_TO_TICKS(300));
    }
}
esp_err_t ak_wifi_audio_init(void) {
    const uint8_t *settings=ak_settings_current();if(!settings)return ESP_ERR_NOT_FOUND;
    memcpy(host,settings+100,16);port=(uint16_t)settings[116]|(uint16_t)settings[117]<<8;memcpy(psk,settings+118,32);
    uint8_t mac[6];esp_read_mac(mac,ESP_MAC_WIFI_STA);snprintf(identity,sizeof(identity),"%02X%02X%02X%02X%02X%02X",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    desired.stream=esp_random();chunks=xQueueCreate(10,sizeof(audio_chunk));if(!chunks)return ESP_ERR_NO_MEM;
    esp_err_t e=esp_netif_init();if(e!=ESP_OK)return e;
    e=esp_event_loop_create_default();if(e!=ESP_OK && e!=ESP_ERR_INVALID_STATE)return e;
    if(!esp_netif_create_default_wifi_sta())return ESP_ERR_NO_MEM;
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();e=esp_wifi_init(&init);if(e!=ESP_OK)return e;
    e=esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,event,NULL);if(e!=ESP_OK)return e;
    e=esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,event,NULL);if(e!=ESP_OK)return e;
    wifi_config_t cfg={0};memcpy(cfg.sta.ssid,settings+4,settings[1]);memcpy(cfg.sta.password,settings+36,settings[2]);
    cfg.sta.threshold.authmode=WIFI_AUTH_WPA2_PSK;cfg.sta.pmf_cfg.capable=true;
    e=esp_wifi_set_storage(WIFI_STORAGE_RAM);if(e==ESP_OK)e=esp_wifi_set_mode(WIFI_MODE_STA);if(e==ESP_OK)e=esp_wifi_set_config(WIFI_IF_STA,&cfg);zero(&cfg,sizeof(cfg));
    if(e!=ESP_OK)return e;
    e=esp_wifi_start();if(e!=ESP_OK)return e;
    return xTaskCreate(sender,"wifi_audio",8192,NULL,5,NULL)==pdPASS?ESP_OK:ESP_ERR_NO_MEM;
}

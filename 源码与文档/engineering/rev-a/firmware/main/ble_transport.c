#include "ble_transport.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_store.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_mac.h"
#include "esp_log.h"
#include <stdatomic.h>
#include <string.h>
#include <stdio.h>

/* HOGP mouse report: five bytes (buttons, X, Y, wheel, pan), report ID 1.
 * GATT report values omit the report ID; Report Reference supplies it. */
static const uint8_t mouse_map[]={
    0x05,0x01,0x09,0x02,0xa1,0x01,0x85,0x01,0x09,0x01,0xa1,0x00,
    0x05,0x09,0x19,0x01,0x29,0x05,0x15,0x00,0x25,0x01,0x95,0x05,0x75,0x01,0x81,0x02,
    0x95,0x01,0x75,0x03,0x81,0x01,0x05,0x01,0x09,0x30,0x09,0x31,0x09,0x38,
    0x15,0x81,0x25,0x7f,0x75,0x08,0x95,0x03,0x81,0x06,
    0x05,0x0c,0x0a,0x38,0x02,0x95,0x01,0x81,0x06,0xc0,0xc0
};
/* 98f32a0e-79bc-4d5b-9f84-dcce6f807291 service; ...7292 control. */
static const ble_uuid128_t control_service=BLE_UUID128_INIT(0x91,0x72,0x80,0x6f,0xce,0xdc,0x84,0x9f,0x5b,0x4d,0xbc,0x79,0x0e,0x2a,0xf3,0x98);
static const ble_uuid128_t control_uuid=BLE_UUID128_INIT(0x92,0x72,0x80,0x6f,0xce,0xdc,0x84,0x9f,0x5b,0x4d,0xbc,0x79,0x0e,0x2a,0xf3,0x98);
static QueueHandle_t commands,events;
static atomic_uint connection=BLE_HS_CONN_HANDLE_NONE;
static atomic_uint generation;
static atomic_bool encrypted,active,suspended,mouse_subscribed,control_subscribed,overflow;
static uint16_t mouse_handle,control_handle;
static uint8_t own_address;
static char name[20];
static uint8_t last_state[AK_WIRE_SIZE];
static struct ble_npl_event forget_event;
static SemaphoreHandle_t forget_done;
static atomic_bool forget_pending;
static atomic_int forget_result;
static portMUX_TYPE state_lock=portMUX_INITIALIZER_UNLOCKED;
void ble_store_config_init(void);
static int gap_event(struct ble_gap_event *,void *);

static void cache_state(const uint8_t *packet) {
    portENTER_CRITICAL(&state_lock);memcpy(last_state,packet,AK_WIRE_SIZE);portEXIT_CRITICAL(&state_lock);
}
static int append(struct ble_gatt_access_ctxt *ctx,const void *value,size_t n) {
    return os_mbuf_append(ctx->om,value,n)==0?0:BLE_ATT_ERR_INSUFFICIENT_RES;
}
static int hid_access(uint16_t conn,uint16_t attr,struct ble_gatt_access_ctxt *ctx,void *arg) {
    (void)conn;(void)attr;
    uintptr_t kind=(uintptr_t)arg;
    if(ctx->op==BLE_GATT_ACCESS_OP_READ_DSC) {const uint8_t ref[]={1,1};return append(ctx,ref,sizeof(ref));}
    if(ctx->op==BLE_GATT_ACCESS_OP_READ_CHR) {
        if(kind==1)return append(ctx,mouse_map,sizeof(mouse_map));
        if(kind==2) {const uint8_t info[]={0x11,0x01,0,2};return append(ctx,info,sizeof(info));}
        if(kind==3) {const uint8_t report[5]={0};return append(ctx,report,sizeof(report));}
        return BLE_ATT_ERR_READ_NOT_PERMITTED;
    }
    if(kind==4 && ctx->op==BLE_GATT_ACCESS_OP_WRITE_CHR) {
        uint8_t value=0;
        if(OS_MBUF_PKTLEN(ctx->om)!=1 || os_mbuf_copydata(ctx->om,0,1,&value) || value>1)return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        if(atomic_exchange(&suspended,value==0)!=(value==0))atomic_fetch_add(&generation,1);
        return 0;
    }
    return BLE_ATT_ERR_WRITE_NOT_PERMITTED;
}
static int control_access(uint16_t conn,uint16_t attr,struct ble_gatt_access_ctxt *ctx,void *arg) {
    (void)conn;(void)attr;(void)arg;
    if(ctx->op==BLE_GATT_ACCESS_OP_READ_CHR) {
        uint8_t snapshot[AK_WIRE_SIZE];portENTER_CRITICAL(&state_lock);memcpy(snapshot,last_state,sizeof(snapshot));portEXIT_CRITICAL(&state_lock);return append(ctx,snapshot,sizeof(snapshot));
    }
    if(ctx->op!=BLE_GATT_ACCESS_OP_WRITE_CHR || !atomic_load(&active) || !ak_ble_connected() || !atomic_load(&control_subscribed))return BLE_ATT_ERR_WRITE_NOT_PERMITTED;
    if(ble_att_mtu(conn)<AK_WIRE_SIZE+3)return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    uint8_t packet[AK_WIRE_SIZE];ak_wire_command command;
    if(OS_MBUF_PKTLEN(ctx->om)!=sizeof(packet) || os_mbuf_copydata(ctx->om,0,sizeof(packet),packet) || !ak_decode_command(packet,sizeof(packet),&command))return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    if(xQueueSend(commands,&command,0)!=pdTRUE) {atomic_store(&overflow,true);return BLE_ATT_ERR_INSUFFICIENT_RES;}
    return 0;
}
static const struct ble_gatt_svc_def services[]={
    {.type=BLE_GATT_SVC_TYPE_PRIMARY,.uuid=BLE_UUID16_DECLARE(0x1812),.characteristics=(struct ble_gatt_chr_def[]){
        {.uuid=BLE_UUID16_DECLARE(0x2a4b),.access_cb=hid_access,.arg=(void *)1,.flags=BLE_GATT_CHR_F_READ|BLE_GATT_CHR_F_READ_ENC},
        {.uuid=BLE_UUID16_DECLARE(0x2a4a),.access_cb=hid_access,.arg=(void *)2,.flags=BLE_GATT_CHR_F_READ|BLE_GATT_CHR_F_READ_ENC},
        {.uuid=BLE_UUID16_DECLARE(0x2a4d),.access_cb=hid_access,.arg=(void *)3,.val_handle=&mouse_handle,.flags=BLE_GATT_CHR_F_READ|BLE_GATT_CHR_F_READ_ENC|BLE_GATT_CHR_F_NOTIFY,
         .descriptors=(struct ble_gatt_dsc_def[]){{.uuid=BLE_UUID16_DECLARE(0x2908),.att_flags=BLE_ATT_F_READ|BLE_ATT_F_READ_ENC,.access_cb=hid_access},{0}}},
        {.uuid=BLE_UUID16_DECLARE(0x2a4c),.access_cb=hid_access,.arg=(void *)4,.flags=BLE_GATT_CHR_F_WRITE_NO_RSP|BLE_GATT_CHR_F_WRITE_ENC},
        {0}}},
    {.type=BLE_GATT_SVC_TYPE_PRIMARY,.uuid=&control_service.u,.characteristics=(struct ble_gatt_chr_def[]){
        {.uuid=&control_uuid.u,.access_cb=control_access,.val_handle=&control_handle,.flags=BLE_GATT_CHR_F_READ|BLE_GATT_CHR_F_READ_ENC|BLE_GATT_CHR_F_WRITE|BLE_GATT_CHR_F_WRITE_ENC|BLE_GATT_CHR_F_NOTIFY},{0}}},
    {0}
};
static void advertise(void) {
    static const ble_uuid16_t hid[]={BLE_UUID16_INIT(0x1812)};
    struct ble_hs_adv_fields fields={0};
    fields.flags=BLE_HS_ADV_F_DISC_GEN|BLE_HS_ADV_F_BREDR_UNSUP;
    fields.name=(const uint8_t *)name;fields.name_len=strlen(name);fields.name_is_complete=1;
    fields.appearance=0x03c2;fields.appearance_is_present=1;fields.uuids16=(ble_uuid16_t *)hid;fields.num_uuids16=1;fields.uuids16_is_complete=1;
    struct ble_gap_adv_params params={.conn_mode=BLE_GAP_CONN_MODE_UND,.disc_mode=BLE_GAP_DISC_MODE_GEN,.itvl_min=160,.itvl_max=240};
    int rc=ble_gap_adv_set_fields(&fields);
    if(!rc)rc=ble_gap_adv_start(own_address,NULL,BLE_HS_FOREVER,&params,gap_event,NULL);
    if(rc)ESP_LOGE("aikey_ble","advertising error %d",rc);
}
static bool known_peer(uint16_t handle) {
    ble_addr_t peers[CONFIG_BT_NIMBLE_MAX_BONDS];int count=0;
    struct ble_gap_conn_desc desc;
    if(ble_gap_conn_find(handle,&desc) || ble_store_util_bonded_peers(peers,&count,CONFIG_BT_NIMBLE_MAX_BONDS))return false;
    if(!count)return true; /* First enrollment uses normal OS pairing. */
    for(int i=0;i<count;i++)if(ble_addr_cmp(&peers[i],&desc.peer_id_addr)==0)return true;
    return false; /* EN reset never replaces an existing bond. */
}
static void clear_link(void) {
    atomic_store(&encrypted,false);atomic_store(&suspended,false);atomic_store(&mouse_subscribed,false);atomic_store(&control_subscribed,false);atomic_store(&connection,BLE_HS_CONN_HANDLE_NONE);
    atomic_fetch_add(&generation,1);
}
static int gap_event(struct ble_gap_event *e,void *unused) {
    (void)unused;
    switch(e->type) {
    case BLE_GAP_EVENT_CONNECT:
        if(e->connect.status) {advertise();break;}
        atomic_store(&connection,e->connect.conn_handle);
        if(!known_peer(e->connect.conn_handle)) {ble_gap_terminate(e->connect.conn_handle,BLE_ERR_REM_USER_CONN_TERM);break;}
        ble_gap_security_initiate(e->connect.conn_handle);break;
    case BLE_GAP_EVENT_DISCONNECT:clear_link();advertise();break;
    case BLE_GAP_EVENT_ENC_CHANGE: {
        struct ble_gap_conn_desc desc;
        bool ok=e->enc_change.status==0 && !ble_gap_conn_find(e->enc_change.conn_handle,&desc) && desc.sec_state.encrypted;
        atomic_store(&encrypted,ok);
        atomic_fetch_add(&generation,1);
        if(!ok)ble_gap_terminate(e->enc_change.conn_handle,BLE_ERR_REM_USER_CONN_TERM);
        break;}
    case BLE_GAP_EVENT_SUBSCRIBE:
        if(e->subscribe.attr_handle==mouse_handle && atomic_exchange(&mouse_subscribed,e->subscribe.cur_notify)!=(bool)e->subscribe.cur_notify)atomic_fetch_add(&generation,1);
        if(e->subscribe.attr_handle==control_handle && atomic_exchange(&control_subscribed,e->subscribe.cur_notify)!=(bool)e->subscribe.cur_notify)atomic_fetch_add(&generation,1);
        break;
    case BLE_GAP_EVENT_ADV_COMPLETE:advertise();break;
    case BLE_GAP_EVENT_REPEAT_PAIRING:return BLE_GAP_REPEAT_PAIRING_IGNORE;
    default:break;
    }
    return 0;
}
static void reset(int reason) {clear_link();ESP_LOGE("aikey_ble","host reset %d",reason);}
static void sync_host(void) {
    if(ble_hs_util_ensure_addr(0) || ble_hs_id_infer_auto(0,&own_address)) {ESP_LOGE("aikey_ble","address unavailable");return;}
    advertise();
}
static void run_host(void *unused) {(void)unused;nimble_port_run();nimble_port_freertos_deinit();}
static void forget_on_host(struct ble_npl_event *event) {
    (void)event;ak_ble_drop_link();
    atomic_store(&forget_result,ble_store_clear());
    atomic_store(&forget_pending,false);xSemaphoreGive(forget_done);
}
bool ak_ble_forget_bonds(void) {
    if(!forget_done || atomic_exchange(&forget_pending,true))return false;
    (void)xSemaphoreTake(forget_done,0);
    ble_npl_eventq_put(nimble_port_get_dflt_eventq(),&forget_event);
    return xSemaphoreTake(forget_done,pdMS_TO_TICKS(1000))==pdTRUE && atomic_load(&forget_result)==0;
}
esp_err_t ak_ble_init(void) {
    commands=xQueueCreate(8,sizeof(ak_wire_command));events=xQueueCreate(32,AK_WIRE_SIZE);
    if(!commands||!events)return ESP_ERR_NO_MEM;
    uint8_t mac[6];ESP_ERROR_CHECK(esp_read_mac(mac,ESP_MAC_WIFI_STA));snprintf(name,sizeof(name),"AIKEY-%02X%02X%02X",mac[3],mac[4],mac[5]);
    esp_err_t e=nimble_port_init();if(e!=ESP_OK)return e;
    ble_hs_cfg.reset_cb=reset;ble_hs_cfg.sync_cb=sync_host;
    ble_hs_cfg.sm_io_cap=BLE_HS_IO_NO_INPUT_OUTPUT;ble_hs_cfg.sm_bonding=1;ble_hs_cfg.sm_sc=1;ble_hs_cfg.sm_mitm=0;
    ble_hs_cfg.sm_our_key_dist=BLE_SM_PAIR_KEY_DIST_ENC|BLE_SM_PAIR_KEY_DIST_ID;ble_hs_cfg.sm_their_key_dist=BLE_SM_PAIR_KEY_DIST_ENC|BLE_SM_PAIR_KEY_DIST_ID;
    ble_svc_gap_init();ble_svc_gatt_init();ble_store_config_init();
    if(ble_svc_gap_device_name_set(name) || ble_svc_gap_device_appearance_set(0x03c2) || ble_gatts_count_cfg(services) || ble_gatts_add_svcs(services))return ESP_FAIL;
    if(ble_att_set_preferred_mtu(64))return ESP_FAIL;
    forget_done=xSemaphoreCreateBinary();if(!forget_done)return ESP_ERR_NO_MEM;
    ble_npl_event_init(&forget_event,forget_on_host,NULL);
    nimble_port_freertos_init(run_host);return ESP_OK;
}
bool ak_ble_connected(void) {return atomic_load(&connection)!=BLE_HS_CONN_HANDLE_NONE && atomic_load(&encrypted) && !atomic_load(&suspended);}
bool ak_ble_ready(void) {return ak_ble_connected() && atomic_load(&active);}
bool ak_ble_hid_available(void) {return ak_ble_ready() && atomic_load(&mouse_subscribed);}
uint32_t ak_ble_generation(void) {return atomic_load(&generation);}
void ak_ble_drop_link(void) {uint16_t c=(uint16_t)atomic_load(&connection);if(c!=BLE_HS_CONN_HANDLE_NONE)ble_gap_terminate(c,BLE_ERR_REM_USER_CONN_TERM);}
void ak_ble_set_active(bool value) {atomic_store(&active,value);}
void ak_ble_flush(void) {if(commands)xQueueReset(commands);if(events)xQueueReset(events);atomic_store(&overflow,false);}
bool ak_ble_pop_command(ak_wire_command *out) {return commands && xQueueReceive(commands,out,0)==pdTRUE;}
bool ak_ble_pop_event(uint8_t out[AK_WIRE_SIZE]) {return events && xQueueReceive(events,out,0)==pdTRUE;}
bool ak_ble_take_overflow(void) {return atomic_exchange(&overflow,false);}
void ak_ble_queue_event(const ak_controller *c,const ak_event *e) {
    uint8_t packet[AK_WIRE_SIZE];ak_encode_state(c,e,packet);cache_state(packet);
    if(ak_ble_ready() && atomic_load(&control_subscribed) && xQueueSend(events,packet,0)!=pdTRUE)atomic_store(&overflow,true);
}
static bool notify(uint16_t handle,const void *bytes,size_t len) {
    if(!ak_ble_ready())return false;
    uint16_t conn=(uint16_t)atomic_load(&connection);
    if(ble_att_mtu(conn)<len+3)return false;
    struct os_mbuf *buffer=ble_hs_mbuf_from_flat(bytes,len);
    return buffer && ble_gatts_notify_custom(conn,handle,buffer)==0;
}
bool ak_ble_mouse(uint8_t buttons,int8_t x,int8_t y) {
    if(!atomic_load(&mouse_subscribed))return false;
    const uint8_t packet[]={(uint8_t)(buttons&3),(uint8_t)x,(uint8_t)y,0,0};return notify(mouse_handle,packet,sizeof(packet));
}
/* With no control subscriber this is a readable snapshot, not an outstanding
 * notification. Do not let it stall ordinary OS mouse reports. */
bool ak_ble_state(const uint8_t packet[AK_WIRE_SIZE]) {cache_state(packet);return !atomic_load(&control_subscribed) || notify(control_handle,packet,AK_WIRE_SIZE);}

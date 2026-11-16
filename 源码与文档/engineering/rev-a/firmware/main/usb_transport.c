#include "usb_transport.h"
#include "board_config.h"
#include "tinyusb.h"
#include "class/hid/hid_device.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_mac.h"
#include <stdio.h>
#include <stdatomic.h>

static QueueHandle_t commands,events,configs;
static atomic_bool overflow=false;
static char serial[13];
static const uint8_t reports[]={
    TUD_HID_REPORT_DESC_MOUSE(HID_REPORT_ID(1)),
    0x06,0x00,0xff,0x09,0x01,0xa1,0x01,0x85,0x02,
    0x15,0x00,0x26,0xff,0x00,0x75,0x08,0x95,AK_WIRE_SIZE,
    0x09,0x01,0x81,0x02,0x09,0x02,0x91,0x02,0xc0,
    /* Separate USB-only configuration collection; never a mouse command. */
    0x06,0x00,0xff,0x09,0x03,0xa1,0x01,0x85,0x03,
    0x15,0x00,0x26,0xff,0x00,0x75,0x08,0x95,32,
    0x09,0x03,0x81,0x02,0x09,0x04,0x91,0x02,0xc0
};
static const tusb_desc_device_t device={
    .bLength=sizeof(tusb_desc_device_t),.bDescriptorType=TUSB_DESC_DEVICE,.bcdUSB=0x0200,
    .bDeviceClass=0xef,.bDeviceSubClass=2,.bDeviceProtocol=1,.bMaxPacketSize0=64,
    /* TinyUSB development identity. Production USB VID/PID allocation is pending. */
    .idVendor=0xcafe,.idProduct=0x4031,.bcdDevice=0x0001,
    .iManufacturer=1,.iProduct=2,.iSerialNumber=3,.bNumConfigurations=1
};
static const uint8_t configuration[]={
    TUD_CONFIG_DESCRIPTOR(1,3,0,TUD_CONFIG_DESC_LEN+TUD_HID_DESC_LEN+TUD_AUDIO20_MIC_ONE_CH_DESC_LEN,TUSB_DESC_CONFIG_ATT_SELF_POWERED,500),
    TUD_HID_DESCRIPTOR(0,4,HID_ITF_PROTOCOL_NONE,sizeof(reports),0x81,64,4),
    TUD_AUDIO20_MIC_ONE_CH_DESCRIPTOR(1,5,2,16,0x82,34)
};
static const char *strings[]={(const char[]){0x09,0x04},"AI KEY Development","AI KEY REV A",serial,"Mouse + control","Held-key microphone"};
const uint8_t *tud_hid_descriptor_report_cb(uint8_t instance) { (void)instance;return reports; }
uint16_t tud_hid_get_report_cb(uint8_t instance,uint8_t id,hid_report_type_t type,uint8_t *buffer,uint16_t len) {
    (void)instance;(void)id;(void)type;(void)buffer;(void)len;return 0;
}
void tud_hid_set_report_cb(uint8_t instance,uint8_t id,hid_report_type_t type,const uint8_t *buffer,uint16_t len) {
    (void)instance;
    ak_wire_command command;
    if(id==2 && type==HID_REPORT_TYPE_OUTPUT && ak_decode_command(buffer,len,&command))
        if(xQueueSend(commands,&command,0)!=pdTRUE)atomic_store(&overflow,true);
    if(id==3 && type==HID_REPORT_TYPE_OUTPUT && len==32)
        if(xQueueSend(configs,buffer,0)!=pdTRUE)atomic_store(&overflow,true);
}
esp_err_t ak_usb_init(void) {
    commands=xQueueCreate(8,sizeof(ak_wire_command));events=xQueueCreate(32,AK_WIRE_SIZE);configs=xQueueCreate(4,32);
    if(!commands || !events || !configs)return ESP_ERR_NO_MEM;
    uint8_t mac[6];esp_read_mac(mac,ESP_MAC_WIFI_STA);
    snprintf(serial,sizeof(serial),"%02X%02X%02X%02X%02X%02X",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    const tinyusb_config_t cfg={.device_descriptor=&device,.string_descriptor=strings,
        .string_descriptor_count=6,.configuration_descriptor=configuration,.external_phy=false,
        .self_powered=true,.vbus_monitor_io=AK_PIN_USB_VBUS};
    return tinyusb_driver_install(&cfg);
}
bool ak_usb_pop_command(ak_wire_command *out) {return xQueueReceive(commands,out,0)==pdTRUE;}
bool ak_usb_pop_event(uint8_t out[AK_WIRE_SIZE]) {return xQueueReceive(events,out,0)==pdTRUE;}
void ak_usb_queue_event(const ak_controller *c,const ak_event *e) {
    if(!tud_mounted())return;
    uint8_t packet[AK_WIRE_SIZE];ak_encode_state(c,e,packet);
    if(xQueueSend(events,packet,0)!=pdTRUE)atomic_store(&overflow,true);
}
bool ak_usb_take_overflow(void) {return atomic_exchange(&overflow,false);}
bool ak_usb_mounted(void) {return tud_mounted() && !tud_suspended();}
bool ak_usb_suspended(void) {return tud_mounted() && tud_suspended();}
bool ak_usb_ready(void) {return tud_hid_ready();}
bool ak_usb_mouse(uint8_t buttons,int8_t x,int8_t y) {return tud_hid_mouse_report(1,buttons,x,y,0,0);}
bool ak_usb_state(const uint8_t packet[AK_WIRE_SIZE]) {return tud_hid_report(2,packet,AK_WIRE_SIZE);}
bool ak_usb_pop_config(uint8_t out[32]) {return xQueueReceive(configs,out,0)==pdTRUE;}
bool ak_usb_config_reply(const uint8_t packet[32]) {return tud_hid_report(3,packet,32);}
void ak_usb_flush(void) {xQueueReset(commands);xQueueReset(events);xQueueReset(configs);atomic_store(&overflow,false);}

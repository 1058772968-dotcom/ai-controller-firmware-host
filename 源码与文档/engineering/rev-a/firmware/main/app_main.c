#include "controller.h"
#include "board_config.h"
#include "usb_transport.h"
#include "ble_transport.h"
#include "link_policy.h"
#include "imu.h"
#include "motion.h"
#include "audio_capture.h"
#include "peripheral_bus.h"
#include "settings_store.h"
#include "wifi_audio.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

static ak_controller controller;
static ak_motion motion;
static bool audio_initialized;
static bool ble_initialized;
static bool wifi_initialized;
static ak_link_policy routing;
#define active_link (routing.active)
static bool peripherals_initialized;
static ak_peripherals peripherals;
static ak_settings_stage settings_stage;
static int16_t pending_x,pending_y;
static const int key_pins[]={AK_PIN_KEY_L,AK_PIN_KEY_R,AK_PIN_KEY_VOICE,AK_PIN_KEY_SIDE};
static uint8_t buttons(void) {
    uint8_t mask=0;for(unsigned i=0;i<4;i++)if(!gpio_get_level(key_pins[i]))mask|=1u<<i;
    return mask;
}
static uint32_t now(void) {return (uint32_t)(esp_timer_get_time()/1000);}
static bool link_ready(void) {return active_link==LINK_USB?ak_usb_ready():active_link==LINK_BLE && ak_ble_ready();}
static bool link_mouse(uint8_t buttons,int8_t x,int8_t y) {return active_link==LINK_USB?ak_usb_mouse(buttons,x,y):active_link==LINK_BLE && ak_ble_mouse(buttons,x,y);}
static bool link_state(const uint8_t *packet) {return active_link==LINK_USB?ak_usb_state(packet):active_link==LINK_BLE && ak_ble_state(packet);}
static bool link_event(uint8_t *packet) {return active_link==LINK_USB?ak_usb_pop_event(packet):active_link==LINK_BLE && ak_ble_pop_event(packet);}
static bool link_command(ak_wire_command *command) {return active_link==LINK_USB?ak_usb_pop_command(command):active_link==LINK_BLE && ak_ble_pop_command(command);}
static void before_handoff(void *context,link_type old,link_type selected) {
    const ak_link_inputs *inputs=context;
    if(old==LINK_BLE) {
        (void)ak_ble_mouse(0,0,0);
        if(selected!=LINK_BLE && (inputs->usb_mounted || inputs->usb_suspended))ak_ble_drop_link();
    } else if(old==LINK_USB && ak_usb_ready())(void)ak_usb_mouse(0,0,0);
    ak_ble_set_active(false);
}
static void emit(void *context,const ak_event *event) {
    (void)context;
    if(event->type==AK_CENTER || event->type==AK_OWNER || event->type==AK_RESET_INPUT) {
        ak_motion_recenter(&motion);pending_x=pending_y=0;
    }
    if(active_link==LINK_USB)ak_usb_queue_event(&controller,event);
    else if(active_link==LINK_BLE)ak_ble_queue_event(&controller,event);
}
static void outputs(void) {
    gpio_set_level(AK_PIN_MIC_EN,controller.mic_power);
    if(wifi_initialized)ak_wifi_audio_context(controller.session,active_link==LINK_BLE,controller.mic_ready);
    ak_audio_route(active_link==LINK_BLE);
    if(audio_initialized)ak_audio_set(controller.mic_power,controller.mic_ready);
    if(peripherals_initialized) {
        ak_peripherals_step(&peripherals,now(),controller.recording || controller.drawing ||
            (controller.raw&(AK_VOICE|AK_SIDE)) || ak_usb_suspended(),controller.haptic);
        controller.battery_valid=peripherals.battery_valid;
        controller.battery_mv=peripherals.battery_mv;controller.soc_q8=peripherals.soc_q8;
        controller.haptic_calibrated=ak_haptic_ready(&peripherals);
        controller.hardware_faults=(uint8_t)((controller.hardware_faults&~12u)|
            (controller.haptic_calibrated?0u:4u)|(peripherals.gauge_failed?8u:0u));
    } else gpio_set_level(AK_PIN_HAPTIC_EN,0);
    bool suspended=ak_usb_suspended();
    gpio_set_level(AK_PIN_CHG_EN1,ak_usb_mounted()||suspended);gpio_set_level(AK_PIN_CHG_EN2,suspended);
    gpio_set_level(AK_PIN_LED_R,controller.drawing);
    gpio_set_level(AK_PIN_LED_G,controller.mic_ready || controller.drawing);
    gpio_set_level(AK_PIN_LED_B,controller.mic_ready);
}
void app_main(void) {
    gpio_config_t out={.mode=GPIO_MODE_OUTPUT,.pin_bit_mask=(1ULL<<AK_PIN_MIC_EN)|(1ULL<<AK_PIN_HAPTIC_EN)|(1ULL<<AK_PIN_CHG_EN1)|(1ULL<<AK_PIN_CHG_EN2)|(1ULL<<AK_PIN_LED_R)|(1ULL<<AK_PIN_LED_G)|(1ULL<<AK_PIN_LED_B)};
    ESP_ERROR_CHECK(gpio_config(&out));outputs();
    gpio_config_t in={.mode=GPIO_MODE_INPUT,.pull_up_en=GPIO_PULLUP_ENABLE};
    for(unsigned i=0;i<4;i++)in.pin_bit_mask|=1ULL<<key_pins[i];
    ESP_ERROR_CHECK(gpio_config(&in));
    /* Never erase user pairing/settings automatically if NVS cannot initialize. */
    ESP_ERROR_CHECK(nvs_flash_init());
    if(ak_settings_load()!=ESP_OK)ESP_LOGE("aikey","Saved settings invalid/unavailable; Wi-Fi remains disabled. Stored data was not erased.");
    ESP_ERROR_CHECK(ak_usb_init());ak_motion_init(&motion);ak_init(&controller,esp_random(),buttons(),now(),emit,NULL);
    if(ak_ble_init()==ESP_OK)ble_initialized=true;
    else {controller.hardware_faults|=16;ESP_LOGE("aikey","BLE unavailable: USB remains available");}
    esp_err_t wifi_result=ak_wifi_audio_init();
    wifi_initialized=wifi_result==ESP_OK;
    if(wifi_result!=ESP_OK && wifi_result!=ESP_ERR_NOT_FOUND)ESP_LOGE("aikey","Wi-Fi audio initialization failed; USB audio remains available");
    if(ak_imu_init()!=ESP_OK) {controller.hardware_faults|=1;ESP_LOGE("aikey","IMU unavailable: pointer movement disabled");}
    if(ak_audio_init()==ESP_OK)audio_initialized=true;
    else {controller.hardware_faults|=2;ESP_LOGE("aikey","PDM unavailable: recording disabled");}
    ak_i2c_io peripheral_io;
    if(ak_peripheral_bus_init(&peripheral_io)==ESP_OK) {
        ak_peripherals_init(&peripherals,peripheral_io,now());peripherals_initialized=true;
    } else {controller.hardware_faults|=12;ESP_LOGE("aikey","I2C unavailable: gauge and haptic disabled");}
    uint8_t previous_hid=0xff;uint32_t last_status=0;
    uint8_t config_reply[32];bool config_pending=false;
    uint8_t pending[AK_WIRE_SIZE];bool pending_valid=false;uint32_t last_imu=now(),last_sample=last_imu;
    for(;;) {
        uint32_t t=now();
        ak_link_inputs inputs={.usb_mounted=ak_usb_mounted(),.usb_suspended=ak_usb_suspended(),
            .ble_connected=ble_initialized && ak_ble_connected(),.ble_generation=ak_ble_generation()};
        if(ak_link_update(&routing,&controller,inputs,buttons(),t,before_handoff,&inputs)) {
            ak_usb_flush();ak_ble_flush();previous_hid=0xff;pending_valid=false;
            ak_ble_set_active(active_link==LINK_BLE);last_status=0;
            ak_settings_reset(&settings_stage);config_pending=false;
        }
        bool mounted=active_link!=LINK_NONE;
        ak_poll(&controller,buttons(),t);
        if(!(controller.hardware_faults&1) && t-last_imu>=2) {
            float g[3],a[3];bool fresh=false;last_imu=t;
            if(ak_imu_read(g,a,&fresh)!=ESP_OK) {controller.hardware_faults|=1;ak_fault(&controller,2,t);}
            else if(fresh) {
                int16_t x,y;ak_motion_step(&motion,g,a,(t-last_sample)*.001f,&x,&y);last_sample=t;
                controller.calibrated=motion.calibrated;
                if(mounted) {
                    int xx=pending_x+x,yy=pending_y+y;
                    pending_x=xx>127?127:xx<-127?-127:xx;pending_y=yy>127?127:yy<-127?-127:yy;
                }
            }
        }
        if(audio_initialized && ak_audio_failed() && !(controller.hardware_faults&2)) {controller.hardware_faults|=2;ak_fault(&controller,3,t);}
        if(wifi_initialized && ak_wifi_audio_take_fault() && active_link==LINK_BLE)ak_fault(&controller,4,t);
        bool audio_available=audio_initialized && !ak_audio_failed() &&
            (active_link==LINK_USB || (active_link==LINK_BLE && wifi_initialized && ak_wifi_audio_ready(controller.session)));
        if(controller.recording && !audio_available)ak_fault(&controller,4,t);
        if(audio_available)controller.hardware_faults&=(uint8_t)~2u;else controller.hardware_faults|=2u;
        if(active_link==LINK_USB?ak_usb_take_overflow():active_link==LINK_BLE && ak_ble_take_overflow())ak_fault(&controller,1,t);
        ak_wire_command command;
        while(link_command(&command)) {
            if(mounted)ak_command(&controller,command.session,command.sequence,command.command,command.value,t);
        }
        outputs();
        if(mounted && link_ready()) {
            if(active_link==LINK_USB) {
                uint8_t request[32];
                if(!config_pending && ak_usb_pop_config(request)) {
                    bool idle=!controller.host_connected && !buttons() && !controller.recording && !controller.drawing;
                    config_pending=ak_settings_process(&settings_stage,ak_settings_backend(),controller.session,idle,ak_settings_configured(),request,32,config_reply);
                }
                if(config_pending) {
                    if(ak_usb_config_reply(config_reply))config_pending=false;
                    vTaskDelay(pdMS_TO_TICKS(1));continue;
                }
            }
            bool hid_available=active_link==LINK_USB || ak_ble_hid_available();
            if(hid_available && previous_hid!=controller.hid_buttons) {
                if(link_mouse(controller.hid_buttons,0,0))previous_hid=controller.hid_buttons;
            } else {
                if(!pending_valid)pending_valid=link_event(pending);
                if(!pending_valid && t-last_status>=100) {ak_encode_state(&controller,NULL,pending);pending_valid=true;last_status=t;}
                if(pending_valid) {if(link_state(pending))pending_valid=false;}
                else if(pending_x || pending_y) {
                    bool sent;
                    if(controller.owner==AK_HOST) {uint8_t packet[AK_WIRE_SIZE];ak_encode_motion(&controller,pending_x,pending_y,packet);sent=link_state(packet);}
                    else sent=link_mouse(controller.hid_buttons,(int8_t)pending_x,(int8_t)pending_y);
                    if(sent)pending_x=pending_y=0;
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

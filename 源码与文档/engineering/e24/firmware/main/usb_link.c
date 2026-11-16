#include "usb_link.h"
#include <stdatomic.h>
#include <stdio.h>
#include "bsp_pins.h"
#include "sdkconfig.h"
#include "class/hid/hid_device.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "soc/rtc_cntl_reg.h"
#include "tinyusb.h"
#include "tusb_cdc_acm.h"
#include "tusb_console.h"

static const char *TAG = "usb";
static QueueHandle_t s_commands, s_configs;
static atomic_bool s_overflow;
static atomic_bool s_cdc_open;
static char s_serial[13];

/* 报告描述符与 REV A 相同（电脑端已按此解析）：1 鼠标，2 控制，3 配置 */
static const uint8_t s_report[] = {
    TUD_HID_REPORT_DESC_MOUSE(HID_REPORT_ID(1)),
    0x06, 0x00, 0xff, 0x09, 0x01, 0xa1, 0x01, 0x85, 0x02,
    0x15, 0x00, 0x26, 0xff, 0x00, 0x75, 0x08, 0x95, AK_WIRE_SIZE,
    0x09, 0x01, 0x81, 0x02, 0x09, 0x02, 0x91, 0x02, 0xc0,
    0x06, 0x00, 0xff, 0x09, 0x03, 0xa1, 0x01, 0x85, 0x03,
    0x15, 0x00, 0x26, 0xff, 0x00, 0x75, 0x08, 0x95, 32,
    0x09, 0x03, 0x81, 0x02, 0x09, 0x04, 0x91, 0x02, 0xc0,
};

static const tusb_desc_device_t s_device = {
    .bLength = sizeof(tusb_desc_device_t), .bDescriptorType = TUSB_DESC_DEVICE, .bcdUSB = 0x0200,
    .bDeviceClass = TUSB_CLASS_MISC, .bDeviceSubClass = MISC_SUBCLASS_COMMON, .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = 64,
    .idVendor = 0xcafe, .idProduct = 0x4031, .bcdDevice = 0x0124,   /* 0x0124 = E24 */
    .iManufacturer = 1, .iProduct = 2, .iSerialNumber = 3, .bNumConfigurations = 1,
};

enum { ITF_HID = 0, ITF_CDC, ITF_CDC_DATA, ITF_MIC_CTRL, ITF_MIC_STREAM, ITF_COUNT };
#define EP_HID_IN 0x81
#define EP_CDC_NOTIF 0x82
#define EP_CDC_OUT 0x03
#define EP_CDC_IN 0x83
#define EP_MIC_IN 0x84
#define CONFIG_LEN (TUD_CONFIG_DESC_LEN + TUD_HID_INOUT_DESC_LEN + TUD_CDC_DESC_LEN + TUD_AUDIO20_MIC_ONE_CH_DESC_LEN)

static const uint8_t s_config[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_COUNT, 0, CONFIG_LEN, TUSB_DESC_CONFIG_ATT_SELF_POWERED, 500),
    /* HID IN+OUT，轮询 1 ms：主机下发控制/配置走 OUT 端点，不依赖 SET_REPORT 控制传输 */
    TUD_HID_INOUT_DESCRIPTOR(ITF_HID, 4, HID_ITF_PROTOCOL_NONE, sizeof(s_report), 0x02, EP_HID_IN, 64, 1),
    TUD_CDC_DESCRIPTOR(ITF_CDC, 5, EP_CDC_NOTIF, 8, EP_CDC_OUT, EP_CDC_IN, 64),
    /* UAC2 麦克风：16 kHz，16 bit，单声道；每 1 ms 32 字节，多留一帧余量 */
    TUD_AUDIO20_MIC_ONE_CH_DESCRIPTOR(ITF_MIC_CTRL, 6, 2, 16, EP_MIC_IN, 34),
};

static const char *s_strings[] = {
    (const char[]){0x09, 0x04}, "AI KEY Development", "AI KEY E24", s_serial, "Mouse + control", "E24 log",
#if CONFIG_E24_MIC_POC_OPEN
    "AI KEY Mic POC",
#else
    "Held-key microphone",
#endif

};

const uint8_t *tud_hid_descriptor_report_cb(uint8_t instance) { (void)instance; return s_report; }

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t id, hid_report_type_t type, uint8_t *buf, uint16_t len)
{
    (void)instance; (void)id; (void)type; (void)buf; (void)len;
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t id, hid_report_type_t type, const uint8_t *buf, uint16_t len)
{
    (void)instance;
    /* OUT 端点数据：id 由 TinyUSB 从首字节剥离；部分主机走控制传输时 type=OUTPUT 同样处理 */
    if (type != HID_REPORT_TYPE_OUTPUT && type != HID_REPORT_TYPE_INVALID) return;
    if (id == 0 && len > 0) { id = buf[0]; buf++; len--; }
    ak_wire_command c;
    if (id == 2 && ak_decode_command(buf, len, &c)) {
        if (xQueueSend(s_commands, &c, 0) != pdTRUE) atomic_store(&s_overflow, true);
    } else if (id == 3 && len == 32) {
        if (xQueueSend(s_configs, buf, 0) != pdTRUE) atomic_store(&s_overflow, true);
    }
}

static void on_line_state(int itf, cdcacm_event_t *e)
{
    (void)itf;
    atomic_store(&s_cdc_open, e->line_state_changed_data.dtr);
}

static void on_line_coding(int itf, cdcacm_event_t *e)
{
    (void)itf;
    /* 1200 bps “触碰”：Arduino 惯例，用于免按键进入下载模式 */
    if (e->line_coding_changed_data.p_line_coding->bit_rate == 1200) usb_link_reboot_to_download();
}

esp_err_t usb_link_init(void)
{
    s_commands = xQueueCreate(16, sizeof(ak_wire_command));
    s_configs = xQueueCreate(4, 32);
    if (!s_commands || !s_configs) return ESP_ERR_NO_MEM;
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(s_serial, sizeof s_serial, "%02X%02X%02X%02X%02X%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    const tinyusb_config_t cfg = {
        .device_descriptor = &s_device,
        .string_descriptor = s_strings,
        .string_descriptor_count = sizeof s_strings / sizeof s_strings[0],
        .external_phy = false,
        .configuration_descriptor = s_config,
        .self_powered = true,
        .vbus_monitor_io = BSP_PIN_USB_VBUS_PRESENT,   /* E24 新增的 VBUS 检测（TPS3808 → GPIO15） */
    };
    esp_err_t err = tinyusb_driver_install(&cfg);
    if (err != ESP_OK) return err;
    const tinyusb_config_cdcacm_t acm = {
        .usb_dev = TINYUSB_USBDEV_0,
        .cdc_port = TINYUSB_CDC_ACM_0,
        .callback_line_state_changed = on_line_state,
        .callback_line_coding_changed = on_line_coding,
    };
    err = tusb_cdc_acm_init(&acm);
    if (err != ESP_OK) return err;
    err = esp_tusb_init_console(TINYUSB_CDC_ACM_0);   /* 之后 ESP_LOG / printf 都走 CDC */
    if (err == ESP_OK) ESP_LOGI(TAG, "USB 复合设备就绪：HID(1 鼠标/2 控制/3 配置) + CDC 日志 + UAC 麦克风，序列号 %s", s_serial);
    return err;
}

bool usb_link_mounted(void) { return tud_mounted() && !tud_suspended(); }
bool usb_link_ready(void) { return tud_hid_ready(); }
bool usb_link_mouse(uint8_t b, int8_t x, int8_t y) { return tud_hid_mouse_report(1, b, x, y, 0, 0); }
bool usb_link_state(const uint8_t p[AK_WIRE_SIZE]) { return tud_hid_report(2, p, AK_WIRE_SIZE); }
bool usb_link_config_reply(const uint8_t p[32]) { return tud_hid_report(3, p, 32); }
bool usb_link_pop_command(ak_wire_command *o) { return xQueueReceive(s_commands, o, 0) == pdTRUE; }
bool usb_link_pop_config(uint8_t o[32]) { return xQueueReceive(s_configs, o, 0) == pdTRUE; }
bool usb_link_take_overflow(void) { return atomic_exchange(&s_overflow, false); }
void usb_link_flush(void) { xQueueReset(s_commands); xQueueReset(s_configs); atomic_store(&s_overflow, false); }

void usb_link_telemetry(const char *line, int len)
{
    if (!atomic_load(&s_cdc_open) || len <= 0) return;
    if (tud_cdc_n_write_available(0) < (uint32_t)len) return;   /* 放不下整行就丢整行 */
    tinyusb_cdcacm_write_queue(TINYUSB_CDC_ACM_0, (const uint8_t *)line, (size_t)len);
    tinyusb_cdcacm_write_flush(TINYUSB_CDC_ACM_0, 0);
}

void usb_link_reboot_to_download(void)
{
    /* 未实测：强制下次从 ROM 下载模式启动，并把 USB PHY 交还 USB-Serial-JTAG */
    REG_WRITE(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
    CLEAR_PERI_REG_MASK(RTC_CNTL_USB_CONF_REG, RTC_CNTL_SW_HW_USB_PHY_SEL | RTC_CNTL_SW_USB_PHY_SEL | RTC_CNTL_USB_PAD_ENABLE);
    esp_restart();
}

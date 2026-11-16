#pragma once
/* USB 复合设备（联调档）：
 *   接口 0 HID：报告 1 = 标准鼠标；报告 2 = 32 字节 v1 控制/状态；报告 3 = 32 字节配置通道
 *   接口 1-2 CDC ACM：日志 + JSON 行遥测（开发版）
 *   接口 3-4 UAC2 麦克风：16 kHz 单声道，隐私闸门在 audio_svc.c
 * VID/PID 沿用 REV A 开发标识 0xCAFE/0x4031，便于电脑端直接复用；量产身份待分配。 */
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "protocol.h"

esp_err_t usb_link_init(void);
bool usb_link_mounted(void);
bool usb_link_ready(void);                 /* HID 端点空闲，可发一个报告 */
bool usb_link_mouse(uint8_t buttons, int8_t x, int8_t y);
bool usb_link_state(const uint8_t packet[AK_WIRE_SIZE]);
bool usb_link_config_reply(const uint8_t packet[32]);
bool usb_link_pop_command(ak_wire_command *out);
bool usb_link_pop_config(uint8_t out[32]);
bool usb_link_take_overflow(void);
void usb_link_flush(void);
/* 遥测一行 JSON（以 \n 结尾）；CDC 未打开或缓冲满时丢弃，不阻塞 */
void usb_link_telemetry(const char *line, int len);
/* 切回 USB-Serial-JTAG 并重启进 ROM 下载模式（未实测；失败时按住 BOOT 点复位） */
void usb_link_reboot_to_download(void);

#pragma once
/* 音频服务（联调档）：I2S 全双工共享时钟、麦克风 → UAC、提示音 → 功放。
 *
 * 启停原则：没有录音、自检、播放时停时钟、关功放。
 * 录音期间不播放；提示音被录音抢占时走 5 ms 渐出。
 * 麦克风 VDD 直连 3V3，软件闸门不等于物理断电（规格 AUD 02）。 */
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

esp_err_t audio_svc_init(void);
/* 主循环每轮调用。power = 麦克风需要时钟；permit = 隐私闸门。闸门关闭时当场清空待发音频 */
void audio_svc_set_mic(bool power, bool permit);
/* 主机当前是否在收麦克风流。掉配置时清标志，所以由主循环每轮调用 */
bool audio_svc_streaming(void);
/* 取走“需要结束录音”的请求（UAC 溢出或 I2S 读失败）。*failed 为 true 表示采集故障 */
bool audio_svc_take_abort(bool *failed);
/* 配置通道入口，返回 AK_DCFG_* 结果码并写 16 字节状态（格式见 devcfg.h） */
uint8_t audio_svc_config(uint8_t op, uint32_t hz, uint32_t ms, uint32_t atten_db, uint8_t status[16]);

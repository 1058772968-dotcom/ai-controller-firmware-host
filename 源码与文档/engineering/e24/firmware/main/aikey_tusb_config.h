#pragma once
/* 在 esp_tinyusb 的配置上加 UAC 麦克风，不改托管组件源码。 */
#include "../managed_components/espressif__esp_tinyusb/include/tusb_config.h"
#define CFG_TUD_AUDIO 1
#define CFG_TUD_AUDIO_ENABLE_EP_IN 1
#define CFG_TUD_AUDIO_FUNC_1_SAMPLE_RATE 16000
#define CFG_TUD_AUDIO_FUNC_1_N_BYTES_PER_SAMPLE_TX 2
#define CFG_TUD_AUDIO_FUNC_1_N_CHANNELS_TX 1
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX 34
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SW_BUF_SZ 1280   /* 40 ms，音频任务每 10 ms 写一块 */

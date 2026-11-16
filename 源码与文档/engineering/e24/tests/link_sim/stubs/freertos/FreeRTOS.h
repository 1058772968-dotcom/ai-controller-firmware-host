#pragma once
/* 虚拟时钟下的 FreeRTOS 替身：1 tick = 1 ms，同一时刻只有一个任务在跑。 */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
typedef void *TaskHandle_t;
typedef void *QueueHandle_t;
typedef void *SemaphoreHandle_t;
typedef int BaseType_t;
typedef uint32_t TickType_t;
#define pdTRUE 1
#define pdFALSE 0
#define portMAX_DELAY 0xffffffffu
#define pdMS_TO_TICKS(x) ((TickType_t)(x))

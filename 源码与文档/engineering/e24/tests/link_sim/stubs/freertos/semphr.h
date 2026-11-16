#pragma once
#include "freertos/FreeRTOS.h"
/* 一次只跑一个任务且持锁期间不让出，锁天然成立 */
#define xSemaphoreCreateMutex() ((SemaphoreHandle_t)1)
#define xSemaphoreTake(s, t) (pdTRUE)
#define xSemaphoreGive(s) (pdTRUE)

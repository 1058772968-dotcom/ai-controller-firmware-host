#pragma once
#include "freertos/FreeRTOS.h"
void vTaskDelay(TickType_t ticks);
BaseType_t xTaskNotifyGive(TaskHandle_t h);
uint32_t ulTaskNotifyTake(BaseType_t clear, TickType_t timeout);
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void *), const char *name, uint32_t stack, void *arg, unsigned prio, TaskHandle_t *out, int core);

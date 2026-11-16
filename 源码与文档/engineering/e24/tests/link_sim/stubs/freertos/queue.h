#pragma once
#include "freertos/FreeRTOS.h"
QueueHandle_t xQueueCreate(unsigned depth, unsigned item);
BaseType_t xQueueSend(QueueHandle_t q, const void *item, TickType_t t);
BaseType_t xQueueReceive(QueueHandle_t q, void *out, TickType_t t);
BaseType_t xQueueReset(QueueHandle_t q);

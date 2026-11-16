#pragma once
#include <stdbool.h>
#include "pointer.h"
/* 指向参数存 NVS（命名空间 e24，键 ptr，16 字节线格式）。读取失败返回 false，不擦除。 */
bool ptr_store_load(ak_pointer_cfg *cfg);
bool ptr_store_save(const uint8_t wire[AK_POINTER_WIRE_SIZE]);

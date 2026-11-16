#pragma once
#include <stdint.h>
#define RTC_CNTL_OPTION1_REG 1
#define RTC_CNTL_FORCE_DOWNLOAD_BOOT 1
#define RTC_CNTL_USB_CONF_REG 2
#define RTC_CNTL_SW_HW_USB_PHY_SEL 1
#define RTC_CNTL_SW_USB_PHY_SEL 2
#define RTC_CNTL_USB_PAD_ENABLE 4
void sim_reg_write(int reg, uint32_t v);
#define REG_WRITE(r, v) sim_reg_write(r, v)
#define CLEAR_PERI_REG_MASK(r, m) sim_reg_write(r, 0)

#pragma once
void app_bringup(void);       /* 点亮档：只用 GPIO，日志走 USB-Serial-JTAG */
void app_link(void);          /* 联调档：TinyUSB 复合设备 + BMI270 指向 */
void app_report_identity(void);

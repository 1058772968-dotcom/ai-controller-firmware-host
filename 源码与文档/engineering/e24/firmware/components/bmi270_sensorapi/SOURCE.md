# BMI270 SensorAPI 来源

- 上游：Bosch Sensortec BMI270_SensorAPI（BSD-3-Clause），经 ESP 组件库 espressif2022/bmi270 **1.1.0~2** 打包（commit 87fb95766e71bcec928894dd8d06ed867f11737b）。
- 取自本机已下载的组件缓存，不新增网络下载；复制前逐个文件与组件自带 CHECKSUMS.json 比对一致。
- E24 补丁（只删包装，不改 Bosch 算法和配置数据）：
  1. bmi2.h 去掉 `#include "i2c_bus.h"`（Espressif 的旧 I²C 驱动，与 IDF 5.2 新 i2c_master 驱动混用会运行期报错）。
  2. bmi270.h / bmi270.c 去掉 bmi270_sensor_create/del 包装和 common/common.h。
- I²C 读写和延时回调在 `drivers/imu_bmi270` 里用 i2c_master 实现。

| 文件 | 原始 SHA-256 | E24 补丁后 SHA-256 |
|---|---|---|
| bmi2.c | 8c4c395106e1d3ec… | 8c4c395106e1d3ec… |
| bmi270.c | da3c98615177e4b1… | 808dca749135399a… |
| include/bmi2.h | 7e9064259c646477… | 51df1fc8d776f31c… |
| include/bmi2_defs.h | 2e2474895d636bc4… | 2e2474895d636bc4… |
| include/bmi270.h | aa672efce02927e3… | f48b516adf0e78a0… |

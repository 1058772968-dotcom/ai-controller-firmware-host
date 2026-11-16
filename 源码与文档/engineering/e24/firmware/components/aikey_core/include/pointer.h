#ifndef AIKEY_POINTER_H
#define AIKEY_POINTER_H
/* 陀螺仪 → 光标（相对指向）。纯 C，不依赖 IDF，可在电脑端测试。
 *
 * 流水线（每个 IMU 样本一次）：
 *   传感器轴 → 设备轴（axis_map） → 去零偏 → 重力补偿（握持滚转时仍按“世界水平/竖直”出光标）
 *   → 分层平滑（只在慢速时平滑，快速时零延迟） → 软死区（压手抖，无台阶）
 *   → 增益与加速曲线 → 亚像素累积 → 点击稳定（按键沿前后冻结） → 整数位移
 *
 * 设备坐标系约定：+X 向右，+Y 指向前端（握持时指向屏幕），+Z 从正面向外。
 * 平滑只在固件做一次；上位机不得对 0x81 位移再做平滑（双重平滑是“跟手感差”的常见原因）。 */
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    float counts_per_deg;   /* 基础灵敏度：每转 1° 输出多少计数（约等于像素） */
    float accel_gain;       /* 高速时额外倍率，1 = 无加速 */
    float accel_lo_dps;     /* 低于此角速度不加速 */
    float accel_hi_dps;     /* 高于此角速度满加速 */
    float deadzone_dps;     /* 软死区：低于它按平方衰减 */
    float smooth_lo_dps;    /* 低于此速度全量平滑 */
    float smooth_hi_dps;    /* 高于此速度不平滑 */
    float smooth_tau_ms;    /* 平滑时间常数 */
    uint16_t click_freeze_ms; /* 按键按下/松开后冻结光标的时间 */
    bool invert_x, invert_y;
    bool gravity_comp;      /* true：按重力方向分解偏航/俯仰 */
    uint8_t axis_src[3];    /* 设备 X/Y/Z 取自传感器第几轴（0..2） */
    uint8_t axis_neg;       /* bit i = 设备第 i 轴取反 */
} ak_pointer_cfg;

typedef enum { AK_PTR_UNCALIBRATED = 0, AK_PTR_CALIBRATING, AK_PTR_ACTIVE } ak_pointer_state;

typedef struct {
    ak_pointer_cfg cfg;
    ak_pointer_state state;
    float bias[3];          /* 设备轴零偏，°/s */
    float cal_sum[3];
    uint32_t cal_count, cal_started_ms;
    uint32_t still_ms;      /* 连续静止时长 */
    uint32_t track_ms;      /* 连续满足温漂跟踪门限的时长 */
    float up[3];            /* 估计的“上”方向（设备坐标，单位向量） */
    bool up_valid;
    float smooth[2];        /* 平滑后的 (水平, 竖直) 角速度 */
    float residual[2];      /* 亚像素余量 */
    uint32_t freeze_until_ms;
    bool still;
} ak_pointer;

void ak_pointer_default_cfg(ak_pointer_cfg *cfg);
bool ak_pointer_cfg_valid(const ak_pointer_cfg *cfg);
void ak_pointer_init(ak_pointer *p, const ak_pointer_cfg *cfg);
/* 更换参数不丢零偏和校准状态 */
void ak_pointer_set_cfg(ak_pointer *p, const ak_pointer_cfg *cfg);
/* 强制重新校准：需要静置约 1.2 s；期间不出光标 */
void ak_pointer_calibrate(ak_pointer *p, uint32_t now_ms);
/* 居中：只清余量和平滑状态，不动零偏（电脑端负责把光标移到屏幕中心） */
void ak_pointer_recenter(ak_pointer *p);
/* 任意按键按下或松开时调用，启动点击稳定 */
void ak_pointer_button_edge(ak_pointer *p, uint32_t now_ms);
/* 输入一帧：gyro_dps / accel_g 为传感器坐标，dt 秒。输出整数位移（屏幕右/下为正）。
 * 返回 false 表示样本无效或尚未校准（位移为 0）。 */
bool ak_pointer_feed(ak_pointer *p, const float gyro_dps[3], const float accel_g[3],
                     float dt, uint32_t now_ms, int16_t *dx, int16_t *dy);
static inline bool ak_pointer_calibrated(const ak_pointer *p) { return p->state == AK_PTR_ACTIVE; }

/* 调试遥测用：最近一帧处理后的水平/竖直角速度（°/s，未加增益） */
void ak_pointer_last_rates(const ak_pointer *p, float *h_dps, float *v_dps);

/* 参数在配置通道（USB 报告 3）上的 16 字节编码，见联调预案 */
#define AK_POINTER_WIRE_SIZE 16
void ak_pointer_cfg_encode(const ak_pointer_cfg *cfg, uint8_t out[AK_POINTER_WIRE_SIZE]);
bool ak_pointer_cfg_decode(const uint8_t in[AK_POINTER_WIRE_SIZE], ak_pointer_cfg *cfg);
#endif

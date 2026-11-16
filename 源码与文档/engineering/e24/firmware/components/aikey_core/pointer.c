#include "pointer.h"
#include <math.h>
#include <string.h>

#define CAL_WINDOW_MS 1200u      /* 与旧 GRIP 上位机一致：静置 1.2 s 完成零偏 */
#define TRACK_AFTER_MS 1500u     /* 已校准后，静止超过此时长才慢速跟踪温漂 */
#define TRACK_ALPHA 0.0005f     /* 200 Hz 下 τ≈10 s：只跟温漂 */
#define TRACK_DEV_DPS 0.6f       /* 相对零偏超过它就不是温漂 */
#define STILL_DEV_DPS 1.5f       /* 相对慢速均值的抖动上限 */
#define STILL_ACC_TOL 0.08f      /* |a| 偏离 1 g 的上限 */
#define UP_BLEND 0.02f           /* 重力方向互补滤波：加速度计权重 */
#define DEG2RAD 0.017453292519943295f

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
static float dot3(const float a[3], const float b[3]) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
static float norm3(const float a[3]) { return sqrtf(dot3(a, a)); }

void ak_pointer_default_cfg(ak_pointer_cfg *c)
{
    memset(c, 0, sizeof(*c));
    c->counts_per_deg = 28.0f;   /* 旧 GRIP 上位机 sensitivity=28 */
    c->accel_gain = 1.8f;
    c->accel_lo_dps = 30.0f;
    c->accel_hi_dps = 250.0f;
    c->deadzone_dps = 0.7f;      /* 旧 GRIP 上位机 deadzone=0.7 */
    c->smooth_lo_dps = 4.0f;
    c->smooth_hi_dps = 15.0f;
    c->smooth_tau_ms = 40.0f;
    c->click_freeze_ms = 70;
    c->gravity_comp = true;
    c->axis_src[0] = 0; c->axis_src[1] = 1; c->axis_src[2] = 2;
}

bool ak_pointer_cfg_valid(const ak_pointer_cfg *c)
{
    if (!c) return false;
    if (!(c->counts_per_deg >= 1.0f && c->counts_per_deg <= 200.0f)) return false;
    if (!(c->accel_gain >= 1.0f && c->accel_gain <= 4.0f)) return false;
    if (!(c->accel_lo_dps >= 0.0f && c->accel_hi_dps > c->accel_lo_dps && c->accel_hi_dps <= 510.0f)) return false;
    if (!(c->deadzone_dps >= 0.0f && c->deadzone_dps <= 5.0f)) return false;
    if (!(c->smooth_lo_dps >= 0.0f && c->smooth_hi_dps >= c->smooth_lo_dps && c->smooth_hi_dps <= 255.0f)) return false;
    if (!(c->smooth_tau_ms >= 0.0f && c->smooth_tau_ms <= 200.0f)) return false;
    if (c->click_freeze_ms > 255) return false;
    uint8_t seen = 0;
    for (int i = 0; i < 3; i++) {
        if (c->axis_src[i] > 2) return false;
        seen |= (uint8_t)(1u << c->axis_src[i]);
    }
    return seen == 7 && c->axis_neg <= 7;
}

static void reset_motion(ak_pointer *p)
{
    p->smooth[0] = p->smooth[1] = 0;
    p->residual[0] = p->residual[1] = 0;
}

void ak_pointer_init(ak_pointer *p, const ak_pointer_cfg *cfg)
{
    memset(p, 0, sizeof(*p));
    if (cfg && ak_pointer_cfg_valid(cfg)) p->cfg = *cfg;
    else ak_pointer_default_cfg(&p->cfg);
    p->state = AK_PTR_UNCALIBRATED;   /* 上电先自动找静止窗口校准 */
}

void ak_pointer_set_cfg(ak_pointer *p, const ak_pointer_cfg *cfg)
{
    if (!ak_pointer_cfg_valid(cfg)) return;
    bool axes_changed = memcmp(p->cfg.axis_src, cfg->axis_src, 3) || p->cfg.axis_neg != cfg->axis_neg;
    p->cfg = *cfg;
    reset_motion(p);
    if (axes_changed) {           /* 轴映射变了，原零偏和重力方向都不再对应 */
        p->state = AK_PTR_UNCALIBRATED;
        p->up_valid = false;
        p->cal_count = 0;
    }
}

void ak_pointer_calibrate(ak_pointer *p, uint32_t now_ms)
{
    p->state = AK_PTR_CALIBRATING;
    p->cal_count = 0;
    p->cal_started_ms = now_ms;
    memset(p->cal_sum, 0, sizeof p->cal_sum);
    reset_motion(p);
}

void ak_pointer_recenter(ak_pointer *p) { reset_motion(p); }

void ak_pointer_button_edge(ak_pointer *p, uint32_t now_ms)
{
    p->freeze_until_ms = now_ms + p->cfg.click_freeze_ms;
    p->residual[0] = p->residual[1] = 0;
}

void ak_pointer_last_rates(const ak_pointer *p, float *h, float *v)
{
    if (h) *h = p->smooth[0];
    if (v) *v = p->smooth[1];
}

static bool time_before(uint32_t a, uint32_t b) { return (int32_t)(a - b) < 0; }

bool ak_pointer_feed(ak_pointer *p, const float gs[3], const float as[3], float dt,
                     uint32_t now_ms, int16_t *dx, int16_t *dy)
{
    *dx = *dy = 0;
    for (int i = 0; i < 3; i++)
        if (!isfinite(gs[i]) || !isfinite(as[i])) { reset_motion(p); return false; }
    if (!isfinite(dt) || dt <= 0.0f || dt > 0.05f) { reset_motion(p); return false; }

    /* 1. 传感器轴 → 设备轴 */
    float g[3], a[3];
    for (int i = 0; i < 3; i++) {
        float s = (p->cfg.axis_neg >> i) & 1 ? -1.0f : 1.0f;
        g[i] = s * gs[p->cfg.axis_src[i]];
        a[i] = s * as[p->cfg.axis_src[i]];
    }

    /* 2. 静止判定：与零偏无关（看抖动与 1 g），供校准和温漂跟踪使用 */
    float an = norm3(a);
    float ref[3];
    for (int i = 0; i < 3; i++) ref[i] = p->state == AK_PTR_ACTIVE ? p->bias[i] : (p->cal_count ? p->cal_sum[i] / (float)p->cal_count : g[i]);
    float dev = 0;
    for (int i = 0; i < 3; i++) dev = fmaxf(dev, fabsf(g[i] - ref[i]));
    bool still = fabsf(an - 1.0f) < STILL_ACC_TOL && dev < (p->state == AK_PTR_ACTIVE ? 2.5f : STILL_DEV_DPS);
    p->still_ms = still ? p->still_ms + (uint32_t)(dt * 1000.0f + 0.5f) : 0;
    p->still = still;

    /* 3. 重力方向：陀螺积分 + 加速度计互补校正 */
    if (an > 0.5f) {
        if (!p->up_valid) {
            for (int i = 0; i < 3; i++) p->up[i] = a[i] / an;
            p->up_valid = true;
        } else {
            float w[3];
            for (int i = 0; i < 3; i++) w[i] = (g[i] - (p->state == AK_PTR_ACTIVE ? p->bias[i] : 0)) * DEG2RAD * dt;
            float u[3] = {p->up[0], p->up[1], p->up[2]};
            /* 世界固定向量在机体系中：du = -w × u */
            p->up[0] = u[0] - (w[1] * u[2] - w[2] * u[1]);
            p->up[1] = u[1] - (w[2] * u[0] - w[0] * u[2]);
            p->up[2] = u[2] - (w[0] * u[1] - w[1] * u[0]);
            float k = fabsf(an - 1.0f) < 0.2f ? UP_BLEND : 0.0f;
            for (int i = 0; i < 3; i++) p->up[i] = (1.0f - k) * p->up[i] + k * a[i] / an;
            float n = norm3(p->up);
            for (int i = 0; i < 3; i++) p->up[i] /= n;
        }
    }

    /* 4. 校准：连续静止 1.2 s 取均值；中途一动就重来 */
    if (p->state != AK_PTR_ACTIVE) {
        if (!still) {
            p->cal_count = 0;
            memset(p->cal_sum, 0, sizeof p->cal_sum);
            if (p->state == AK_PTR_UNCALIBRATED || p->state == AK_PTR_CALIBRATING) p->cal_started_ms = now_ms;
        } else {
            if (!p->cal_count) p->cal_started_ms = now_ms;
            for (int i = 0; i < 3; i++) p->cal_sum[i] += g[i];
            p->cal_count++;
            if (!time_before(now_ms, p->cal_started_ms + CAL_WINDOW_MS)) {
                for (int i = 0; i < 3; i++) p->bias[i] = p->cal_sum[i] / (float)p->cal_count;
                p->state = AK_PTR_ACTIVE;
                reset_motion(p);
            }
        }
        return false;
    }
    p->track_ms = still && dev < TRACK_DEV_DPS ? p->track_ms + (uint32_t)(dt * 1000.0f + 0.5f) : 0;
    if (p->track_ms > TRACK_AFTER_MS)
        for (int i = 0; i < 3; i++) p->bias[i] += TRACK_ALPHA * (g[i] - p->bias[i]);

    /* 5. 去零偏后分解为 水平(h, 右为正) / 竖直(v, 下为正) 角速度 */
    float w[3] = {g[0] - p->bias[0], g[1] - p->bias[1], g[2] - p->bias[2]};
    float h, v;
    float r[3] = {1, 0, 0};
    float rn = 0;
    if (p->cfg.gravity_comp && p->up_valid) {
        float xu = p->up[0];
        r[0] = 1 - xu * p->up[0]; r[1] = -xu * p->up[1]; r[2] = -xu * p->up[2];
        rn = norm3(r);
    }
    if (rn > 0.3f) {
        for (int i = 0; i < 3; i++) r[i] /= rn;
        h = -dot3(w, p->up);      /* 绕“上”逆时针 = 向左转 → 光标向左 */
        v = -dot3(w, r);          /* 绕“右”正转 = 抬头 → 光标向上 */
    } else {
        h = -w[2];                /* 无重力补偿或竖直握持：按设备 Z/X 轴 */
        v = -w[0];
    }

    /* 6. 分层平滑：慢速时平滑压抖，快速时直通保证跟手 */
    float s = hypotf(h, v);
    float alpha = p->cfg.smooth_tau_ms > 0 ? dt / (p->cfg.smooth_tau_ms * 0.001f + dt) : 1.0f;
    p->smooth[0] += alpha * (h - p->smooth[0]);
    p->smooth[1] += alpha * (v - p->smooth[1]);
    float span = p->cfg.smooth_hi_dps - p->cfg.smooth_lo_dps;
    float wraw = span > 0 ? clampf((s - p->cfg.smooth_lo_dps) / span, 0, 1) : (s >= p->cfg.smooth_hi_dps ? 1.0f : 0.0f);
    float oh = wraw * h + (1 - wraw) * p->smooth[0];
    float ov = wraw * v + (1 - wraw) * p->smooth[1];

    /* 7. 软死区：低于阈值按 s/dz 衰减，连续无台阶 */
    float so = hypotf(oh, ov);
    if (p->cfg.deadzone_dps > 0 && so < p->cfg.deadzone_dps) {
        float k = so / p->cfg.deadzone_dps;
        oh *= k; ov *= k;
        so *= k;
    }

    /* 8. 增益与加速曲线 */
    float t = clampf((so - p->cfg.accel_lo_dps) / (p->cfg.accel_hi_dps - p->cfg.accel_lo_dps), 0, 1);
    float gain = p->cfg.counts_per_deg * (1.0f + (p->cfg.accel_gain - 1.0f) * t) * dt;
    float mx = oh * gain * (p->cfg.invert_x ? -1.0f : 1.0f);
    float my = ov * gain * (p->cfg.invert_y ? -1.0f : 1.0f);

    /* 9. 点击稳定：按键沿后的一小段时间丢弃位移（不是延后补发） */
    if (time_before(now_ms, p->freeze_until_ms)) {
        p->residual[0] = p->residual[1] = 0;
        return true;
    }

    /* 10. 亚像素累积：慢速微动不丢失 */
    p->residual[0] += mx;
    p->residual[1] += my;
    float ix = truncf(p->residual[0]), iy = truncf(p->residual[1]);
    ix = clampf(ix, -32767, 32767);
    iy = clampf(iy, -32767, 32767);
    p->residual[0] -= ix;
    p->residual[1] -= iy;
    p->residual[0] = clampf(p->residual[0], -1, 1);
    p->residual[1] = clampf(p->residual[1], -1, 1);
    *dx = (int16_t)ix;
    *dy = (int16_t)iy;
    return true;
}

static void put16(uint8_t *b, uint16_t v) { b[0] = (uint8_t)v; b[1] = (uint8_t)(v >> 8); }
static uint16_t get16(const uint8_t *b) { return (uint16_t)(b[0] | b[1] << 8); }
static uint8_t q8(float v, float scale) { float x = v * scale + 0.5f; return (uint8_t)clampf(x, 0, 255); }
static uint16_t q16(float v, float scale) { float x = v * scale + 0.5f; return (uint16_t)clampf(x, 0, 65535); }

void ak_pointer_cfg_encode(const ak_pointer_cfg *c, uint8_t o[AK_POINTER_WIRE_SIZE])
{
    memset(o, 0, AK_POINTER_WIRE_SIZE);
    put16(o + 0, q16(c->counts_per_deg, 100));
    put16(o + 2, q16(c->accel_gain, 100));
    o[4] = q8(c->accel_lo_dps, 1);
    o[5] = q8(c->accel_hi_dps, 0.5f);
    o[6] = q8(c->deadzone_dps, 10);
    o[7] = q8(c->smooth_lo_dps, 1);
    o[8] = q8(c->smooth_hi_dps, 1);
    o[9] = q8(c->smooth_tau_ms, 1);
    o[10] = (uint8_t)(c->click_freeze_ms > 255 ? 255 : c->click_freeze_ms);
    o[11] = (uint8_t)((c->invert_x ? 1 : 0) | (c->invert_y ? 2 : 0) | (c->gravity_comp ? 4 : 0));
    o[12] = (uint8_t)(c->axis_src[0] | c->axis_src[1] << 2 | c->axis_src[2] << 4);
    o[13] = c->axis_neg;
}

bool ak_pointer_cfg_decode(const uint8_t in[AK_POINTER_WIRE_SIZE], ak_pointer_cfg *c)
{
    if (in[14] || in[15] || (in[11] & ~7u) || (in[12] & 0xC0) || (in[13] & ~7u)) return false;
    ak_pointer_cfg t;
    memset(&t, 0, sizeof t);
    t.counts_per_deg = get16(in + 0) / 100.0f;
    t.accel_gain = get16(in + 2) / 100.0f;
    t.accel_lo_dps = in[4];
    t.accel_hi_dps = in[5] * 2.0f;
    t.deadzone_dps = in[6] / 10.0f;
    t.smooth_lo_dps = in[7];
    t.smooth_hi_dps = in[8];
    t.smooth_tau_ms = in[9];
    t.click_freeze_ms = in[10];
    t.invert_x = in[11] & 1;
    t.invert_y = (in[11] >> 1) & 1;
    t.gravity_comp = (in[11] >> 2) & 1;
    t.axis_src[0] = in[12] & 3;
    t.axis_src[1] = (in[12] >> 2) & 3;
    t.axis_src[2] = (in[12] >> 4) & 3;
    t.axis_neg = in[13];
    if (!ak_pointer_cfg_valid(&t)) return false;
    *c = t;
    return true;
}

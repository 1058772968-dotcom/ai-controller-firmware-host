/* 陀螺仪指向核心的电脑端仿真测试：200 Hz 合成 IMU 数据，覆盖校准、精细慢移、
 * 手抖、快速甩动、点击稳定、握持滚转补偿、温漂跟踪与参数编码。
 * 只证明算法行为符合设计目标，不代表真机手感已通过。 */
#include "pointer.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DT 0.005f
static uint32_t now;
static uint32_t rng = 12345;
static float noise(float sigma)
{
    float s = 0;
    for (int i = 0; i < 6; i++) { rng = rng * 1664525u + 1013904223u; s += (float)(rng >> 8) / 16777216.0f - 0.5f; }
    return s * sigma * 1.414f;  /* 6 个均匀分布之和，近似高斯 */
}
static const float BIAS[3] = {1.2f, -0.8f, 0.5f};
static const float FLAT[3] = {0, 0, 1};

typedef struct { long sx, sy, path; int first_nonzero; } run_t;

static run_t run(ak_pointer *p, float secs, const float rate[3], const float acc[3], float sigma)
{
    run_t r = {0, 0, 0, -1};
    int n = (int)(secs / DT + 0.5f);
    for (int i = 0; i < n; i++) {
        float g[3], a[3];
        for (int k = 0; k < 3; k++) { g[k] = BIAS[k] + rate[k] + noise(sigma); a[k] = acc[k] + noise(0.004f); }
        int16_t dx, dy;
        ak_pointer_feed(p, g, a, DT, now, &dx, &dy);
        now += 5;
        r.sx += dx; r.sy += dy; r.path += labs(dx) + labs(dy);
        if (r.first_nonzero < 0 && (dx || dy)) r.first_nonzero = i;
    }
    return r;
}

static void calibrated(ak_pointer *p, const ak_pointer_cfg *cfg)
{
    ak_pointer_init(p, cfg);
    float zero[3] = {0};
    run_t r = run(p, 1.3f, zero, FLAT, 0.08f);
    assert(ak_pointer_calibrated(p));
    assert(r.sx == 0 && r.sy == 0);
}

int main(void)
{
    ak_pointer p;
    ak_pointer_cfg cfg;
    ak_pointer_default_cfg(&cfg);
    assert(ak_pointer_cfg_valid(&cfg));
    float zero[3] = {0};

    /* 1. 静置校准 + 10 s 静止漂移 */
    calibrated(&p, &cfg);
    for (int k = 0; k < 3; k++) assert(fabsf(p.bias[k] - BIAS[k]) < 0.05f);
    run_t r = run(&p, 10.0f, zero, FLAT, 0.08f);
    printf("静止 10 s 漂移：dx=%ld dy=%ld 路径=%ld 计数\n", r.sx, r.sy, r.path);
    assert(labs(r.sx) <= 2 && labs(r.sy) <= 2 && r.path <= 4);

    /* 2. 校准中途晃动必须重来，不能把运动当零偏 */
    ak_pointer_init(&p, &cfg);
    run(&p, 0.6f, zero, FLAT, 0.08f);
    float shake[3] = {0, 0, 50};
    run(&p, 0.1f, shake, FLAT, 0.08f);
    run(&p, 0.6f, zero, FLAT, 0.08f);
    assert(!ak_pointer_calibrated(&p));
    run(&p, 0.7f, zero, FLAT, 0.08f);
    assert(ak_pointer_calibrated(&p));
    for (int k = 0; k < 3; k++) assert(fabsf(p.bias[k] - BIAS[k]) < 0.05f);

    /* 3. 精细慢移：向右转 3°/s 持续 2 s ≈ 6° × 28 = 168 计数 */
    calibrated(&p, &cfg);
    float slow_right[3] = {0, 0, -3};
    r = run(&p, 2.0f, slow_right, FLAT, 0.08f);
    printf("慢移 3°/s × 2 s：dx=%ld dy=%ld（理想 168）首个输出在第 %d 帧\n", r.sx, r.sy, r.first_nonzero);
    assert(r.sx > 150 && r.sx < 175 && labs(r.sy) <= 3);

    /* 4. 手抖：8 Hz、±0.3°/s 正弦抖动 3 s，光标基本不动 */
    calibrated(&p, &cfg);
    long tx = 0, tpath = 0;
    for (int i = 0; i < 600; i++) {
        float tr[3] = {0.3f * sinf(2 * 3.14159f * 8 * i * DT), 0, 0.3f * sinf(2 * 3.14159f * 8 * i * DT + 1)};
        run_t s = run(&p, DT, tr, FLAT, 0.08f);
        tx += s.sx; tpath += s.path;
    }
    printf("手抖 8 Hz ±0.3°/s × 3 s：净位移 %ld，路径 %ld 计数\n", tx, tpath);
    assert(labs(tx) <= 3 && tpath <= 12);

    /* 5. 快速甩动：300°/s × 0.15 s；第一帧就要有输出（高速不平滑） */
    calibrated(&p, &cfg);
    float flick[3] = {0, 0, -300};
    r = run(&p, 0.15f, flick, FLAT, 0.08f);
    printf("甩动 300°/s × 0.15 s：dx=%ld（无加速 1260）首个输出在第 %d 帧\n", r.sx, r.first_nonzero);
    assert(r.first_nonzero == 0 && r.sx > 1500 && r.sx < 2400);

    /* 6. 点击稳定：匀速移动中按键，70 ms 内不出位移，随后恢复 */
    calibrated(&p, &cfg);
    float move[3] = {0, 0, -20};
    run(&p, 0.2f, move, FLAT, 0.08f);
    ak_pointer_button_edge(&p, now);
    r = run(&p, 0.065f, move, FLAT, 0.08f);
    assert(r.sx == 0 && r.sy == 0);
    r = run(&p, 0.1f, move, FLAT, 0.08f);
    assert(r.sx > 20);
    printf("点击稳定：按键后 65 ms 位移 0，之后 100 ms 恢复 %ld 计数\n", r.sx);

    /* 7. 握持滚转 45°：世界水平向右转，光标应基本水平 */
    float c45 = 0.7071f;
    float rolled_up[3] = {-c45, 0, c45};
    float turn[3] = {20 * c45, 0, -20 * c45};   /* ω = -20°/s × up */
    calibrated(&p, &cfg);
    run(&p, 0.5f, zero, rolled_up, 0.08f);      /* 让重力估计收敛到新姿态 */
    r = run(&p, 1.0f, turn, rolled_up, 0.08f);
    printf("滚转 45° 补偿开：dx=%ld dy=%ld\n", r.sx, r.sy);
    assert(r.sx > 400 && labs(r.sy) * 10 < r.sx);
    ak_pointer_cfg nc = cfg;
    nc.gravity_comp = false;
    calibrated(&p, &nc);
    run(&p, 0.5f, zero, rolled_up, 0.08f);
    r = run(&p, 1.0f, turn, rolled_up, 0.08f);
    printf("滚转 45° 补偿关：dx=%ld dy=%ld（对照：斜着走）\n", r.sx, r.sy);
    assert(labs(r.sy) * 2 > labs(r.sx));

    /* 8. 温漂跟踪：静止时零偏缓慢跟上；运动时不改零偏 */
    calibrated(&p, &cfg);
    float b0 = p.bias[2];
    float drift[3] = {0, 0, 0.3f};
    run(&p, 30.0f, drift, FLAT, 0.08f);
    printf("温漂 +0.3°/s 静止 30 s 后零偏变化 %.3f\n", p.bias[2] - b0);
    assert(fabsf(p.bias[2] - (b0 + 0.3f)) < 0.05f);
    float b1 = p.bias[2];
    float steady[3] = {0, 0, -40};
    run(&p, 2.0f, steady, FLAT, 0.08f);
    assert(fabsf(p.bias[2] - b1) < 1e-4f);

    /* 9. 非法样本 */
    int16_t dx, dy;
    float bad[3] = {NAN, 0, 0};
    assert(!ak_pointer_feed(&p, bad, FLAT, DT, now, &dx, &dy) && dx == 0 && dy == 0);
    float g0[3] = {0};
    assert(!ak_pointer_feed(&p, g0, FLAT, 0.2f, now, &dx, &dy));

    /* 10. 配置编码往返与反例 */
    uint8_t w[AK_POINTER_WIRE_SIZE];
    ak_pointer_cfg_encode(&cfg, w);
    ak_pointer_cfg back;
    assert(ak_pointer_cfg_decode(w, &back));
    assert(fabsf(back.counts_per_deg - cfg.counts_per_deg) < 0.01f && back.click_freeze_ms == cfg.click_freeze_ms);
    assert(back.gravity_comp && back.axis_src[2] == 2);
    uint8_t b2[AK_POINTER_WIRE_SIZE];
    memcpy(b2, w, sizeof b2); b2[15] = 1; assert(!ak_pointer_cfg_decode(b2, &back));
    memcpy(b2, w, sizeof b2); b2[12] = 0; assert(!ak_pointer_cfg_decode(b2, &back));     /* 三轴同源 */
    memcpy(b2, w, sizeof b2); b2[0] = 0; b2[1] = 0; assert(!ak_pointer_cfg_decode(b2, &back)); /* 灵敏度 0 */
    memcpy(b2, w, sizeof b2); b2[4] = 250; b2[5] = 10; assert(!ak_pointer_cfg_decode(b2, &back)); /* lo>hi */

    /* 11. 改轴映射必须重新校准 */
    calibrated(&p, &cfg);
    ak_pointer_cfg sw = cfg;
    sw.axis_src[0] = 1; sw.axis_src[1] = 0;
    ak_pointer_set_cfg(&p, &sw);
    assert(!ak_pointer_calibrated(&p));

    puts("PASS 校准/重来/静止漂移/慢移/手抖/甩动/点击稳定/滚转补偿/温漂/非法样本/编码/轴映射");
    return 0;
}

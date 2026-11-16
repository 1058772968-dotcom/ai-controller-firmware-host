#ifndef AK_MOTION_H
#define AK_MOTION_H
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    float bias[3], sum[3], fraction_x, fraction_y, gain;
    unsigned stationary_samples;
    bool calibrated;
} ak_motion;
void ak_motion_init(ak_motion *m);
void ak_motion_recenter(ak_motion *m);
bool ak_motion_step(ak_motion *m, const float gyro_dps[3], const float accel_g[3], float dt, int16_t *dx, int16_t *dy);
#endif

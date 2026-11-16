/* 把未改动的 link_app.c 编进来，这样模拟器能读到它的静态变量（只读），不用改固件源码。 */
#include "link_app.c"
#include <stdarg.h>

int sim_state_json(char *o, size_t n)
{
    return snprintf(o, n,
        "{\"session\":%u,\"owner\":%u,\"host_connected\":%d,\"buttons\":%u,\"raw\":%u,\"blocked\":%u,\"hid_buttons\":%u,"
        "\"faults\":%u,\"calibrated\":%d,\"command_sequence\":%u,\"acc_x\":%d,\"acc_y\":%d,\"ptr_state\":%d,"
        "\"bias\":[%.4f,%.4f,%.4f],\"still\":%d,\"telemetry\":%d,\"imu_ok\":%d}",
        (unsigned)s_ctrl.session, s_ctrl.owner, s_ctrl.host_connected, s_ctrl.buttons, s_ctrl.raw, s_ctrl.blocked, s_ctrl.hid_buttons,
        s_ctrl.hardware_faults, s_ctrl.calibrated, (unsigned)s_ctrl.command_sequence, (int)s_acc_x, (int)s_acc_y, (int)s_ptr.state,
        s_ptr.bias[0], s_ptr.bias[1], s_ptr.bias[2], s_ptr.still, s_telemetry, s_imu_ok);
}

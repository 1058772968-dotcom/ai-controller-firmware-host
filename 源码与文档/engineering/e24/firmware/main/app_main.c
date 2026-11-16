/* E24 入口：按 Kconfig 构建档位选择点亮程序或联调程序（见 engineering/e24/README.md）。 */
#include "app.h"
#include "sdkconfig.h"

void app_main(void)
{
#if CONFIG_E24_PROFILE_BRINGUP
    app_bringup();
#else
    app_link();
#endif
}

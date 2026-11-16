/* 全链路模拟器的设备端运行时。
 * 真实源码：link_app.c、usb_link.c、ptr_store.c、controller.c、protocol.c、devcfg.c、pointer.c（一行不改）。
 * 这里只替换它们下面的东西：FreeRTOS、TinyUSB 端点/CDC FIFO、BMI270 读数、NVS、GPIO。
 * 行为依据写在各段注释里；模型不是硬件证据，见 README。
 *
 * 与 run.mjs 的文本协议（一行一条）：
 *   入：t N 走 N ms | o id hex 主机发报告 | k mask 按键 | g gx gy gz ax ay az 真实角速度/加速度（传感器轴）
 *       m 0/1 枚举 | s 0/1 USB 挂起 | d 0/1 DTR | b baud | f 名 值 注入 | r 读状态 | x 退出
 *   出：I ms id hex 上行报告 | C hex CDC 字节 | L 日志 | X 事件 | R json | K 本批结束 */
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "app.h"
#include "audio_svc.h"
#include "bsp_e24.h"
#include "bsp_i2c.h"
#include "class/hid/hid_device.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "imu_bmi270.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "soc/rtc_cntl_reg.h"
#include "tinyusb.h"
#include "tusb_cdc_acm.h"
#include "tusb_console.h"

int sim_state_json(char *o, size_t n);

/* ---------- 时钟与随机数 ---------- */
static uint64_t s_ms;
static uint32_t s_rng = 0x2545F491u;
static uint32_t rnd(void) { s_rng ^= s_rng << 13; s_rng ^= s_rng >> 17; s_rng ^= s_rng << 5; return s_rng; }
static float gauss(void) { float a = 0; for (int i = 0; i < 6; i++) a += (float)(rnd() & 0xffff) / 65535.0f; return (a - 3.0f) * 1.414f; }
uint32_t esp_random(void) { return rnd(); }
int64_t esp_timer_get_time(void) { return (int64_t)s_ms * 1000 + 37; }
const char *esp_err_to_name(esp_err_t e) { return e ? "ERR" : "OK"; }

/* ---------- 任务：线程 + 接力棒，任一时刻只有一个在跑 ---------- */
typedef struct {
    pthread_t th; pthread_cond_t cv; int go, alive, prio, waiting, notified;
    uint64_t wake; void (*fn)(void *); void *arg;
} task_t;
static pthread_mutex_t s_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t s_sched = PTHREAD_COND_INITIALIZER;
static int s_sched_go;
static task_t s_tasks[6];
static int s_ntasks;
static task_t *s_cur;
static int s_halted;   /* esp_restart 后设备停摆 */

static void to_sched(task_t *me)
{
    me->go = 0; s_sched_go = 1; pthread_cond_signal(&s_sched);
    while (!me->go) pthread_cond_wait(&me->cv, &s_mu);
}
static void *task_entry(void *p)
{
    task_t *t = p;
    pthread_mutex_lock(&s_mu);
    while (!t->go) pthread_cond_wait(&t->cv, &s_mu);
    t->fn(t->arg);
    t->alive = 0;
    s_sched_go = 1; pthread_cond_signal(&s_sched);
    pthread_mutex_unlock(&s_mu);
    return NULL;
}
static task_t *spawn(void (*fn)(void *), void *arg, int prio)
{
    task_t *t = &s_tasks[s_ntasks++];
    memset(t, 0, sizeof *t);
    pthread_cond_init(&t->cv, NULL);
    t->fn = fn; t->arg = arg; t->prio = prio; t->alive = 1; t->wake = s_ms;
    pthread_create(&t->th, NULL, task_entry, t);
    return t;
}
static void run(task_t *t)
{
    s_cur = t; t->go = 1; s_sched_go = 0;
    pthread_cond_signal(&t->cv);
    while (!s_sched_go) pthread_cond_wait(&s_sched, &s_mu);
}
void vTaskDelay(TickType_t n) { task_t *me = s_cur; me->wake = s_ms + (n ? n : 1); me->waiting = 0; to_sched(me); }
uint32_t ulTaskNotifyTake(BaseType_t clear, TickType_t timeout)
{
    (void)clear;
    task_t *me = s_cur;
    if (!me->notified) { me->waiting = 1; me->wake = s_ms + timeout; to_sched(me); }
    uint32_t v = (uint32_t)me->notified; me->notified = 0; me->waiting = 0;
    return v;
}
BaseType_t xTaskNotifyGive(TaskHandle_t h) { ((task_t *)h)->notified = 1; return pdTRUE; }
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void *), const char *name, uint32_t st, void *arg, unsigned prio, TaskHandle_t *out, int core)
{
    (void)name; (void)st; (void)core;
    task_t *t = spawn(fn, arg, (int)prio);
    if (out) *out = t;
    return pdTRUE;
}

/* ---------- 队列 ---------- */
typedef struct { unsigned depth, item, head, count; uint8_t *buf; } q_t;
QueueHandle_t xQueueCreate(unsigned d, unsigned i) { q_t *q = calloc(1, sizeof *q); q->depth = d; q->item = i; q->buf = malloc(d * i); return q; }
BaseType_t xQueueSend(QueueHandle_t h, const void *it, TickType_t t)
{
    (void)t; q_t *q = h;
    if (q->count == q->depth) return pdFALSE;
    memcpy(q->buf + ((q->head + q->count) % q->depth) * q->item, it, q->item); q->count++;
    return pdTRUE;
}
BaseType_t xQueueReceive(QueueHandle_t h, void *o, TickType_t t)
{
    (void)t; q_t *q = h;
    if (!q->count) return pdFALSE;
    memcpy(o, q->buf + q->head * q->item, q->item); q->head = (q->head + 1) % q->depth; q->count--;
    return pdTRUE;
}
BaseType_t xQueueReset(QueueHandle_t h) { q_t *q = h; q->head = q->count = 0; return pdTRUE; }

/* ---------- CDC：TinyUSB 0.21 cdc_device.c 的行为 ----------
 * TX FIFO 512 B（sdkconfig.link）；DTR 低时 FIFO 可覆盖（只留最新字节），主机也不读 IN 端点；DTR 高时不可覆盖，满了写不进。
 * 控制台经 vfs_tinyusb.c tusb_write 逐字符写、\n→\r\n；遥测经 tinyusb_cdcacm_write_queue，可用空间不足时只写一部分。 */
#define CDC_CAP 512
static uint8_t s_cdc[CDC_CAP];
static unsigned s_cdc_head, s_cdc_len;
static int s_dtr, s_console, s_cdc_flush, s_cdc_rate = 256;
static unsigned s_cdc_partial;   /* 遥测写入不完整的次数 */
static tusb_cdcacm_callback_t s_cb_state, s_cb_coding;

static int cdc_put(uint8_t c)
{
    if (s_cdc_len == CDC_CAP) {
        if (s_dtr) return 0;
        s_cdc_head = (s_cdc_head + 1) % CDC_CAP; s_cdc_len--;
    }
    s_cdc[(s_cdc_head + s_cdc_len++) % CDC_CAP] = c;
    return 1;
}
size_t tinyusb_cdcacm_write_queue(int itf, const uint8_t *b, size_t n)
{
    (void)itf;
    size_t room = CDC_CAP - s_cdc_len, w = n < room ? n : room;
    for (size_t i = 0; i < w; i++) cdc_put(b[i]);
    if (w != n) s_cdc_partial++;
    return w;
}
uint32_t tud_cdc_n_write_available(uint8_t itf) { (void)itf; return CDC_CAP - s_cdc_len; }
esp_err_t tinyusb_cdcacm_write_flush(int itf, uint32_t t) { (void)itf; (void)t; s_cdc_flush = 1; return ESP_OK; }
esp_err_t tusb_cdc_acm_init(const tinyusb_config_cdcacm_t *c) { s_cb_state = c->callback_line_state_changed; s_cb_coding = c->callback_line_coding_changed; return ESP_OK; }
esp_err_t esp_tusb_init_console(int itf) { (void)itf; s_console = 1; return ESP_OK; }

static void hex_out(const char *pre, const uint8_t *p, unsigned n)
{
    fputs(pre, stdout);
    for (unsigned i = 0; i < n; i++) printf("%02x", p[i]);
    putchar('\n');
}
static void cdc_drain(void)
{
    if (!s_dtr || !s_cdc_flush || !s_cdc_len) { if (!s_cdc_len) s_cdc_flush = 0; return; }
    uint8_t b[1024];
    unsigned n = s_cdc_len < (unsigned)s_cdc_rate ? s_cdc_len : (unsigned)s_cdc_rate;
    for (unsigned i = 0; i < n; i++) b[i] = s_cdc[(s_cdc_head + i) % CDC_CAP];
    s_cdc_head = (s_cdc_head + n) % CDC_CAP; s_cdc_len -= n;
    hex_out("C ", b, n);
}

void sim_log(char level, const char *tag, const char *fmt, ...)
{
    char m[300], l[340];
    va_list a; va_start(a, fmt); vsnprintf(m, sizeof m, fmt, a); va_end(a);
    int n = snprintf(l, sizeof l, "%c (%llu) %s: %s", level, (unsigned long long)s_ms, tag, m);
    printf("L %s\n", l);
    if (!s_console) return;                 /* CONFIG_ESP_CONSOLE_NONE：控制台注册前的日志没有去处 */
    for (int i = 0; i < n; i++) if (!cdc_put((uint8_t)l[i])) return;
    if (cdc_put('\r')) cdc_put('\n');
    s_cdc_flush = 1;
}

/* ---------- USB 设备 ---------- */
static int s_mounted, s_suspended, s_hid_busy;
static const tinyusb_config_t *s_usb;
static tinyusb_config_t s_usb_cfg;
esp_err_t tinyusb_driver_install(const tinyusb_config_t *c) { s_usb_cfg = *c; s_usb = &s_usb_cfg; return ESP_OK; }
bool tud_mounted(void) { return s_mounted; }
bool tud_suspended(void) { return s_suspended; }
bool tud_hid_ready(void) { return s_mounted && !s_suspended && !s_hid_busy; }
static void in_report(uint8_t id, const uint8_t *p, unsigned n)
{
    char pre[40]; snprintf(pre, sizeof pre, "I %llu %u ", (unsigned long long)s_ms, id);
    hex_out(pre, p, n);
    s_hid_busy = 1;                         /* 中断端点 bInterval=1：每 ms 一个报告 */
}
bool tud_hid_report(uint8_t id, const void *p, uint16_t n) { if (!tud_hid_ready()) return false; in_report(id, p, n); return true; }
bool tud_hid_mouse_report(uint8_t id, uint8_t b, int8_t x, int8_t y, int8_t v, int8_t h)
{
    if (!tud_hid_ready()) return false;
    uint8_t r[5] = {b, (uint8_t)x, (uint8_t)y, (uint8_t)v, (uint8_t)h};
    in_report(id, r, 5);
    return true;
}
esp_err_t esp_read_mac(uint8_t *m, int t) { (void)t; memcpy(m, "\x24\x0a\xc4\x00\xe2\x24", 6); return ESP_OK; }
static uint32_t s_opt1;
static int s_in_sched;
void sim_reg_write(int r, uint32_t v) { if (r == RTC_CNTL_OPTION1_REG) s_opt1 = v; }
void esp_restart(void)
{
    printf("X restart download=%d\n", s_opt1 == RTC_CNTL_FORCE_DOWNLOAD_BOOT);
    s_halted = 1; s_mounted = 0;
    if (s_in_sched) return;                 /* 从 TinyUSB 回调（调度线程）进来：标记后返回即可 */
    for (;;) { task_t *me = s_cur; me->waiting = 0; me->wake = ~0ull; to_sched(me); }
}

/* ---------- 下层外设 ---------- */
static uint8_t s_keys;
static float s_gyro[3], s_acc[3] = {0, 0, 1}, s_bias[3] = {0.4f, -0.3f, 0.2f}, s_noise = 0.05f;
static int s_imu_run, s_imu_initing, s_imu_fail_read, s_imu_fail_init, s_imu_init_ms = 900, s_odr = 200;
static unsigned s_race_reads, s_reads, s_failed_reads;
static task_t *s_imu_task;
static uint64_t s_last_read_ms;
static float s_lat_g[3], s_lat_a[3];

/* 音频服务替身：记录隐私闸门的开合时刻，I2S 和 UAC 不在模拟范围内 */
static int s_mic_power, s_mic_gate;
static unsigned s_gate_opens;
static unsigned long long s_gate_closed_ms;
esp_err_t audio_svc_init(void) { return ESP_OK; }
void audio_svc_set_mic(bool power, bool permit)
{
    int gate = power && permit;
    if (gate && !s_mic_gate) s_gate_opens++;
    if (!gate && s_mic_gate) s_gate_closed_ms = s_ms;
    s_mic_power = power; s_mic_gate = gate;
}
bool audio_svc_take_abort(bool *failed) { *failed = false; return false; }
uint8_t audio_svc_config(uint8_t op, uint32_t hz, uint32_t ms, uint32_t atten, uint8_t st[16])
{ (void)op; (void)hz; (void)ms; (void)atten; memset(st, 0, 16); return 0; }

esp_err_t bsp_early_init(void) { return ESP_OK; }
uint8_t bsp_keys_raw(void) { return s_keys; }
esp_err_t bsp_i2c_init(void) { ESP_LOGI("bsp_i2c", "I2C SDA=8 SCL=9 100000 Hz"); return ESP_OK; }
bool bsp_i2c_probe(uint8_t a) { (void)a; return true; }
/* 与 bringup.c 的 app_report_identity 同样的四行，长度决定 512 B FIFO 里还留得住多少 */
void app_report_identity(void)
{
    ESP_LOGI("e24-bringup", "板型 AIKEY-E24 | 固件 aikey_e24 e833831 | IDF v5.2.3");
    ESP_LOGI("e24-bringup", "芯片 ESP32-S3 rev v0.2，2 核 | 运行分区 ota_0 @0x20000");
    ESP_LOGI("e24-bringup", "复位原因：上电");
    ESP_LOGI("e24-bringup", "Flash 8192 KB，PSRAM 8192 KB -> PASS");
}

esp_err_t imu_init(uint16_t odr, TaskHandle_t t)
{
    s_imu_initing = 1;
    vTaskDelay(s_imu_init_ms);              /* bmi270_init：100 kHz 下传 8 KB 配置约 0.8 s */
    s_imu_initing = 0;
    if (s_imu_fail_init) return ESP_FAIL;
    s_imu_task = t; s_odr = odr; s_imu_run = 1; s_last_read_ms = s_ms;
    ESP_LOGI("imu", "BMI270 就绪 chip_id=0x24 ODR≈%u Hz ±4g ±2000dps", (unsigned)odr);
    return ESP_OK;
}
esp_err_t imu_read(imu_sample_t *o)
{
    s_reads++;
    if (s_imu_initing) s_race_reads++;
    if (s_imu_fail_read || s_imu_fail_init || !s_imu_run) {
        if (!s_imu_initing) s_failed_reads++;
        if (s_imu_fail_read || s_imu_fail_init) return ESP_FAIL;
        memset(o, 0, sizeof *o); return ESP_OK;
    }
    memcpy(o->gyro_dps, s_lat_g, sizeof s_lat_g); memcpy(o->accel_g, s_lat_a, sizeof s_lat_a);
    o->dt = (float)(s_ms - s_last_read_ms) * 0.001f;
    o->sensor_time = (uint32_t)s_ms;
    s_last_read_ms = s_ms;
    return ESP_OK;
}
static void imu_sample(void)
{
    for (int i = 0; i < 3; i++) { s_lat_g[i] = s_gyro[i] + s_bias[i] + s_noise * gauss(); s_lat_a[i] = s_acc[i] + 0.002f * gauss(); }
    if (s_imu_task) { task_t *t = s_imu_task; t->notified = 1; }
}

static uint8_t s_nvs[16]; static int s_nvs_len, s_nvs_fail;
esp_err_t nvs_flash_init(void) { return ESP_OK; }
esp_err_t nvs_open(const char *n, int m, nvs_handle_t *h) { (void)n; (void)m; *h = 1; return ESP_OK; }
esp_err_t nvs_get_blob(nvs_handle_t h, const char *k, void *o, size_t *n) { (void)h; (void)k; if (!s_nvs_len) return ESP_FAIL; memcpy(o, s_nvs, 16); *n = 16; return ESP_OK; }
esp_err_t nvs_set_blob(nvs_handle_t h, const char *k, const void *i, size_t n) { (void)h; (void)k; if (s_nvs_fail) return ESP_FAIL; memcpy(s_nvs, i, n); s_nvs_len = (int)n; return ESP_OK; }
esp_err_t nvs_commit(nvs_handle_t h) { (void)h; return ESP_OK; }
void nvs_close(nvs_handle_t h) { (void)h; }

/* ---------- 调度 ---------- */
#define OUTQ 64
static struct { uint8_t b[33]; unsigned n; } s_out[OUTQ];
static unsigned s_out_n;

static void tick(void)
{
    s_ms++;
    s_hid_busy = 0;
    if (s_halted) return;
    /* 主机 OUT 报告：走真实 tud_hid_set_report_cb，字节 0 是报告号（hid_device.c 的 id=0 路径） */
    for (unsigned i = 0; i < s_out_n; i++) if (s_mounted && !s_suspended) tud_hid_set_report_cb(0, 0, HID_REPORT_TYPE_OUTPUT, s_out[i].b, (uint16_t)s_out[i].n);
    s_out_n = 0;
    if (s_imu_run && s_ms % (1000u / (unsigned)s_odr) == 0) imu_sample();
    for (int pass = 0; pass < 2; pass++)
        for (int prio = 20; prio >= 0; prio--)
            for (int i = 0; i < s_ntasks; i++) {
                task_t *t = &s_tasks[i];
                if (!t->alive || t->prio != prio) continue;
                if (s_halted) return;
                if (t->waiting ? (t->notified || t->wake <= s_ms) : t->wake <= s_ms) run(t);
            }
    cdc_drain();
}

static void main_task(void *a) { (void)a; app_link(); }
static int hexval(char c) { return c <= '9' ? c - '0' : (c | 32) - 'a' + 10; }

int main(void)
{
    static char line[2048];
    setvbuf(stdout, NULL, _IOFBF, 1 << 16);
    pthread_mutex_lock(&s_mu);
    spawn(main_task, NULL, 1);
    while (fgets(line, sizeof line, stdin)) {
        char c = line[0];
        if (c == 'x') break;
        if (c == 't') { int n = atoi(line + 2); while (n-- > 0) tick(); puts("K"); fflush(stdout); }
        else if (c == 'o') {
            unsigned id; char hex[200];
            if (sscanf(line + 2, "%u %199s", &id, hex) == 2 && s_out_n < OUTQ) {
                unsigned n = (unsigned)strlen(hex) / 2, o = s_out_n++;
                s_out[o].b[0] = (uint8_t)id;
                for (unsigned i = 0; i < n && i < 32; i++) s_out[o].b[i + 1] = (uint8_t)(hexval(hex[2 * i]) * 16 + hexval(hex[2 * i + 1]));
                s_out[o].n = n + 1;
            }
        }
        else if (c == 'k') s_keys = (uint8_t)atoi(line + 2);
        else if (c == 'g') sscanf(line + 2, "%f %f %f %f %f %f", &s_gyro[0], &s_gyro[1], &s_gyro[2], &s_acc[0], &s_acc[1], &s_acc[2]);
        else if (c == 'm') s_mounted = atoi(line + 2);
        else if (c == 's') s_suspended = atoi(line + 2);
        else if (c == 'd') {
            int v = atoi(line + 2);
            if (v != s_dtr) { s_dtr = v; if (v) s_cdc_flush = 1; cdcacm_event_t e = {0}; e.line_state_changed_data.dtr = v; if (s_cb_state) s_cb_state(0, &e); }
        }
        else if (c == 'b') { cdc_line_coding_t lc = {(uint32_t)atoi(line + 2)}; cdcacm_event_t e = {0}; e.line_coding_changed_data.p_line_coding = &lc; if (s_cb_coding) { s_in_sched = 1; s_cb_coding(0, &e); s_in_sched = 0; } }
        else if (c == 'f') {
            char k[32]; int v;
            if (sscanf(line + 2, "%31s %d", k, &v) == 2) {
                if (!strcmp(k, "imu_fail_read")) s_imu_fail_read = v;
                else if (!strcmp(k, "imu_fail_init")) s_imu_fail_init = v;
                else if (!strcmp(k, "nvs_fail")) s_nvs_fail = v;
                else if (!strcmp(k, "cdc_rate")) s_cdc_rate = v;
                else if (!strcmp(k, "noise_mdps")) s_noise = (float)v / 1000.0f;
                else if (!strcmp(k, "bias_z_mdps")) s_bias[2] = (float)v / 1000.0f;
                else if (!strcmp(k, "seed")) s_rng = (uint32_t)v | 1u;
            }
        }
        else if (c == 'r') {
            char j[600]; sim_state_json(j, sizeof j);
            printf("R {\"dev\":%s,\"sim\":{\"ms\":%llu,\"race_reads\":%u,\"reads\":%u,\"failed_reads\":%u,\"cdc_partial\":%u,\"cdc_len\":%u,\"mic_power\":%d,\"mic_gate\":%d,\"gate_opens\":%u,\"gate_closed_ms\":%llu}}\n", j, (unsigned long long)s_ms, s_race_reads, s_reads, s_failed_reads, s_cdc_partial, s_cdc_len, s_mic_power, s_mic_gate, s_gate_opens, s_gate_closed_ms);
            puts("K"); fflush(stdout);
        }
        else if (c == 'p') {   /* 描述符：usb_link.c 里的真实字节 */
            const uint8_t *rd = tud_hid_descriptor_report_cb(0);
            unsigned cl = s_usb ? (unsigned)(s_usb->configuration_descriptor[2] | s_usb->configuration_descriptor[3] << 8) : 0;
            if (s_usb) hex_out("P cfg ", s_usb->configuration_descriptor, cl);
            unsigned rl = 0; if (s_usb) { const uint8_t *q = s_usb->configuration_descriptor; rl = (unsigned)(q[9 + 9 + 7] | q[9 + 9 + 8] << 8); }
            hex_out("P rep ", rd, rl);
            if (s_usb) hex_out("P dev ", (const uint8_t *)s_usb->device_descriptor, 18);
            puts("K"); fflush(stdout);
        }
    }
    return 0;
}

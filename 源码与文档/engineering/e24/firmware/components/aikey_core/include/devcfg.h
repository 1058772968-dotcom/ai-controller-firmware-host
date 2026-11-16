#ifndef AIKEY_DEVCFG_H
#define AIKEY_DEVCFG_H
/* USB 报告 3（配置通道）上的指向/调试命令。与 REV A 的 Wi-Fi/BLE 配置事务（op 1..6）共用帧格式，
 * 操作码从 0x10 起，互不冲突；不占用 v1 控制协议（报告 2）的保留字节。
 *
 * 请求帧 32 字节：
 *   [0]=1 版本 [1]=op [2..3]=0 [4..7]=session（与状态报告一致，小端） [8..11]=事务号（原样回显）
 *   [12..27]=16 字节负载 [28..29]=0 [30..31]=CRC16（同协议 v1，覆盖 0..29）
 * 回复帧 32 字节：
 *   [0]=1 [1]=op|0x80 [2]=结果码 [3]=指向状态（0 未校准/1 校准中/2 可用） [4..7]=session [8..11]=事务号
 *   [12..27]=当前生效的指向参数（16 字节编码，见 pointer.h） [28]=bit0 遥测开启 [29]=0 [30..31]=CRC16
 *   音频操作（0x17..0x19）的 [12..27] 改为 16 字节音频状态（下标从 12 算起）：
 *     [0] bit0 时钟运行 bit1 闸门打开 bit2 自检中 bit3 自检结果有效 bit4 播放中 bit5 功放开 bit6 主机在收流 bit7 故障
 *     [1] 左槽非零占比 % [2] 右槽非零占比 % [3]=0 [4..5] RMS 0.01 dBFS（int16） [6..7] 峰值 0.01 dBFS（int16）
 *     [8..11] 自检帧数 [12..13] I2S 读错误数 [14..15] UAC 写溢出数 */
#include <stdbool.h>
#include <stdint.h>
#include "pointer.h"

enum {
    AK_DCFG_PTR_GET = 0x10,      /* 读参数 */
    AK_DCFG_PTR_SET = 0x11,      /* 写参数，立即生效，不落盘 */
    AK_DCFG_PTR_SAVE = 0x12,     /* 把当前参数写入 NVS */
    AK_DCFG_GYRO_CAL = 0x13,     /* 开始静置校准（约 1.2 s） */
    AK_DCFG_TELEMETRY = 0x14,    /* 负载[0]=1 开启 CDC 遥测，0 关闭 */
    AK_DCFG_DOWNLOAD = 0x15,     /* 负载[0..3]="DFU!"：重启进 ROM 下载模式 */
    AK_DCFG_PTR_DEFAULTS = 0x16, /* 恢复默认参数（不落盘） */
    AK_DCFG_AUDIO_STATUS = 0x17, /* 读音频状态 */
    AK_DCFG_MIC_TEST = 0x18,     /* 开始约 1 s 的麦克风电平自检：只回统计值，不传波形 */
    AK_DCFG_SPK_TONE = 0x19,     /* 负载[0..3]="SPK!" [4..5]=Hz [6..7]=ms [8]=衰减 dB：播一次提示音 */
};
enum { AK_DCFG_OK = 0, AK_DCFG_FRAME, AK_DCFG_SESSION, AK_DCFG_VALUE, AK_DCFG_STORAGE, AK_DCFG_BUSY, AK_DCFG_UNAVAILABLE };

typedef struct {
    void *ctx;
    bool (*save)(void *ctx, const uint8_t cfg[AK_POINTER_WIRE_SIZE]);
    void (*calibrate)(void *ctx);
    void (*telemetry)(void *ctx, bool on);
    void (*download)(void *ctx);   /* 回复发出后再执行 */
    /* 参数已校验。写 16 字节状态到 status，返回 AK_DCFG_* 结果码；为空时音频操作回 UNAVAILABLE */
    uint8_t (*audio)(void *ctx, uint8_t op, uint32_t hz, uint32_t ms, uint32_t atten_db, uint8_t status[16]);
} ak_devcfg_io;

static inline bool ak_devcfg_owns(const uint8_t *in, unsigned len)
{
    return in && len == 32 && in[1] >= AK_DCFG_PTR_GET && in[1] <= AK_DCFG_SPK_TONE;
}

/* 处理一帧。*cfg 为当前生效参数；SET/DEFAULTS 成功时改写 *cfg 并把 *apply 置 true。
 * *download_after 置 true 表示回复发出后应调用 io.download。 */
void ak_devcfg_process(ak_pointer_cfg *cfg, uint8_t pointer_state, bool telemetry_on, uint32_t session,
                       const uint8_t *in, unsigned len, ak_devcfg_io io,
                       uint8_t out[32], bool *apply, bool *download_after);
#endif

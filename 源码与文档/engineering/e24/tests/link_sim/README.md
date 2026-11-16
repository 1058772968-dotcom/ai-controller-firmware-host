# 全链路模拟器

把真实固件 C 代码和真实上位机 JS 接到一起，用同一条 1 ms 虚拟时钟跑。结论和问题清单见[链路联调文档](../../../../docs/engineering/项目档案/20261106-链路联调预演/链路联调文档.md)。

```bash
node run.mjs
```

```bash
SIM_VERBOSE=1 node run.mjs L01 L02
```

结果写成 JSON：`node run.mjs --json 报告.json`。有检查失败时退出码为 1。

验证修改前先在副本上跑：`SIM_FIRMWARE=<副本>/firmware SIM_PROTOTYPE=<副本>/prototype node run.mjs`。

## 文件

| 文件 | 内容 |
|---|---|
| `sim_rt.c` | 设备端运行时：任务调度、TinyUSB/CDC 模型、IMU 读数、NVS，与 Node 的文本协议 |
| `glue_link.c` | 把未改动的 `link_app.c` 编进来，以便读它的静态变量 |
| `stubs/` | ESP-IDF、FreeRTOS、TinyUSB 头文件替身 |
| `harness.mjs` | 虚拟时钟、WebHID 与 Web Serial 替身、系统鼠标模型、手部动作 |
| `scenarios.mjs` | 场景。A 开头是主干，L 开头是问题，F 是随机压力 |

场景里写的是应该成立的行为。当前代码失败表示问题重现，修好后这份脚本就是回归门槛；全绿后再把它加进 `tools/run_host_tests.py`。

## 边界

模拟通过不等于实物通过。这里没有真实的双核并发、CPU 耗时、USB 电气、浏览器和 macOS 权限、手抖。替身的依据写在 `sim_rt.c` 和 `harness.mjs` 的注释里。

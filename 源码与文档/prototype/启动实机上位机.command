#!/bin/zsh
# 双击运行：打开 AI KEY 实机上位机（调参、轴向向导、遥测）。服务逻辑和灵动岛 POC 共用，同一端口下手柄授权也共用。
cd "${0:A:h}" || exit 1
ISLAND_POC_PAGE="AI键盘-实机上位机.html" exec ./启动灵动岛POC.command

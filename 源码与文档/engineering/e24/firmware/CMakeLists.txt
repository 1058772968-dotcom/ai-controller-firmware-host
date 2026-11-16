cmake_minimum_required(VERSION 3.16)
# TinyUSB 配置要加 UAC：托管组件不改，用项目级头文件扩展
include_directories("${CMAKE_CURRENT_LIST_DIR}/main")
add_compile_definitions(CFG_TUSB_CONFIG_FILE="aikey_tusb_config.h")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(aikey_e24)

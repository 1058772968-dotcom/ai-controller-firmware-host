# 纯逻辑模块：不依赖 IDF，可在电脑端单元测试（tests/host）
idf_component_register(SRCS "controller.c" "protocol.c" "pointer.c" "devcfg.c" "audio_dsp.c"
                       INCLUDE_DIRS "include")

idf_component_register(SRCS "app_main.c" "usb_transport.c" "ble_transport.c" "imu.c" "audio_capture.c" "peripheral_bus.c" "settings_store.c" "wifi_audio.c"
                       "../core/controller.c" "../core/protocol.c" "../core/motion.c" "../core/audio_filter.c" "../core/peripherals.c" "../core/link_policy.c" "../core/settings.c" "../core/audio_wire.c" "../vendor/st/lsm6dsv16x_reg.c"
                       INCLUDE_DIRS "." "../core" "../vendor/st"
                       REQUIRES driver esp_timer esp_hw_support nvs_flash esp_tinyusb bt esp_wifi esp_event esp_netif esp-tls)

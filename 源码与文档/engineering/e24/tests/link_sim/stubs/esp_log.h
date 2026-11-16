#pragma once
void sim_log(char level, const char *tag, const char *fmt, ...) __attribute__((format(printf, 3, 4)));
#define ESP_LOGE(t, ...) sim_log('E', t, __VA_ARGS__)
#define ESP_LOGW(t, ...) sim_log('W', t, __VA_ARGS__)
#define ESP_LOGI(t, ...) sim_log('I', t, __VA_ARGS__)
#define ESP_LOGD(t, ...) do {} while (0)

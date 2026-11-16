# Bosch BMI270 SensorAPI（BSD-3-Clause，见 LICENSE）。来源与补丁见 SOURCE.md。
idf_component_register(SRCS "bmi2.c" "bmi270.c"
                       INCLUDE_DIRS "include"
                       REQUIRES freertos log esp_common)
target_compile_definitions(${COMPONENT_LIB} PUBLIC CONFIG_SENSOR_BMI270=1)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-unused-variable -Wno-unused-function)

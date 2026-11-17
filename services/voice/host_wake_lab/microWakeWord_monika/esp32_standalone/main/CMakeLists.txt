idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "."
    REQUIRES esp-tflite-micro esp-micro-speech-features esp_timer heap
    EMBED_FILES "monika_int8.tflite"
)

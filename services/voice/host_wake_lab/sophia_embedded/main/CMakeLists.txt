idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "." "../integration"
    REQUIRES esp-sr esp_timer heap
    EMBED_FILES "sophia_srmodels.bin"
)
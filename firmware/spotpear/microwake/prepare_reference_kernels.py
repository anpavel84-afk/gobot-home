"""One-variable diagnostic: same model/fixture, ESP-NN kernels disabled only.

No dependency downgrade or vendor source modification. No provider admission.
"""
import argparse
from pathlib import Path
from prepare_product import change


def prepare(root):
    top=root/'CMakeLists.txt';main=root/'main'
    if '0.4.10-dev-native-parity-1' not in top.read_text():raise ValueError('Expected isolated native-parity copy')
    cfg=(main/'gobot_mww_config.h').read_text()
    if '#define GOBOT_WAKE_ROUTE 0' not in cfg or '#define GOBOT_WAKE_OWNER_TEST 0' not in cfg:
        raise ValueError('Diagnostic must stay local-only')
    cmake=root/'managed_components/espressif__esp-tflite-micro/CMakeLists.txt'
    if cmake.read_text().count('target_compile_options(${COMPONENT_LIB} PRIVATE -DESP_NN)')!=1:
        raise ValueError('Re-review changed pinned component options')
    # Apply after project() has constructed the component targets. The managed
    # component and lockfiles remain byte-for-byte unchanged.
    with top.open('a',encoding='utf-8') as f:f.write('''
# GoBot bounded kernel parity experiment; no SDK/esp-sr change.
idf_component_get_property(gobot_mww_lib espressif__esp-tflite-micro COMPONENT_LIB)
get_target_property(gobot_mww_options ${gobot_mww_lib} COMPILE_OPTIONS)
list(REMOVE_ITEM gobot_mww_options "-DESP_NN")
set_property(TARGET ${gobot_mww_lib} PROPERTY COMPILE_OPTIONS ${gobot_mww_options})
target_compile_definitions(${gobot_mww_lib} PRIVATE ESP_NN=0)
''')
    for p in (top,main/'gobot_build_info.h'):change(p,'0.4.10-dev-native-parity-1','0.4.11-dev-ref-kernels-1')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('isolated_copy',type=Path);prepare(p.parse_args().isolated_copy)

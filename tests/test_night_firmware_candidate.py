import importlib.util
from pathlib import Path
import pytest

def test_candidate_preparation_only_changes_capabilities(tmp_path):
    script=Path(__file__).parents[1]/'firmware/spotpear/vnext/prepare_candidate.py'
    spec=importlib.util.spec_from_file_location('prepare_night',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    (tmp_path/'main/protocols').mkdir(parents=True)
    cmake=tmp_path/'CMakeLists.txt';cmake.write_text('set(PROJECT_VER "0.4.3-dev-media-ready")')
    p=tmp_path/'main/protocols/protocol.h';p.write_text('#ifndef PROTOCOL_H\n#define PROTOCOL_H\n    void SendSessionReady(){old();}\n#endif\n')
    result=module.prepare(tmp_path)
    assert p.read_text().startswith('#include "../gobot_web_next_contract.h"\n#ifndef')
    assert 'gobot::kWebNextCapabilities' in p.read_text()
    assert result['playback_ack_precision']=='activity_only' and result['installed'] is False
    assert not result['audio_path_changed'] and not result['kws_changed']
    with pytest.raises(ValueError):module.prepare(tmp_path)

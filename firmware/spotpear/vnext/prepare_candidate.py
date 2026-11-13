"""Patch a COPY of installed 0.4.3 sources. No flash/OTA/network operations."""
import hashlib,json,sys
from pathlib import Path
def prepare(root):
    root=Path(root).resolve()
    cmake=root/'CMakeLists.txt';protocol=root/'main/protocols/protocol.h'
    original=protocol.read_text();build=cmake.read_text()
    if '0.4.3-dev-media-ready' not in build:raise ValueError('verified_0_4_3_source_required')
    lines=[line for line in original.splitlines() if 'void SendSessionReady(){' in line]
    if len(lines)!=1:raise ValueError('session_ready_patch_anchor_required')
    header=r'''#pragma once
// Versioned capability negotiation only. No invented playback cursor.
namespace gobot {
inline constexpr const char* kWebNextCapabilities =
    ",\"gobot_contract\":3,\"scene_contract\":2,\"playback_ack_precision\":\"activity_only\",\"segment_position\":false";
}
'''
    line=r'''    void SendSessionReady(){SendText(std::string("{\"type\":\"gobot_session_ready\",\"session_id\":\"")+session_id_+"\",\"continuous\":true,\"capture_deferred\":true"+gobot::kWebNextCapabilities+"}");}'''
    updated='#include "../gobot_web_next_contract.h"\n'+original.replace(lines[0],line)
    protocol.write_text(updated)
    (root/'main/gobot_web_next_contract.h').write_text(header)
    cmake.write_text(build.replace('0.4.3-dev-media-ready','0.4.4-night-contract',1))
    manifest={'candidate_version':'0.4.4-night-contract','base_version':'0.4.3-dev-media-ready',
        'upstream':'a73e9a7e266e3196d1368ba46c30bee0d81f0a64','protocol_header_before_sha256':hashlib.sha256(original.encode()).hexdigest(),
        'gobot_contract':3,'scene_contract':2,'playback_ack_precision':'activity_only','precise_segment_position':False,
        'audio_path_changed':False,'kws_changed':False,'installed':False,'flash_authorized':False}
    (root/'night-contract-source.json').write_text(json.dumps(manifest,indent=2))
    return manifest
if __name__=='__main__':print(json.dumps(prepare(sys.argv[1])))

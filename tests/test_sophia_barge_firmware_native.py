"""Build the candidate's real heap-backed AEC framing and interrupt state helper.

The DSP backend is stubbed. These are memory/clock/protocol tests, not evidence
that actual speaker echo or human barge-in succeeds acoustically.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'firmware/spotpear/host'

AEC_STUB = '''#pragma once
#include <cstdint>
enum aec_mode_t {AEC_MODE_FD_LOW_COST=5};
enum aec_nlp_level_t {AEC_NLP_LEVEL_AGGR=2};
struct aec_config_t {int mic_num,ref_num,out_num,filter_length,sample_rate;uint32_t caps;aec_mode_t mode;aec_nlp_level_t nlp_level;};
struct aec_handle_t {};
aec_handle_t* aec_create_from_config(aec_config_t*);
int aec_get_chunksize(const aec_handle_t*);
void aec_process(const aec_handle_t*,int16_t*,int16_t*,int16_t*);
void aec_destroy(aec_handle_t*);
'''
HEAP_STUB = '''#pragma once
#include <cstddef>
constexpr unsigned MALLOC_CAP_INTERNAL=1, MALLOC_CAP_SPIRAM=2, MALLOC_CAP_8BIT=4;
void* heap_caps_aligned_alloc(size_t,size_t,unsigned);
void heap_caps_free(void*);
'''


class SophiaBargeFirmwareNativeTests(unittest.TestCase):
    def test_exact_parent_and_protected_idle_audio_assets(self):
        manifest = json.loads((HOST / 'sophia_barge_v418_manifest.json').read_text())
        parent_path = HOST / 'sophia_admission_v417_manifest.json'
        parent = json.loads(parent_path.read_text())
        self.assertEqual(hashlib.sha256(parent_path.read_bytes()).hexdigest(), manifest['parent_manifest_sha256'])
        self.assertEqual(manifest['baseline_version'], parent['candidate_version'])
        self.assertEqual(manifest['baseline_app_sha256'], parent['candidate_app_sha256'])
        self.assertEqual(manifest['baseline_app_size'], parent['candidate_app_size'])
        self.assertEqual(manifest['baseline_sources'], {**parent['baseline_sources'], **parent['candidate_sources']})
        self.assertEqual(manifest['protected_binary_hashes'], parent['protected_binary_hashes'])
        self.assertEqual(manifest['sdkconfig_sha256'], parent['sdkconfig_sha256'])
        self.assertEqual(manifest['model'], 'wn10_sophia')
        self.assertEqual(manifest['detector_mode'], 'DET_MODE_95')
        for name in ('main/audio/codecs/es8311_audio_codec.cc', 'main/audio/audio_codec.cc',
                     'main/audio/engines/afe_audio_engine.cc', 'main/sophia_pcm_tap.hpp',
                     'main/sophia_host_capture.h', 'main/wake_question_buffer.h',
                     'main/host_output_receipts.h', 'main/protocols/websocket_protocol.cc',
                     'dependencies.lock'):
            self.assertIn(name, manifest['protected_source_paths'])
            self.assertNotIn(name, manifest['candidate_sources'])
        patch = HOST / 'sophia_barge_v418.patch'
        self.assertEqual(hashlib.sha256(patch.read_bytes()).hexdigest(), manifest['patch_sha256'])

    def test_actual_cpp_clock_gaps_allocation_failure_completion_and_watchdog(self):
        if not shutil.which('g++'):
            self.skipTest('native C++ compiler unavailable')
        manifest = json.loads((HOST / 'sophia_barge_v418_manifest.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / 'main').mkdir()
            subprocess.run(['git', 'apply', '--include=main/host_barge_wake.h',
                            str(HOST / 'sophia_barge_v418.patch')], cwd=workspace, check=True, capture_output=True)
            header = workspace / 'main/host_barge_wake.h'
            self.assertEqual(hashlib.sha256(header.read_bytes()).hexdigest(), manifest['candidate_sources']['main/host_barge_wake.h'])
            (workspace / 'main/esp_aec.h').write_text(AEC_STUB)
            (workspace / 'main/esp_heap_caps.h').write_text(HEAP_STUB)
            executable = workspace / 'test'
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-I', str(workspace / 'main'), str(HOST / 'test_sophia_barge_v418.cc'),
                            '-o', str(executable)], check=True, capture_output=True)
            # This managed runner uses ptrace; LSan cannot attach. The fixture
            # separately asserts all AEC handles and aligned allocations are freed.
            result = subprocess.run([str(executable)], check=True, capture_output=True, text=True,
                                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            self.assertIn('PASS original capture clock / partial AEC frames / allocation failure / correlated interrupt latch / watchdog', result.stdout)


if __name__ == '__main__':
    unittest.main()

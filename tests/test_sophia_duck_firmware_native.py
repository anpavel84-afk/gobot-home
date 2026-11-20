"""Exact production wake/duck handlers and SR framing; DSP/codec edges are stubs.

This proves control ordering, current-volume restoration and the selected SR
contract. It does not prove human wake recognition, echo rejection or loudness.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from test_sophia_barge_firmware_native import AEC_STUB, HEAP_STUB
from test_sophia_touch_firmware_native import block

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT/'firmware/spotpear/host'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(workspace, name, paths=None):
    args = ['git', 'apply']
    if paths:
        args.extend('--include=main/'+p for p in paths)
    subprocess.run([*args, str(name)], cwd=workspace, check=True, capture_output=True)


class SophiaDuckFirmwareNativeTests(unittest.TestCase):
    def test_exact_installed_parent_and_unchanged_model_sdk_raw_path(self):
        manifest = json.loads((HOST/'sophia_duck_v420_manifest.json').read_text())
        parent_path = HOST/'sophia_touch_v419_manifest.json'
        parent = json.loads(parent_path.read_text())
        self.assertEqual(digest(parent_path), manifest['parent_manifest_sha256'])
        self.assertEqual(manifest['baseline_version'], parent['candidate_version'])
        self.assertEqual(manifest['baseline_app_sha256'], parent['candidate_app_sha256'])
        self.assertEqual(manifest['baseline_app_size'], parent['candidate_app_size'])
        self.assertEqual(manifest['baseline_sources'], {**parent['baseline_sources'], **parent['candidate_sources']})
        self.assertEqual(manifest['protected_binary_hashes'], parent['protected_binary_hashes'])
        self.assertEqual(manifest['sdkconfig_sha256'], parent['sdkconfig_sha256'])
        self.assertEqual(digest(HOST/'sophia_duck_v420.patch'), manifest['patch_sha256'])
        self.assertEqual(manifest['active_output_kws_only_aec']['mode'], 'AEC_MODE_SR_LOW_COST')
        self.assertEqual(manifest['model'], parent['model'])
        self.assertEqual(manifest['detector_mode'], parent['detector_mode'])
        for name in ('main/embedded_sophia_engine.hpp', 'main/sophia_pcm_tap.hpp',
                     'main/sophia_host_capture.h', 'main/host_touch_controls.inc',
                     'main/host_touch_gesture.h', 'main/boards/spotpear/sp-esp32-s3-1.28-box/sp-esp32-s3-1.28-box.cc',
                     'main/audio/engines/afe_audio_engine.cc', 'dependencies.lock'):
            self.assertIn(name, manifest['protected_source_paths'])
            self.assertNotIn(name, manifest['candidate_sources'])

    def test_actual_cpp_wake_duck_and_current_volume_restore(self):
        self._run('test_sophia_duck_v420.cc', 'PASS actual wake duck/hardware attenuation/no NVS/current-volume restore/DMA barrier/touch/mute controls')

    def test_actual_sr_aec_frames_pcm_tap_clock_levels_and_allocation_failure(self):
        self._run('test_sophia_duck_aec_v420.cc', 'PASS SR AEC config / actual PCM tap continuity / signed magnitude telemetry / no raw fallback / allocation guards')

    def _run(self, harness, expected):
        if not shutil.which('g++'):
            self.skipTest('native C++ compiler unavailable')
        manifest = json.loads((HOST/'sophia_duck_v420_manifest.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            main = workspace/'main'; main.mkdir()
            shutil.copyfile(HOST/'host_rc1_app.inc', main/'host_rc1_app.inc')
            apply(workspace, ROOT/'tests/fixtures/sophia_v4_host_basis.patch')
            for name in ('sophia_unified_v4.patch', 'sophia_admission_v417.patch', 'sophia_barge_v418.patch'):
                apply(workspace, HOST/name, ('host_rc1_app.inc',))
            apply(workspace, HOST/'sophia_barge_v418.patch', ('host_barge_wake.h',))
            paths = ('host_rc1_app.inc', 'host_barge_wake.h', 'host_touch_gesture.h', 'host_touch_controls.inc')
            apply(workspace, HOST/'sophia_touch_v419.patch', paths)
            apply(workspace, ROOT/'tests/fixtures/sophia_v419_duck_basis.patch')
            paths = (*paths, 'audio/codecs/es8311_audio_codec.cc', 'audio/codecs/es8311_audio_codec.h', 'sophia_pcm_tap.hpp')
            for path in paths:
                self.assertEqual(digest(main/path), manifest['baseline_sources']['main/'+path])
            apply(workspace, HOST/'sophia_duck_v420.patch', paths)
            for path in paths:
                self.assertEqual(digest(main/path), manifest['candidate_sources'].get('main/'+path, manifest['baseline_sources']['main/'+path]))
            source = (main/'host_rc1_app.inc').read_text()
            for filename, anchor, body in (
                ('native_begin_interrupt.inc', 'bool Application::HostBeginInterrupt(', False),
                ('native_duck_release.inc', 'void Application::HostReleaseOutputDuck(', False),
                ('native_sophia_wake.inc', 'void Application::HostSophiaWake(', False),
                ('native_barge_stats.inc', 'std::string Application::HostBargeStats(', False),
                ('native_output_start.inc', 'else if(kind=="gobot_host_output_start")', True),
                ('native_ready_body.inc', 'if(kind=="gobot_host_ready")', True),
                ('native_interrupt_body.inc', 'if(kind=="gobot_host_interrupt_complete" && ws->HostV2())', True),
                ('native_mute_body.inc', 'if(kind=="gobot_host_mute" && ws->HostV2())', True),
                ('native_resume_block.inc', 'if(host_touch_resume_pending_ && ws->HostV2())', False),
            ):
                (main/filename).write_text(block(source, anchor, body=body)+'\n')
            source = (main/'audio/codecs/es8311_audio_codec.cc').read_text()
            for filename, anchor in (
                ('native_codec_volume.inc', 'void Es8311AudioCodec::SetOutputVolume('),
                ('native_codec_attenuation.inc', 'bool Es8311AudioCodec::SetTransientOutputAttenuation('),
            ):
                (main/filename).write_text(block(source, anchor)+'\n')
            source = (main/'audio/codecs/es8311_audio_codec.h').read_text()
            (main/'native_effective_volume.inc').write_text(block(source, 'int EffectiveOutputVolume(')+'\n')
            (main/'esp_aec.h').write_text(AEC_STUB.replace('AEC_MODE_FD_LOW_COST=5', 'AEC_MODE_SR_LOW_COST=0,AEC_MODE_FD_LOW_COST=5'))
            (main/'esp_heap_caps.h').write_text(HEAP_STUB)
            executable = workspace/'test'
            result = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(main),
                str(HOST/harness), '-o', str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)


if __name__ == '__main__':
    unittest.main()

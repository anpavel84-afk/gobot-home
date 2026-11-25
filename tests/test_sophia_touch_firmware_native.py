"""Compile exact patched gesture/control code; no firmware build or device access.

Reconstruct the historical public V4 control source with its pinned SHA, apply
the same successor patches, then compile actual production bodies. JSON/audio/
transport edges are stubs. This verifies state ordering, not physical acoustics.
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

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT/'firmware/spotpear/host'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block(source, anchor, *, body=False):
    if source.count(anchor) != 1:
        raise AssertionError('production block anchor must be unique: '+anchor)
    start = source.index(anchor)
    opening = source.index('{', start)
    depth = 1
    index = opening+1
    while depth:
        depth += (source[index] == '{')-(source[index] == '}')
        index += 1
    return source[opening+1:index-1] if body else source[start:index]


class SophiaTouchFirmwareNativeTests(unittest.TestCase):
    def test_manifest_preserves_wake_audio_and_exact_installed_predecessor(self):
        manifest = json.loads((HOST/'sophia_touch_v419_manifest.json').read_text())
        previous_path = HOST/'sophia_barge_v418_manifest.json'
        previous = json.loads(previous_path.read_text())
        self.assertEqual(digest(previous_path), manifest['parent_manifest_sha256'])
        self.assertEqual(manifest['baseline_version'], previous['candidate_version'])
        self.assertEqual(manifest['baseline_app_sha256'], previous['candidate_app_sha256'])
        self.assertEqual(manifest['baseline_app_size'], previous['candidate_app_size'])
        previous_sources = {**previous['baseline_sources'], **previous['candidate_sources']}
        self.assertEqual({path: manifest['baseline_sources'][path] for path in previous_sources}, previous_sources)
        self.assertEqual(set(manifest['baseline_sources'])-set(previous_sources),
            {'main/boards/spotpear/sp-esp32-s3-1.28-box/sp-esp32-s3-1.28-box.cc'})
        self.assertEqual(manifest['protected_binary_hashes'], previous['protected_binary_hashes'])
        self.assertEqual(manifest['sdkconfig_sha256'], previous['sdkconfig_sha256'])
        self.assertEqual(digest(HOST/'sophia_touch_v419.patch'), manifest['patch_sha256'])
        self.assertEqual(manifest['hold_threshold_ms'], 650)
        for path in ('main/embedded_sophia_engine.hpp', 'main/sophia_pcm_tap.hpp',
                     'main/audio/audio_service.cc', 'main/sophia_host_capture.h',
                     'main/protocols/websocket_protocol.cc', 'dependencies.lock'):
            self.assertIn(path, manifest['protected_source_paths'])
            self.assertNotIn(path, manifest['candidate_sources'])

    def test_actual_production_gestures_and_mute_controls(self):
        if not shutil.which('g++'):
            self.skipTest('native C++ compiler unavailable')
        manifest = json.loads((HOST/'sophia_touch_v419_manifest.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            main = workspace/'main'
            main.mkdir()
            shutil.copyfile(HOST/'host_rc1_app.inc', main/'host_rc1_app.inc')
            subprocess.run(['git', 'apply', str(ROOT/'tests/fixtures/sophia_v4_host_basis.patch')],
                           cwd=workspace, check=True, capture_output=True)
            original = json.loads((HOST/'sophia_unified_v4_manifest.json').read_text())
            self.assertEqual(digest(main/'host_rc1_app.inc'), original['baseline_sources']['main/host_rc1_app.inc'])
            for name in ('sophia_unified_v4.patch', 'sophia_admission_v417.patch', 'sophia_barge_v418.patch'):
                subprocess.run(['git', 'apply', '--include=main/host_rc1_app.inc', str(HOST/name)],
                               cwd=workspace, check=True, capture_output=True)
            self.assertEqual(digest(main/'host_rc1_app.inc'), manifest['baseline_sources']['main/host_rc1_app.inc'])
            subprocess.run(['git', 'apply', '--include=main/host_barge_wake.h',
                            str(HOST/'sophia_barge_v418.patch')], cwd=workspace, check=True, capture_output=True)
            paths = ('host_rc1_app.inc', 'host_barge_wake.h', 'host_touch_gesture.h', 'host_touch_controls.inc')
            subprocess.run(['git', 'apply', *['--include=main/'+path for path in paths],
                            str(HOST/'sophia_touch_v419.patch')], cwd=workspace, check=True, capture_output=True)
            for path in paths:
                self.assertEqual(digest(main/path), manifest['candidate_sources']['main/'+path])
            source = (main/'host_rc1_app.inc').read_text()
            for filename, anchor, body in (
                ('native_begin_interrupt.inc', 'bool Application::HostBeginInterrupt(', False),
                ('native_ready_body.inc', 'if(kind=="gobot_host_ready")', True),
                ('native_interrupt_body.inc', 'if(kind=="gobot_host_interrupt_complete" && ws->HostV2())', True),
                ('native_mute_body.inc', 'if(kind=="gobot_host_mute" && ws->HostV2())', True),
                ('native_resume_block.inc', 'if(host_touch_resume_pending_ && ws->HostV2())', False),
            ):
                (main/filename).write_text(block(source, anchor, body=body)+'\n')
            (main/'esp_aec.h').write_text(AEC_STUB)
            (main/'esp_heap_caps.h').write_text(HEAP_STUB)
            executable = workspace/'test'
            result = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(main),
                str(HOST/'test_sophia_touch_v419.cc'), '-o', str(executable)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS real touch 650ms/release/all-state mute/revision/late-ready/late-listen/reconnect controls', result.stdout)


if __name__ == '__main__':
    unittest.main()

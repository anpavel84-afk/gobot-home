"""Exact v420 -> v421 native timer methods, with inert JSON/LCD/socket edges.

These checks do not build an ESP image, flash a board or claim visible pixels.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from test_sophia_touch_firmware_native import block

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT/'firmware/spotpear/host'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(workspace, name, *paths):
    subprocess.run(['git', 'apply', *['--include=main/'+p for p in paths], str(name)],
                   cwd=workspace, check=True, capture_output=True)


class SophiaTimerFirmwareNativeTests(unittest.TestCase):
    def test_exact_parent_manifest_scope_and_unchanged_audio_wake_models(self):
        manifest = json.loads((HOST/'sophia_timer_v421_manifest.json').read_text())
        parent_path = HOST/'sophia_duck_v420_manifest.json'
        parent = json.loads(parent_path.read_text())
        self.assertEqual(digest(parent_path), manifest['parent_manifest_sha256'])
        self.assertEqual(manifest['baseline_version'], parent['candidate_version'])
        self.assertEqual(manifest['baseline_app_sha256'], parent['candidate_app_sha256'])
        self.assertEqual(manifest['baseline_app_size'], parent['candidate_app_size'])
        self.assertEqual(manifest['baseline_sources'], {**parent['baseline_sources'], **parent['candidate_sources']})
        self.assertEqual(manifest['protected_binary_hashes'], parent['protected_binary_hashes'])
        self.assertEqual(manifest['sdkconfig_sha256'], parent['sdkconfig_sha256'])
        self.assertEqual(digest(HOST/'sophia_timer_v421.patch'), manifest['patch_sha256'])
        self.assertEqual(digest(HOST/'host_timer_ui.h'), manifest['candidate_sources']['main/host_timer_ui.h'])
        self.assertEqual(set(manifest['candidate_sources']), {'CMakeLists.txt', 'main/application.cc',
            'main/application.h', 'main/gobot_build_info.h', 'main/host_rc1_app.inc', 'main/host_timer_ui.h',
            'main/protocols/websocket_protocol.cc', 'main/touch_screen.h'})
        self.assertEqual(set(manifest['protected_source_paths']),
                         set(manifest['baseline_sources'])-set(manifest['candidate_sources']))
        for name in ('main/embedded_sophia_engine.hpp', 'main/sophia_pcm_tap.hpp', 'main/sophia_host_capture.h',
                     'main/host_barge_wake.h', 'main/host_touch_controls.inc', 'main/host_output_receipts.h',
                     'main/audio/audio_service.cc', 'main/audio/codecs/es8311_audio_codec.cc', 'dependencies.lock'):
            self.assertIn(name, manifest['protected_source_paths'])
        self.assertIn(manifest['build_status'], {'source_only_not_built', 'passed'})
        self.assertEqual(manifest['physical_status_at_build'], 'not_flashed')

    def test_actual_control_and_rendered_ack_methods(self):
        if not shutil.which('g++'):
            self.skipTest('native C++ compiler unavailable')
        manifest = json.loads((HOST/'sophia_timer_v421_manifest.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            main = workspace/'main'; main.mkdir()
            shutil.copyfile(HOST/'host_rc1_app.inc', main/'host_rc1_app.inc')
            apply(workspace, ROOT/'tests/fixtures/sophia_v4_host_basis.patch')
            for name in ('sophia_unified_v4.patch', 'sophia_admission_v417.patch',
                         'sophia_barge_v418.patch', 'sophia_touch_v419.patch', 'sophia_duck_v420.patch'):
                apply(workspace, HOST/name, 'host_rc1_app.inc')
            self.assertEqual(digest(main/'host_rc1_app.inc'), manifest['baseline_sources']['main/host_rc1_app.inc'])
            apply(workspace, HOST/'sophia_admission_v417.patch', 'host_admission_ui.h')
            apply(workspace, HOST/'sophia_timer_v421.patch', 'host_rc1_app.inc', 'host_timer_ui.h')
            for name in ('host_rc1_app.inc', 'host_timer_ui.h'):
                self.assertEqual(digest(main/name), manifest['candidate_sources']['main/'+name])
            source = (main/'host_rc1_app.inc').read_text()
            for filename, anchor in (('native_timer_control.inc', 'void Application::HostTimerControl('),
                                     ('native_timer_rendered.inc', 'void Application::HostTimerRendered(')):
                (main/filename).write_text(block(source, anchor)+'\n')
            executable = workspace/'test'
            result = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(main),
                str(HOST/'test_sophia_timer_v421.cc'), '-o', str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS actual timer scope/types/monotonic deadline/replay/clear/reconnect/mute isolation/native framebuffer receipts', result.stdout)

    def test_actual_native_renderer_retains_primary_views_and_draws_timer_badge(self):
        if not shutil.which('g++'):
            self.skipTest('native C++ compiler unavailable')
        manifest = json.loads((HOST/'sophia_timer_v421_manifest.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            main = workspace/'main'; main.mkdir()
            shutil.copyfile(ROOT/'firmware/spotpear/touch_screen.h', main/'touch_screen.h')
            apply(workspace, ROOT/'tests/fixtures/sophia_v420_timer_basis.patch')
            self.assertEqual(digest(main/'touch_screen.h'), manifest['baseline_sources']['main/touch_screen.h'])
            apply(workspace, HOST/'sophia_timer_v421.patch', 'touch_screen.h')
            self.assertEqual(digest(main/'touch_screen.h'), manifest['candidate_sources']['main/touch_screen.h'])
            # Synthetic one-pixel glyphs exercise actual placement/priority;
            # installed private atlas and physical panel are not claimed tested.
            (main/'touch_atlas.h').write_text('''#pragma once
#include <cstdint>
#include <array>
namespace atlas {
constexpr uint16_t bg=0,amber=0xffe0,ink=0xffff,muted=0x8888,blue=0x001f,mint=0x07e0,lilac=0xf81f;
struct Sprite {int x,y,w,h,pos,advance;};
const auto sprites=[] {std::array<Sprite,200> a{};for(auto& s:a)s={0,0,1,1,0,4};return a;}();
const auto codes=[] {std::array<unsigned,129> a{};for(unsigned i=0;i<128;++i)a[i]=i;a[128]=0x2026;return a;}();
constexpr unsigned char pixels[]={0xff};
}
''')
            (main/'raster.cc').write_text('''#include "touch_screen.h"
#include <cassert>
#include <iostream>
int main(){
    std::vector<uint16_t> before(240*240),after(240*240);
    for(auto view:{touchui::View::Weather,touchui::View::Clock,touchui::View::Muted,touchui::View::Speaking}){
        touchui::Page p;p.view=view;p.value="20";p.detail="detail";
        touchui::Screen(before.data()).draw(p);p.badge="0:10";
        touchui::Screen(after.data()).draw(p);assert(p.view==view);
        unsigned changed=0;
        for(unsigned i=0;i<before.size();++i)if(before[i]!=after[i]){++changed;assert(i/240==35);}
        assert(changed>0);
    }
    std::cout<<"PASS actual native badge raster with primary view preserved\\n";
}
''')
            executable = workspace/'raster'
            result = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(main),
                str(main/'raster.cc'), '-o', str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS actual native badge raster with primary view preserved', result.stdout)


if __name__ == '__main__':
    unittest.main()

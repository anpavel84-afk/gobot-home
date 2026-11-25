#!/usr/bin/env python3
"""Read a private v421 build and emit content-free evidence; no device access.

This verifies source/SDK/assets/model embedding and the ESP application
descriptor. The caller separately runs the installed esptool image-info for
the complete image checksum; no build, network or serial command is executed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_file(path, expected, size=None):
    if not path.is_file() or sha(path) != expected or size is not None and path.stat().st_size != size:
        raise SystemExit('Build evidence checksum/size guard failed: '+str(path))


def app_info(path, version, capacity):
    if not path.is_file() or path.is_symlink():
        raise SystemExit('App image must be a regular private file')
    size = path.stat().st_size
    if not 256 <= size <= capacity or ((size+4095)//4096)*4096 > capacity:
        raise SystemExit('App image exceeds the preserved app partition')
    with path.open('rb') as handle:
        header = handle.read(256)
    if (header[0] != 0xe9 or not 1 <= header[1] <= 16 or struct.unpack_from('<H', header, 12)[0] != 9
            or struct.unpack_from('<I', header, 32)[0] != 0xabcd5432
            or header[48:80].split(b'\0', 1)[0] != version.encode('ascii')):
        raise SystemExit('Unexpected ESP32-S3 application descriptor/version')
    return {'sha256': sha(path), 'bytes': size, 'version': version,
            'app_slot_free': capacity-size, 'chip': 'esp32s3'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--build-log', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    baseline, project, image = args.baseline.resolve(), args.project.resolve(), args.image.resolve()
    if baseline == project or baseline in project.parents or project in baseline.parents:
        raise SystemExit('Baseline and candidate must be independent')
    if project not in image.parents or args.report.exists() or not args.build_log.is_file():
        raise SystemExit('Candidate image/log or absent evidence path guard failed')
    here = Path(__file__).resolve().parent
    manifest_path = here/'sophia_timer_v421_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    require_file(here/manifest['parent_manifest_file'], manifest['parent_manifest_sha256'])
    require_file(here/'sophia_timer_v421.patch', manifest['patch_sha256'])
    for relative, expected in manifest['baseline_sources'].items():
        require_file(baseline/relative, expected)
    for relative, expected in {**manifest['baseline_sources'], **manifest['candidate_sources']}.items():
        require_file(project/relative, expected)
    for directory in (baseline, project):
        require_file(directory/'sdkconfig', manifest['sdkconfig_sha256'])
        for relative, guard in manifest['protected_binary_hashes'].items():
            require_file(directory/relative, guard['sha256'], guard['size'])
    baseline_image = baseline/'build/xiaozhi.bin'
    require_file(baseline_image, manifest['baseline_app_sha256'], manifest['baseline_app_size'])
    before = app_info(baseline_image, manifest['baseline_version'], manifest['app_slot_capacity'])
    candidate = app_info(image, manifest['candidate_version'], manifest['app_slot_capacity'])
    model = (project/'main/sophia_srmodels.bin').read_bytes()
    if image.read_bytes().count(model) != 1:
        raise SystemExit('Exact Sophia model must be embedded once')
    report = {'schema': 1, 'candidate': candidate, 'rollback': before,
        'manifest_sha256': sha(manifest_path), 'patch_sha256': manifest['patch_sha256'],
        'build_log_sha256': sha(args.build_log), 'baseline_preserved': True,
        'baseline_source_guards': len(manifest['baseline_sources']),
        'candidate_source_guards': len(manifest['candidate_sources']),
        'protected_source_guards': len(manifest['protected_source_paths']),
        'protected_binary_guards': len(manifest['protected_binary_hashes']),
        'sdkconfig_unchanged': True, 'sophia_model_embedded_exact_once': True,
        'image_checksum_tool_required': True, 'flashed': False,
        'physical_visible_countdown_verified': False, 'physical_audible_alarm_verified': False}
    with args.report.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

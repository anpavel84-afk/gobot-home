#!/usr/bin/env python3
"""Prepare an isolated copy of the installed Sophia V4; never flash hardware.

All private models, enrolled configuration and existing build cache remain on
the authorized private build host. This public utility contains source only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Existing exact V4 project")
    parser.add_argument("--destination", type=Path, required=True, help="New, absent isolated directory")
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.destination.resolve()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here/"sophia_unified_v4_manifest.json").read_text())
    patch = here/"sophia_unified_v4.patch"
    if source == destination or source in destination.parents:
        raise SystemExit("Destination must be independent of the preserved source project")
    if destination.exists():
        raise SystemExit("Destination already exists; inspect it rather than overwriting work")
    if sha(patch) != manifest["patch_sha256"]:
        raise SystemExit("Source patch checksum mismatch")
    for relative, expected in manifest["baseline_sources"].items():
        path = source/relative
        if not path.is_file() or sha(path) != expected:
            raise SystemExit("Exact installed V4 source guard failed: "+relative)
    for relative, expected in [
        ("sdkconfig", manifest["sdkconfig_sha256"]),
        ("build/xiaozhi.bin", manifest["baseline_app_sha256"]),
    ]:
        if not (source/relative).is_file() or sha(source/relative) != expected:
            raise SystemExit("Private baseline guard failed: "+relative)
    if (source/"build/xiaozhi.bin").stat().st_size != manifest["baseline_app_size"]:
        raise SystemExit("Baseline app size mismatch")
    for relative, guard in manifest["protected_binary_hashes"].items():
        path = source/relative
        if (not path.is_file() or sha(path) != guard["sha256"]
                or path.stat().st_size != guard["size"]):
            raise SystemExit("Private model/partition/asset guard failed: "+relative)
    shutil.copytree(source, destination, symlinks=True)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=destination, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=destination, check=True)
    for relative, expected in manifest["candidate_sources"].items():
        if sha(destination/relative) != expected:
            raise SystemExit("Patched source checksum mismatch: "+relative)
    for relative in ["main/embedded_sophia_engine.hpp", "main/sophia_pcm_tap.hpp",
                     "main/audio/engines/afe_audio_engine.cc",
                     "main/audio/engines/lite_audio_engine.cc",
                     "sdkconfig", "dependencies.lock"]:
        if (source/relative).read_bytes() != (destination/relative).read_bytes():
            raise SystemExit("Wake-preservation guard failed: "+relative)
    print(json.dumps({"prepared": str(destination), "source_preserved": True,
                      "candidate_version": manifest["candidate_version"],
                      "build_required": True, "flashed": False}, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prepare the wake recognition and transient duck successor to exact installed Sophia 0.4.19; never flash.

Run only on the existing authorized private builder. Models, enrolled/private
configuration and compiled artifacts remain there. Existing directories are
never overwritten and the original 0.4.19 app is verified before copying.
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


def require_file(path, expected, *, size=None):
    if not path.is_file() or sha(path) != expected or (size is not None and path.stat().st_size != size):
        raise SystemExit("Private baseline checksum/size guard failed: "+str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Preserved exact 0.4.19 private project")
    parser.add_argument("--destination", type=Path, required=True, help="New independent, absent directory")
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.destination.resolve()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here/"sophia_duck_v420_manifest.json").read_text())
    patch = here/"sophia_duck_v420.patch"
    if source == destination or source in destination.parents or destination in source.parents:
        raise SystemExit("Destination must be independent of the preserved source project")
    if destination.exists():
        raise SystemExit("Destination already exists; inspect it instead of overwriting")
    if not source.is_dir():
        raise SystemExit("Private source project does not exist")
    require_file(here/"sophia_touch_v419_manifest.json", manifest["parent_manifest_sha256"])
    require_file(patch, manifest["patch_sha256"])
    for relative, expected in manifest["baseline_sources"].items():
        require_file(source/relative, expected)
    require_file(source/"sdkconfig", manifest["sdkconfig_sha256"])
    require_file(source/"build/xiaozhi.bin", manifest["baseline_app_sha256"],
                 size=manifest["baseline_app_size"])
    for relative, guard in manifest["protected_binary_hashes"].items():
        require_file(source/relative, guard["sha256"], size=guard["size"])
    shutil.copytree(source, destination, symlinks=True)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=destination, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=destination, check=True)
    for relative, expected in manifest["candidate_sources"].items():
        require_file(destination/relative, expected)
    for relative in [*manifest["protected_source_paths"], "sdkconfig"]:
        if (source/relative).read_bytes() != (destination/relative).read_bytes():
            raise SystemExit("Preserved source changed: "+relative)
    for relative, guard in manifest["protected_binary_hashes"].items():
        require_file(destination/relative, guard["sha256"], size=guard["size"])
    print(json.dumps({"prepared": str(destination), "baseline_source_guards": len(manifest["baseline_sources"]),
        "candidate_source_guards": len(manifest["candidate_sources"]), "source_preserved": True,
        "candidate_version": manifest["candidate_version"], "build_required": True, "flashed": False}, indent=2))


if __name__ == "__main__":
    main()

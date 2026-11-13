"""Prepare a fresh pinned checkout from public overlay and the private per-board build inputs."""
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copyfile
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("private_sources", type=Path, help="verified extracted GoBot v1 source bundle on PLAN")
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here/"manifest.json").read_text())
    def git(*cmd):
        return subprocess.check_output(["git", *cmd], cwd=checkout).decode().strip()
    if git("rev-parse", "HEAD") != manifest["upstream"] or git("status", "--porcelain"):
        parser.error("fresh unmodified pinned checkout required")
    patch = here/"gobot-native.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["source_patch_sha256"]:
        parser.error("patch does not match manifest")
    inputs = args.private_sources
    files = [(inputs/"sdkconfig", "sdkconfig"), (inputs/"gobot_ca.pem", "gobot_ca.pem"),
             (inputs/"gobot_kws_samples.h", "main/gobot_kws_samples.h"),
             (inputs/"gobot_build_info.h", "main/gobot_build_info.h"),
             (here/"dependencies.lock", "dependencies.lock"),
             (here/"sdkconfig.gobot.defaults", "sdkconfig.gobot.defaults"),
             (here/"gobot_platform.h", "main/gobot_platform.h"),
             (here/"gobot_turn_guard.h", "main/gobot_turn_guard.h")]
    if not all(src.is_file() for src, _ in files):
        parser.error("missing private or public build input")
    if hashlib.sha256((inputs/"sdkconfig").read_bytes()).hexdigest() != "c2c23c572e10d364bdc07a4352c8a0a7cc61cdd427501688d3672f114db61036":
        parser.error("hardware configuration changed")
    git("apply", "--check", str(patch))
    git("apply", str(patch))
    for src, dst in files:
        copyfile(src, checkout/dst)


if __name__ == "__main__":
    main()

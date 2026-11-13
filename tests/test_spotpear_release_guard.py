"""Offline safety checks on the firmware release chain; never touch USB."""
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_media_ready_release_preserves_explicit_ack_rollback():
    base=ROOT/'firmware/spotpear/duplex'
    old=json.loads((base/'ack-release.json').read_text())
    new=json.loads((base/'media-ready-release.json').read_text())
    assert new['previous_sha256']==old['app_sha256']
    assert new['app_sha256']!=old['app_sha256'] and len(new['app_sha256'])==64
    assert 0<new['app_bytes']<0x3f0000

def test_each_flash_source_is_indexed_by_one_action_not_a_tuple_key():
    tree=ast.parse((ROOT/'firmware/spotpear_bringup.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Subscript) and isinstance(target.value,ast.Name) and target.value.id=='sources':
                    assert not isinstance(target.slice,ast.Tuple)

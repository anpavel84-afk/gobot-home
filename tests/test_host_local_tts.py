"""No network, no cloud TTS, no actual voices: mocked bounded local PCM tests."""
from __future__ import annotations
import json
import math
import struct
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"services"/"voice"))
from host_local_tts import offline_russian_packets


def make_input(tmp_path, *, language="ru_RU", rate=22050):
    model=tmp_path/"voice.onnx"
    model.write_bytes(b"not-a-real-private-voice")
    model.with_suffix(".onnx.json").write_text(
        json.dumps({"language":{"code":language},"audio":{"sample_rate":rate}}),
        encoding="utf8")
    binary=tmp_path/"piper.exe"
    binary.write_bytes(b"stub")
    return model,binary


def test_offline_voice_requires_russian_and_exact_rate(tmp_path):
    model,binary=make_input(tmp_path,language="en_US")
    with pytest.raises(ValueError,match="unexpected_local_voice_rate"):
        offline_russian_packets(model,piper_path=binary)


def test_offline_voice_pcm_is_low_volume_and_24k_opus(tmp_path):
    model,binary=make_input(tmp_path)
    sample_rate=22050
    pcm=b"".join(struct.pack("<h",int(25000*math.sin(2*math.pi*350*n/sample_rate)))
                 for n in range(sample_rate))
    with patch("host_local_tts.subprocess.run",
               return_value=SimpleNamespace(returncode=0,stdout=pcm,stderr=b"")) as run:
        packets=offline_russian_packets(model,piper_path=binary)
    assert 17<=len(packets)<=21
    assert run.call_args.kwargs["stdout"]==-1
    assert "--output-raw" in run.call_args.args[0]
    assert "--volume" in run.call_args.args[0]
    assert "Привет, я Гобот." in run.call_args.kwargs["input"].decode()
    assert all(isinstance(x,bytes) and 0<len(x)<=4096 for x in packets)


def test_offline_voice_refuses_oversize_duration(tmp_path):
    model,binary=make_input(tmp_path)
    pcm=b"\0\0"*(22050*5)
    with patch("host_local_tts.subprocess.run",
               return_value=SimpleNamespace(returncode=0,stdout=pcm,stderr=b"")):
        with pytest.raises(ValueError,match="offline_phrase_duration_outside"):
            offline_russian_packets(model,piper_path=binary)

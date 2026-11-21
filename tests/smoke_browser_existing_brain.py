"""One-shot free sanity test of ORIGINAL existing Brain Service on isolated DB."""
import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
root = Path(__file__).resolve().parents[2] / "GoBotHome"
sys.path.insert(0, str(root / "services" / "brain"))
from gobot.config import load
from gobot.brain import Service
from gobot.models import ChatRequest

async def run():
    with tempfile.TemporaryDirectory(prefix="gobot-host-a-existing-brain-") as t:
        from os import chdir
        chdir(root)
        config = replace(load(), db=str(Path(t) / "browser-test.sqlite"),
                         fast_provider="mock", allow_paid=False)
        service = Service(config)
        req = ChatRequest(text="Сколько времени?", mode="auto",
            remember=False, device_id="host-a-browser-preflight")
        replay = await service.prepare(req)
        print("ORIGINAL_BRAIN_PREPARE_OK")
        counts={}
        async for message in service.events(req, replay):
            counts[message.type] = counts.get(message.type,0)+1
            if message.type=="error":
                print("ORIGINAL_BRAIN_EVENT_ERROR_CODE",message.data.get("code"))
            if message.type=="final":
                print("ORIGINAL_BRAIN_FINAL_PROVIDER",message.data.get("provider"))
                print("ORIGINAL_BRAIN_FINAL_TEXT_LENGTH",len(message.data.get("text") or ""))
        print("ORIGINAL_BRAIN_EVENT_TYPES",counts)
        if counts.get("final",0)!=1:
            raise RuntimeError("existing_brain_no_final")
asyncio.run(run())

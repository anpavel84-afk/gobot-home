"""Read-only OpenAI Realtime response.done usage tap for HOST-A Browser Lab.

This wrapper forwards exactly the same byte-for-byte websocket commands and
events used by the existing original Brain Speech. It never adds a response,
sends a prompt or changes prices. Only token counts from response.done are
retained, not text/audio/credentials.
"""
from __future__ import annotations

import json
from websockets.asyncio.client import connect

from host_a_browser_metered_budget import realtime_usage_usd, BudgetError


class MeteredWebSocket:
    def __init__(self, ws, callback):
        self._ws=ws
        self._callback=callback

    async def send(self, data):
        return await self._ws.send(data)

    async def recv(self):
        data=await self._ws.recv()
        if isinstance(data,str) and '"response.done"' in data:
            try:
                obj=json.loads(data)
                if obj.get("type")=="response.done":
                    response=obj.get("response") or {}
                    usage=response.get("usage")
                    ident=response.get("id")
                    if isinstance(usage,dict) and isinstance(ident,str):
                        self._callback(ident,usage)
            except (ValueError,TypeError,BudgetError):
                # Never disrupt the existing TTS just to measure spend;
                # missing/invalid billing telemetry falls back to the
                # conservative fixed bound in browser budget settlement.
                pass
        return data

    def __getattr__(self,name):
        return getattr(self._ws,name)


class MeteredConnect:
    def __init__(self, inner, callback):
        self._inner=inner
        self._callback=callback

    async def __aenter__(self):
        ws=await self._inner.__aenter__()
        return MeteredWebSocket(ws,self._callback)

    async def __aexit__(self,*args):
        return await self._inner.__aexit__(*args)


class RealtimeUsageTap:
    def __init__(self,base_connector=connect):
        self.base_connector=base_connector
        self._usage=[]
        self._ids=set()
        self.rejected_reports=0

    def begin_turn(self):
        self._usage=[]
        self._ids.clear()
        self.rejected_reports=0

    def _observe(self,ident,usage):
        if ident in self._ids:
            return
        # Validate all counters and rates before retaining anything.
        try:
            realtime_usage_usd(usage)
        except BudgetError:
            self.rejected_reports+=1
            return
        self._ids.add(ident)
        # Keep ONLY fields needed for accounting, no response content.
        self._usage.append({
            "input_tokens":usage.get("input_tokens"),
            "output_tokens":usage.get("output_tokens"),
            "input_token_details":usage.get("input_token_details",{}),
            "output_token_details":usage.get("output_token_details",{}),
        })

    def connector(self,*args,**kwargs):
        return MeteredConnect(
            self.base_connector(*args,**kwargs), self._observe)

    def usage(self):
        # A copied pure JSON structure prevents asynchronous mutation.
        return json.loads(json.dumps(self._usage))

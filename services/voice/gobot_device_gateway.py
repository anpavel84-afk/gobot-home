"""Private ESP32 WebSocket/Opus transport for the existing GoBot Brain.

No cloud credentials on the gadget. No audio or transcript files. Only explicit
local-wake turns are accepted; one completed request per connection. A separate
hardware_test mode uses a synthetic local acknowledgement, never a fake Brain reply.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import contextlib
from fractions import Fraction
import hashlib
import hmac
import io
import ipaddress
import sys
import json
from pathlib import Path
import ssl
import time
import uuid
import wave

import av
import httpx
import numpy as np
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from websockets.datastructures import MultipleValuesError

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'data/hardware/gobot-v1'
MAX_PCM = 16000 * 2 * 26
MAX_PACKET = 4096
sys.path.insert(0, str(ROOT / 'services/brain'))
MAX_TURN_SECONDS = 180


class OpusInput:
    def __init__(self):
        self.codec = av.CodecContext.create('opus', 'r')
        self.codec.extradata = b'OpusHead\x01\x01\x00\x00' + (16000).to_bytes(4, 'little') + b'\x00\x00\x00'
        self.codec.open()
        self.resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        self.pcm = bytearray()
        self.packets = 0

    def feed(self, packet: bytes) -> None:
        if not 0 < len(packet) <= MAX_PACKET or self.packets >= 500:
            raise ValueError('audio_packet_limit')
        self.packets += 1
        for decoded in self.codec.decode(av.Packet(packet)):
            for frame in self.resampler.resample(decoded):
                self.pcm.extend(frame.to_ndarray().astype('<i2', copy=False).tobytes())
                if len(self.pcm) > MAX_PCM:
                    raise ValueError('audio_duration_limit')

    def wav(self) -> bytes:
        for frame in self.resampler.resample(None):
            self.pcm.extend(frame.to_ndarray().astype('<i2', copy=False).tobytes())
        if not 3200 <= len(self.pcm) <= MAX_PCM:
            raise ValueError('empty_or_excessive_audio')
        out = io.BytesIO()
        with wave.open(out, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(self.pcm)
        return out.getvalue()


class OpusOutput:
    def __init__(self):
        self.codec = av.CodecContext.create('libopus', 'w')
        self.codec.sample_rate = 24000
        self.codec.layout = 'mono'
        self.codec.format = 's16'
        self.codec.bit_rate = 24000
        self.codec.time_base = Fraction(1, 24000)
        self.codec.options = {'frame_duration': '60', 'application': 'voip'}
        self.codec.open()
        self.resampler = None
        self.input_rate = None
        self.fifo = av.AudioFifo()
        self.pts = 0
        self.closed = False

    def _frames(self, flush=False):
        packets = []
        while self.fifo.samples >= 1440 or (flush and self.fifo.samples):
            frame = self.fifo.read(1440, partial=flush)
            frame.pts = self.pts; frame.time_base = Fraction(1, 24000)
            self.pts += frame.samples
            packets.extend(bytes(packet) for packet in self.codec.encode(frame))
        return packets

    def feed(self, pcm: bytes, rate: int) -> list[bytes]:
        if self.closed or rate not in {16000, 22050, 24000, 44100, 48000} or len(pcm) % 2 or len(pcm) > 262144:
            raise ValueError('invalid_output_pcm')
        if self.input_rate is not None and self.input_rate != rate:
            raise ValueError('sample_rate_changed_mid_turn')
        if not pcm:
            return []
        if self.resampler is None:
            self.input_rate = rate
            self.resampler = av.AudioResampler(format='s16', layout='mono', rate=24000)
        frame = av.AudioFrame.from_ndarray(np.frombuffer(pcm, dtype='<i2').reshape(1, -1), format='s16', layout='mono')
        frame.sample_rate = rate
        for converted in self.resampler.resample(frame):
            converted.pts = None
            self.fifo.write(converted)
        return self._frames()

    def finish(self) -> list[bytes]:
        if self.closed:
            return []
        self.closed = True
        if self.resampler:
            for frame in self.resampler.resample(None):
                frame.pts = None; self.fifo.write(frame)
        return self._frames(flush=True) + [bytes(packet) for packet in self.codec.encode(None)]


def authorize(headers, config: dict) -> bool:
    try:
        return (headers.get('Device-Id', '').lower() == config['device_mac']
                and headers.get('Protocol-Version') == '1'
                and hmac.compare_digest(headers.get('Authorization', ''), 'Bearer ' + config['device_token']))
    except (KeyError, ValueError, TypeError, MultipleValuesError):
        return False


def validate_hello(message: dict) -> bool:
    audio = message.get('audio_params', {})
    return (message.get('type') == 'hello' and message.get('transport') == 'websocket'
            and type(message.get('version')) is int and message['version'] == 1 and isinstance(audio, dict)
            and audio.get('format') == 'opus' and audio.get('sample_rate') == 16000
            and audio.get('channels') == 1 and audio.get('frame_duration') == 60)


class Gateway:
    def __init__(self, config: dict, brain_token: str, *, client_factory=httpx.AsyncClient):
        self.config = config
        self.auth = {'Authorization': 'Bearer ' + brain_token}
        self.client_factory = client_factory
        self.active = False
        self.next_packet_at = 0.0
        self.stats = {'accepted': 0, 'completed': 0, 'rejected': 0, 'errors': 0, 'received_packets': 0}
        self.mode_flow = None  # Only a server-issued, guest-scoped mode handle survives a wake.
        self.legacy_turn = None
        self.quota_path = PRIVATE / 'hardware-usage.json'
        self.max_daily_turns = int(config.get('max_daily_turns', 20))

    def reserve_manual_turn(self) -> None:
        # Durable, bounded count. Never reset by restarting the gateway.
        day = time.strftime('%Y-%m-%d', time.gmtime())
        value = json.loads(self.quota_path.read_text()) if self.quota_path.exists() else {}
        count = value.get('turns', 0) if value.get('day') == day else 0
        if count >= self.max_daily_turns:
            raise ValueError('hardware_daily_turn_limit')
        temp = self.quota_path.with_suffix('.tmp')
        temp.write_text(json.dumps({'day': day, 'turns': count + 1}), encoding='utf8')
        temp.replace(self.quota_path)

    async def handle(self, ws):
        if ws.request.path != '/xiaozhi/v1/' or not authorize(ws.request.headers, self.config):
            self.stats['rejected'] += 1
            await ws.close(1008, 'Unauthorized device'); return
        if self.active:
            await ws.close(1013, 'Device busy'); return
        self.active = True
        self.stats['accepted'] += 1
        session = str(uuid.uuid4())
        turn_id = str(uuid.uuid4())
        response_task = None
        state = 'hello'
        decoder = None
        deadline = asyncio.get_running_loop().time() + 8
        async def send(obj):
            await ws.send(json.dumps({**obj, 'session_id': session}, ensure_ascii=False))
        try:
            async with asyncio.timeout(MAX_TURN_SECONDS + 35):
                iterator = aiter(ws)
                while True:
                    async with asyncio.timeout_at(deadline):
                        raw = await anext(iterator, None)
                    if raw is None:
                        break
                    if isinstance(raw, bytes):
                        if state != 'capture' or decoder is None:
                            raise ValueError('audio_outside_capture')
                        decoder.feed(raw); self.stats['received_packets'] += 1
                        continue
                    if len(raw) > 16384:
                        raise ValueError('control_too_large')
                    obj = json.loads(raw)
                    if not isinstance(obj, dict):
                        raise ValueError('invalid_control')
                    kind = obj.get('type')
                    if state != 'hello' and obj.get('session_id') != session:
                        raise ValueError('wrong_session')
                    if kind == 'hello' and state == 'hello':
                        if not validate_hello(obj):
                            raise ValueError('invalid_hello')
                        await send({'type': 'hello', 'version': 1, 'transport': 'websocket',
                                    'audio_params': {'format': 'opus', 'sample_rate': 24000, 'channels': 1, 'frame_duration': 60}})
                        state = 'ready'
                    elif kind == 'listen' and obj.get('state') == 'start' and state == 'ready':
                        if obj.get('mode') != 'auto':
                            raise ValueError('only_wake_auto_turn_supported')
                        decoder = OpusInput(); state = 'capture'
                        deadline = asyncio.get_running_loop().time() + 26
                    elif kind == 'listen' and obj.get('state') == 'stop' and state == 'capture':
                        state = 'respond'
                        deadline = asyncio.get_running_loop().time() + MAX_TURN_SECONDS + 8
                        data = decoder.wav(); decoder = None
                        response_task = asyncio.create_task(self.respond(ws, send, data, turn_id))
                    elif kind == 'abort':
                        if response_task:
                            response_task.cancel()
                            await asyncio.gather(response_task, return_exceptions=True)
                        await ws.close(1000, 'Cancelled'); break
                    else:
                        raise ValueError('invalid_state_transition')
        except (ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception as error:
            self.stats['errors'] += 1
            print(json.dumps({'event': 'device_connection_error', 'kind': type(error).__name__}), flush=True)
            with contextlib.suppress(Exception): await ws.close(1008, 'Invalid or expired turn')
        finally:
            if response_task:
                response_task.cancel()
                await asyncio.gather(response_task, return_exceptions=True)
            if self.legacy_turn == turn_id:
                with contextlib.suppress(Exception):
                    async with self.client_factory(trust_env=False, timeout=3) as client:
                        await client.post(self.config['brain_url'] + '/api/v1/turns/' + turn_id + '/cancel', headers=self.auth)
            self.legacy_turn = None
            self.active = False
            self.save_stats()

    def save_stats(self):
        # Contains counts and mode only, never prompts, recordings or credentials.
        tmp = PRIVATE / 'gateway-status.tmp'
        tmp.write_text(json.dumps({'active': self.active, 'mode': self.config['mode'], **self.stats}), encoding='utf8')
        tmp.replace(PRIVATE / 'gateway-status.json')

    async def send_audio(self, ws, packet: bytes):
        if not 0 < len(packet) <= MAX_PACKET:
            raise ValueError('encoded_packet_size')
        now = asyncio.get_running_loop().time()
        scheduled = max(now, self.next_packet_at)
        if scheduled > now:
            await asyncio.sleep(scheduled-now)
        await ws.send(packet)
        self.next_packet_at = scheduled + .060

    async def respond(self, ws, send, wav: bytes, turn_id: str):
        self.next_packet_at = 0.0
        try:
            async with asyncio.timeout(MAX_TURN_SECONDS):
                if self.config['mode'] == 'hardware_test':
                    # This announces a hardware test, not fabricated recognition/Brain output.
                    rate = 24000
                    samples = np.arange(rate // 4)
                    envelope = np.sin(np.pi * samples / len(samples)) ** 2
                    acknowledgement = (4500 * envelope * np.sin(2*np.pi*440*samples/rate)).astype('<i2').tobytes()
                    await send({'type': 'tts', 'state': 'start'})
                    await asyncio.sleep(.08)
                    await send({'type': 'tts', 'state': 'sentence_start', 'text': 'ГоБот. Проверка оборудования.'})
                    encoder = OpusOutput()
                    for pos in range(0, len(acknowledgement), 8192):
                        for packet in encoder.feed(acknowledgement[pos:pos+8192], rate):
                            await self.send_audio(ws, packet)
                    for packet in encoder.finish(): await self.send_audio(ws, packet)
                    await send({'type': 'tts', 'state': 'stop'})
                elif self.config['mode'] == 'live_c':
                    if self.config.get('hardware_live_consent') is not True:
                        raise PermissionError('hardware_live_permission_required')
                    from spotpear_live import live_turn
                    async with self.client_factory(trust_env=False, timeout=httpx.Timeout(35, connect=3)) as client:
                        legacy = await self.active_legacy_flow(client)
                        if legacy:
                            await self.brain_response(ws, send, wav, turn_id, flow_id=legacy)
                        else:
                            self.reserve_manual_turn()
                            flow = await live_turn(client, self.config, self.auth, wav, turn_id, send,
                                                   lambda packet: self.send_audio(ws, packet), OpusOutput())
                            self.mode_flow = self.confirmed_legacy(flow)
                elif self.config['mode'] == 'legacy_a':
                    await self.brain_response(ws, send, wav, turn_id)
                else:
                    raise ValueError('unknown_gateway_mode')
                self.legacy_turn = None
                self.stats['completed'] += 1
                self.save_stats()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.stats['errors'] += 1
            print(json.dumps({'event': 'device_response_error', 'kind': type(error).__name__}), flush=True)
            with contextlib.suppress(Exception): await ws.close(1011, 'GoBot response unavailable')

    @staticmethod
    def confirmed_legacy(flow):
        if not isinstance(flow, dict) or flow.get('active') is not True or flow.get('provider_closed') is not True or flow.get('mode') != 'legacy':
            return None
        try:
            return str(uuid.UUID(flow['mode_conversation_id']))
        except (KeyError, ValueError, TypeError, AttributeError):
            return None

    async def active_legacy_flow(self, client):
        if not self.mode_flow:
            return None
        response = await client.post(f"{self.config['brain_url']}/api/v1/live/modes/{self.mode_flow}/command",
                                     headers=self.auth, json={'device_id':self.config['device_id'],
                                     'client_id':self.config['device_id'],'action':'activity'})
        if response.status_code in {403, 404}:
            self.mode_flow = None
            return None
        response.raise_for_status()
        self.mode_flow = self.confirmed_legacy(response.json())
        return self.mode_flow

    async def brain_response(self, ws, send, wav: bytes, turn_id: str, flow_id=None):
        if not self.config.get('paid_speech_consent'):
            raise ValueError('speech_permission_required')
        self.reserve_manual_turn()
        config = self.config
        async with self.client_factory(trust_env=False, timeout=httpx.Timeout(100, connect=3)) as client:
            response = await client.post(config['brain_url']+'/api/v1/audio/transcribe', content=wav,
                params={'provider': config['stt_provider'], 'paid_consent': True,
                        'device_id': config['device_id'], 'trace_id': turn_id},
                headers={**self.auth, 'Content-Type': 'audio/wav'})
            response.raise_for_status()
            recognized = response.json()
            text = recognized.get('text', '').strip()
            if not text or len(text) > 8000:
                raise ValueError('no_speech')
            await send({'type': 'stt', 'text': text})
            request = {'text': text, 'device_id': config['device_id'], 'conversation_id': config['conversation_id'],
                       'turn_id': turn_id, 'correlation_id': turn_id, 'trace_id': turn_id,
                       'client_kind': 'device', 'client_id': config['device_id'], 'remember': False,
                       'provider': 'auto', 'mode': 'auto', 'speak': True,
                       'tts_provider': config['tts_provider'], 'tts_voice': config['tts_voice'],
                       'paid_tts_consent': True, 'paid_chat_consent': config.get('paid_chat_consent',False),
                       'usage_consent': config.get('cli_usage_consent',False),
                       'tts_character_limit': 1600, 'expensive_fallback_approved': False}
            if flow_id:
                request['mode_conversation_id'] = flow_id
            encoder = OpusOutput(); started = False; expected_seq = 0; audio_bytes = 0
            self.legacy_turn = turn_id
            async with client.stream('POST',config['brain_url']+'/api/v1/chat/voice/stream',headers=self.auth,json=request) as reply:
                reply.raise_for_status()
                async for line in reply.aiter_lines():
                    if not line.startswith('data: '): continue
                    if len(line)>400000: raise ValueError('brain_event_too_large')
                    event=json.loads(line[6:]); kind=event.get('type'); data=event.get('data',{})
                    if event.get('turn_id') != turn_id:
                        raise ValueError('wrong_brain_turn')
                    if kind=='audio_start':
                        if started: raise ValueError('duplicate_audio_start')
                        started=True; await send({'type':'tts','state':'start'}); await asyncio.sleep(.08)
                    elif kind=='audio_chunk':
                        if not started or data.get('seq')!=expected_seq or data.get('format')!='pcm_s16le':
                            raise ValueError('audio_order_or_format')
                        expected_seq+=1
                        pcm=base64.b64decode(data['pcm'],validate=True); audio_bytes+=len(pcm)
                        if audio_bytes>24000*2*150: raise ValueError('output_duration_limit')
                        for packet in encoder.feed(pcm,int(data['sample_rate'])): await self.send_audio(ws, packet)
                    elif kind=='sentence_ready':
                        await send({'type':'tts','state':'sentence_start','text':str(data.get('text',''))[:1000]})
                    elif kind=='visual_response':
                        from spotpear_scene import project_scene
                        try:
                            scene = project_scene(data['presentation'])
                        except (KeyError, ValueError):
                            continue
                        await send(scene)
                    elif kind=='tool_status' and flow_id and data.get('status') == 'conversation_mode':
                        self.mode_flow = self.confirmed_legacy(data.get('mode'))
                        await send({'type':'tts','state':'start'})
                        await send({'type':'tts','state':'stop'})
                        return
                    elif kind=='widget_command':
                        command=data.get('command')
                        if isinstance(command,dict) and command.get('type')=='custom': await send(command)
                    elif kind in {'error','cancelled','tts_error'}:
                        raise ValueError('brain_or_speech_error')
                    elif kind=='audio_stop':
                        if data.get('reason') not in {'finished','no_audio'}: raise ValueError('incomplete_audio')
                        if not started or not audio_bytes: raise ValueError('no_output_audio')
                        for packet in encoder.finish(): await self.send_audio(ws, packet)
                        await send({'type':'tts','state':'stop'})
                        return
            raise ValueError('missing_audio_stop')


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=PRIVATE/'gateway.json')
    args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf8'))
    bind = ipaddress.IPv4Address(config['bind'])
    approved_lan = any(bind in ipaddress.ip_network(net) for net in ('10.0.0.0/8', '192.168.0.0/16'))
    if not approved_lan or config['port']!=18789 or config.get('url') != f'wss://{bind}:18789/xiaozhi/v1/':
        raise ValueError('unreviewed_listen_address')
    if config['brain_url']!='http://127.0.0.1:18781':raise ValueError('brain_must_be_loopback')
    if config['mode'] not in {'hardware_test','legacy_a','live_c'}:
        raise ValueError('explicit_hardware_mode_required')
    token = json.loads((ROOT/'run/keys.json').read_text())['api_token'] if config['mode']!='hardware_test' else ''
    gateway=Gateway(config,token)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.minimum_version=ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(PRIVATE/'server.pem',PRIVATE/'server.key')
    async with serve(gateway.handle,config['bind'],config['port'],ssl=tls,max_size=16384,max_queue=8,
                     ping_interval=20,ping_timeout=10,open_timeout=8,close_timeout=2,
                     compression=None):
        gateway.save_stats()
        print(json.dumps({'event':'gobot_gateway_ready','mode':config['mode'],'port':config['port'],'tls':True}),flush=True)
        await asyncio.Future()

if __name__=='__main__':
    asyncio.run(main())

"""Finite, cloud-free physical v2 Gateway check on the EXISTING enrolled port.

Stop the owned production Gateway before running this tool. It binds the same
TLS socket and enrolled-device authorization, uses the production SophiaConnection
and Opus codec, and replaces only its Brain peer with an in-memory fixture.
It never imports a provider/key loader, changes a grant, persists PCM/text, or
claims real AI/voice/acoustic acceptance. The output is a quiet synthetic tone.
The existing Brain can remain running; no second Brain or port is created.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import suppress
import json
import math
from pathlib import Path
import ssl
import struct
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/voice'))
from gobot_device_gateway import OpusOutput,authorize,validate_hello
from sophia_connection import SophiaConnection
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed


def tone(seconds=.6):
    count=int(seconds*24000)
    return b''.join(struct.pack('<h',int(1000*math.sin(2*math.pi*440*i/24000)*
        min(1,i/240,(count-i)/240))) for i in range(count))


class FixtureBrain:
    def __init__(self,report):
        self.report=report
        self.queue=asyncio.Queue()
        self.tasks=set()
        self.bytes_received=0
        self.current=None
        self.cancelled=set()
        self.closed=False

    def emit(self,kind,**data):
        self.queue.put_nowait(json.dumps({'type':kind,'data':data}))

    def spawn(self,coro):
        task=asyncio.create_task(coro);self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def __aenter__(self):return self

    async def __aexit__(self,*args):
        self.closed=True
        for task in list(self.tasks):task.cancel()
        await asyncio.gather(*list(self.tasks),return_exceptions=True)

    def __aiter__(self):return self

    async def __anext__(self):
        if self.closed:raise StopAsyncIteration
        return await self.queue.get()

    async def send(self,raw):
        if isinstance(raw,bytes):
            self.bytes_received+=len(raw)
            self.report['fixture_pcm24_samples']+=len(raw)//2
            return
        obj=json.loads(raw);kind=obj.get('type')
        if kind=='hello':
            self.emit('ready',generation_allowed=False,hardware_fixture=True)
            self.report['empty_fixture_transports']+=1
        elif kind=='wake':
            self.report['actual_wake_events']+=1
            self.emit('admission_denied',reason='hardware_fixture_no_paid_admission')
        elif kind=='playback_started':
            self.report['playback_started'].append({'response_id':obj.get('response_id'),
                'plan_monotonic':time.monotonic(),'evidence':'device_i2s_proxy_not_acoustic'})
        elif kind=='playback_finished':
            if obj.get('segment_id'):
                self.report['segments_finished'].append(obj['segment_id'])
            else:
                self.report['whole_playback_finished'].append(obj.get('response_id'))
                self.report['capture_floors'].append(obj.get('sample_floor'))
        elif kind=='mute':self.emit('muted',muted=obj.get('muted') is True)
        elif kind=='stop':
            self.emit('stopped', **({'request_id':obj['request_id']} if obj.get('request_id') else {}))
        elif kind=='input_end':self.emit('input_closed')
        elif kind=='telemetry':
            # Production capture diagnostics may arrive here. Retain no payload,
            # PCM, text, keys or provider state in this cloud-free peer.
            if obj.get('event') not in ('capture_boundary','playback_buffer_summary'):
                raise ValueError('unsupported_fixture_telemetry')
        else:raise ValueError('unsupported_fixture_brain_command')

    async def sound(self,ident,seconds=.6):
        self.current=ident
        self.emit('audio_start',response_id=ident,audio_role='hardware_fixture')
        pcm=tone(seconds)
        for offset in range(0,len(pcm),4800):
            if ident in self.cancelled:return
            self.emit('audio_chunk',response_id=ident,pcm=base64.b64encode(pcm[offset:offset+4800]).decode())
            await asyncio.sleep(.04)
        self.emit('audio_segment_done',response_id=ident,segment_id=ident+':0')
        self.emit('audio_stop',response_id=ident)


async def wait_until(predicate,timeout=10):
    async with asyncio.timeout(timeout):
        while not predicate():await asyncio.sleep(.05)


def barge_aec_evidence(before, after):
    """Require actual DSP/reference work on this connection, not an idle ready bit."""
    keys=('aec_frames','aec_reference_frames','aec_process_max_us',
          'audio_input_stack_hwm_bytes','internal_free','psram_free')
    if after.get('aec_ready') is not True:
        raise ValueError('barge_aec_not_ready')
    if any(type(after.get(key)) is not int or after[key]<0 for key in keys):
        raise ValueError('barge_aec_resources_missing')
    if any(type(before.get(key)) is not int or before[key]<0 for key in ('aec_frames','aec_reference_frames')):
        raise ValueError('barge_aec_baseline_missing')
    deltas={key:after[key]-before[key] for key in ('aec_frames','aec_reference_frames')}
    if any(value<=0 for value in deltas.values()):
        raise ValueError('barge_aec_no_new_processing_or_reference')
    if not 0<after['aec_process_max_us']<32000:
        raise ValueError('barge_aec_exceeded_frame_time')
    if after['audio_input_stack_hwm_bytes']<512:
        raise ValueError('barge_aec_input_stack_margin_low')
    return {'aec_ready':True, **{key:after[key] for key in keys},
            'new_aec_frames':deltas['aec_frames'],
            'new_reference_frames':deltas['aec_reference_frames'],
            'frame_duration_us':32000,'minimum_required_stack_margin_bytes':512,
            'human_wake_or_echo_rejection_accepted':False}


def expected_close_reason(*,unmute_requested,stopping,sent_code,received_code,
                          received_before_sent=None):
    # An explicit peer error never becomes success because local cleanup also
    # sent a normal close. Early unsolicited clean closes are failures too.
    if received_code not in (None,1000,1001):return None
    if unmute_requested:return 'expected_unmute_disconnect'
    if stopping and sent_code==1001 and received_before_sent is not True:
        return 'expected_fixture_shutdown'
    return None


async def run(args):
    if not args.execute:raise ValueError('explicit_execute_required_for_local_physical_sound')
    if not 20<=args.seconds<=180:raise ValueError('bounded_fixture_duration_required')
    config=json.loads(args.config.read_text(encoding='utf-8'))
    if config.get('port')!=18789 or config.get('brain_url')!='http://127.0.0.1:18781':
        raise ValueError('existing_gateway_config_required')
    report={'level':'HARDWARE_FIXTURE','real_provider_calls':0,'raw_audio_saved':False,
        'text_saved':False,'acoustic_or_human_acceptance':False,'synthetic_tone_hz':440,
        'empty_fixture_transports':0,'fixture_pcm24_samples':0,'actual_wake_events':0,
        'playback_started':[],'whole_playback_finished':[],'segments_finished':[],
        'capture_floors':[],'connections':[],'steps':[],'errors':[]}
    require_aec=getattr(args,'require_barge_aec',False)
    report['barge_aec_required']=require_aec
    active=False
    first=True
    stopping=False
    unmute_from_epoch=None
    deadline=time.monotonic()+args.seconds
    async def handler(ws):
        nonlocal active,first
        if ws.request.path!='/xiaozhi/v1/' or not authorize(ws.request.headers,config):
            await ws.close(1008,'enrolled_fixture_device_required');return
        if active:await ws.close(1013,'one_fixture_device');return
        active=True
        brain=FixtureBrain(report)
        fixture_config={**config,'unified_voice':{**config.get('unified_voice',{}),
                                                'enabled':True,'lan_stream_consent':True}}
        connection=SophiaConnection(fixture_config,'',session_id='hardware-fixture-'+uuid4().hex,
            conversation_id='hardware-fixture',encoder_factory=OpusOutput,
            connector=lambda *a,**kw:brain)
        tasks=[]
        record={};report['connections'].append(record)
        async def scenario():
            nonlocal first,unmute_from_epoch
            # Absolute sample_start may already be nonzero. Count actual decoded
            # frames to prove new capture, rather than only a large clock value.
            await wait_until(lambda:connection.cloud_ready.is_set() and
                             connection.stats['received_packets']>=17,15)
            record['stream_epoch']=connection.ring.epoch
            record['capture_started']=True
            await connection.screen('ready','Локальная проверка динамика. Без облака.')
            if not first:
                if unmute_from_epoch and connection.ring.epoch!=unmute_from_epoch:
                    report['steps'].append('unmute_fresh_capture_confirmed')
                return
            first=False
            if require_aec:
                await wait_until(lambda:connection.stats.get('device_resources',{}).get('aec_ready') is True and
                    all(type(connection.stats['device_resources'].get(key)) is int for key in
                        ('aec_frames','aec_reference_frames')),8)
            aec_before=dict(connection.stats.get('device_resources',{}))
            await brain.sound('hardware-whole')
            await wait_until(lambda:'hardware-whole' in report['whole_playback_finished'])
            report['steps'].append('whole_response_dma_receipt')
            if 'hardware-whole:0' not in report['segments_finished']:
                raise ValueError('physical_segment_receipt_missing')
            if connection.forward:raise ValueError('input_open_before_guard')
            if require_aec:
                # Firmware stats are periodic. Wait for the completed real DSP
                # work to be reported; this delay is confined to this fixture.
                await wait_until(lambda:all(connection.stats.get('device_resources',{}).get(key,0)>
                    aec_before[key] for key in ('aec_frames','aec_reference_frames')),8)
                report['barge_aec']=barge_aec_evidence(aec_before,connection.stats['device_resources'])
                report['steps'].append('barge_aec_hardware_reference_processed')
            await asyncio.sleep(.2)
            brain.emit('followup',mode='fast')
            await wait_until(lambda:brain.bytes_received>=48000)
            brain.emit('followup_closed')
            report['steps'].append('post_receipt_guard_then_real_capture')
            producer=asyncio.create_task(brain.sound('hardware-cancel',3))
            await wait_until(lambda:any(x['response_id']=='hardware-cancel' for x in report['playback_started']))
            await asyncio.sleep(.12)
            brain.cancelled.add('hardware-cancel');producer.cancel()
            await asyncio.gather(producer,return_exceptions=True)
            cancel_epoch=connection.output_epoch
            brain.emit('audio_cancel',response_id='hardware-cancel')
            await wait_until(lambda:connection.output is None,4)
            if (connection.output_epoch!=cancel_epoch+1 or
                    'hardware-cancel' in report['whole_playback_finished'] or connection.forward):
                raise ValueError('cancel_not_confirmed_or_followup_opened')
            report['steps'].append('cancel_dma_receipt')
            brain.emit('muted',muted=True)
            try:
                await wait_until(lambda:connection.muted,2)
                await asyncio.sleep(1)
                count=connection.stats['received_packets']
                await asyncio.sleep(2)
                if connection.stats['received_packets']!=count:raise ValueError('muted_microphone_still_streaming')
                report['steps'].append('mute_stops_capture')
            finally:
                # The fixture started from confirmed active capture (unmuted).
                # Request its restoration even if the mute assertion fails.
                record['unmute_requested']=True
                unmute_from_epoch=connection.ring.epoch
                brain.emit('muted',muted=False)
                report['steps'].append('unmute_requested_fresh_epoch')
                await wait_until(lambda:not connection.muted,2)
        try:
            hello=json.loads(await asyncio.wait_for(ws.recv(),8))
            task=asyncio.create_task(connection.run(ws,hello,validate_hello));tasks.append(task)
            steps=asyncio.create_task(scenario());tasks.append(steps)
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            if steps in done:
                steps.result()
                await task
            else:task.result()
        except ConnectionClosed as error:
            record['close_sent_code']=error.sent.code if error.sent else None
            record['close_received_code']=error.rcvd.code if error.rcvd else None
            record['close_received_before_sent']=error.rcvd_then_sent
            record['fixture_deadline_reached']=stopping
            # ESP unmute deliberately destroys the old websocket without a
            # goodbye frame. This alone is NOT a reconnect PASS: the next
            # authenticated epoch must deliver real capture frames below.
            reason=expected_close_reason(unmute_requested=record.get('unmute_requested',False),
                stopping=stopping,sent_code=record['close_sent_code'],
                received_code=record['close_received_code'],
                received_before_sent=record['close_received_before_sent'])
            if reason:
                # The finite server initiated its own deadline shutdown. ESP
                # closes TCP without a websocket reply, even when the sent
                # close frame was normal. An earlier/unsolicited loss still
                # fails; record both codes rather than treating all 1006 as OK.
                record[reason]=True
            else:
                report['errors'].append('unexpected_device_disconnect')
        except Exception as error:
            report['errors'].append(type(error).__name__+':'+str(error)[:100])
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            record['stats']=dict(connection.stats)
            record['events']=list(connection.events)
            active=False
            with suppress(Exception):await ws.close()
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version=ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.config.parent/'server.pem',args.config.parent/'server.key')
    print(json.dumps({'fixture':'started','port':18789,'seconds':args.seconds,'provider_calls':0}),flush=True)
    async with serve(handler,config['bind'],18789,ssl=tls,max_size=16384,max_queue=8,
                     ping_interval=20,ping_timeout=10,close_timeout=2,compression=None):
        while time.monotonic()<deadline:await asyncio.sleep(.2)
        stopping=True
    report['distinct_capture_epochs']=len({x.get('stream_epoch') for x in report['connections'] if x.get('stream_epoch')})
    report['pass']=all(step in report['steps'] for step in (
        'whole_response_dma_receipt','post_receipt_guard_then_real_capture',
        'cancel_dma_receipt','mute_stops_capture','unmute_fresh_capture_confirmed')) and report['distinct_capture_epochs']>=2 and not report['errors']
    if require_aec:
        report['pass']=report['pass'] and 'barge_aec_hardware_reference_processed' in report['steps']
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='connections'}),flush=True)
    return 0 if report['pass'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'data/hardware/gobot-v1/gateway.json')
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=45)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--require-barge-aec',action='store_true',
        help='Require real AEC/reference processing and input-task margin during the quiet tone.')
    raise SystemExit(asyncio.run(run(parser.parse_args())))

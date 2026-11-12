"""Loopback-only LiveKit media relay. Existing Brain owns provider sessions and tools."""
import asyncio
import time
from urllib.parse import urlsplit

import jwt
from livekit import rtc
from aiortc import AudioStreamTrack
import av
import numpy as np
from fractions import Fraction

class RelayInput(AudioStreamTrack):
    def __init__(self, queue):
        super().__init__()
        self.queue=queue
        self.position=0
        self.started=asyncio.Event()
    async def recv(self):
        self.started.set()
        pcm=await asyncio.wait_for(self.queue.get(),5)
        frame=av.AudioFrame.from_ndarray(np.frombuffer(pcm,"<i2").reshape(1,-1),format="s16",layout="mono")
        frame.sample_rate=16000;frame.pts=self.position;frame.time_base=Fraction(1,16000)
        self.position+=len(pcm)//2
        return frame

class LocalMediaRelay:
    def __init__(self, settings, operation_id):
        uri=urlsplit(settings["url"])
        if (uri.scheme,uri.hostname,uri.port)!=("ws","127.0.0.1",17880):
            raise ValueError("livekit_loopback_required")
        self.settings=settings
        self.room_name="gobot-"+operation_id
        self.device_id="device-"+operation_id
        self.brain_id="brain-"+operation_id
        self.device,self.brain=rtc.Room(),rtc.Room()
        self.input_queue=asyncio.Queue(maxsize=25)
        self.output_queue=asyncio.Queue(maxsize=25)
        self.input_track=RelayInput(self.input_queue)
        self.tasks=[]
        self.streams=[]
        self.sources=[]
        self.ready=[asyncio.Event(),asyncio.Event()]
        self.counts={"input_frames":0,"output_frames":0}
        self.error=asyncio.get_running_loop().create_future()
        self.closed=False
        self.microphone_active=False
        self.speaker_active=False
        self.speaker_until=0.
        self.pre_source_frames=0
    def token(self,identity):
        now=int(time.time())
        return jwt.encode({"iss":self.settings["key"],"sub":identity,"nbf":now-3,"exp":now+240,
             "video":{"roomJoin":True,"room":self.room_name,"canPublish":True,
                      "canSubscribe":True,"canPublishData":False}} ,self.settings["secret"],algorithm="HS256")
    def task(self,coroutine):
        task=asyncio.create_task(coroutine)
        self.tasks.append(task)
        def done(t):
            if not t.cancelled() and t.exception() and not self.error.done():
                self.error.set_exception(t.exception())
        task.add_done_callback(done)
        return task
    async def connect(self):
        def subscribe(room, expected, name, queue, index, rate):
            @room.on("track_subscribed")
            def subscribed(track,publication,participant):
                if participant.identity!=expected or publication.name!=name or track.kind!=rtc.TrackKind.KIND_AUDIO:
                    return
                self.ready[index].set()
                stream=rtc.AudioStream(track,sample_rate=rate,num_channels=1,capacity=25,frame_size_ms=20)
                self.streams.append(stream)
                self.task(self.consume(stream,queue,"input_frames" if index==0 else "output_frames"))
        subscribe(self.brain,self.device_id,"mic",self.input_queue,0,16000)
        subscribe(self.device,self.brain_id,"speaker",self.output_queue,1,24000)
        await self.device.connect(self.settings["url"],self.token(self.device_id),rtc.RoomOptions(connect_timeout=8))
        await self.brain.connect(self.settings["url"],self.token(self.brain_id),rtc.RoomOptions(connect_timeout=8))
        self.mic=rtc.AudioSource(16000,1,queue_size_ms=100)
        self.speaker=rtc.AudioSource(24000,1,queue_size_ms=100)
        self.sources=[self.mic,self.speaker]
        for room,source,name in ((self.device,self.mic,"mic"),(self.brain,self.speaker,"speaker")):
            track=rtc.LocalAudioTrack.create_audio_track(name,source)
            options=rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            await room.local_participant.publish_track(track,options)
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in self.ready)),8)
    async def consume(self,stream,queue,counter):
        async for item in stream:
            if ((counter=="input_frames" and not self.microphone_active)
                    or (counter=="output_frames" and (not self.speaker_active
                        or asyncio.get_running_loop().time()>self.speaker_until))):
                # A subscribed Opus track can produce comfort noise before its AudioSource
                # has received any microphone PCM. It must not fill the question queue
                # while the provider's SDP/sideband handshake is in progress.
                self.pre_source_frames+=1
                continue
            queue.put_nowait(bytes(item.frame.data))
            self.counts[counter]+=1
        if not self.closed:
            raise ConnectionError("livekit_media_track_closed")
    async def microphone(self,capture,*,wait_for_transport=False):
        if wait_for_transport:
            await asyncio.wait_for(self.input_track.started.wait(),5)
        self.microphone_active=True
        while True:
            frame=await capture.recv()
            pcm=frame.to_ndarray().astype("<i2",copy=False).tobytes()
            await self.send_microphone(pcm)
    async def send_microphone(self,pcm):
        self.microphone_active=True
        await self.mic.capture_frame(rtc.AudioFrame(pcm,16000,1,len(pcm)//2))
    async def send_speaker(self,pcm):
        self.speaker_active=True
        # The remote Opus track keeps producing concealment/silence after the real
        # provider stops sending. Do not keep the device's playback/idle alive with
        # those frames. Allow the source's bounded queue plus local codec transit.
        self.speaker_until=asyncio.get_running_loop().time()+self.speaker.queued_duration+len(pcm)/48000+.15
        await self.speaker.capture_frame(rtc.AudioFrame(pcm,24000,1,len(pcm)//2))
    async def output(self,consumer):
        while True:
            pcm=await self.output_queue.get()
            await consumer(pcm)
    async def close(self):
        self.closed=True
        for t in self.tasks:t.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        for stream in self.streams:await stream.aclose()
        for source in self.sources:await source.aclose()
        await self.device.disconnect()
        await self.brain.disconnect()
        self.input_track.stop()
        if self.error.done() and not self.error.cancelled():
            self.error.exception()

/* A local PCM copy for existing ECAPA, never a second STT. No recordings on disk. */
window.GoBotRealtimeSpeaker=class {
  constructor(client){this.client=client;this.ready=false;this.parts=[];this.ring=[];this.bytes=0;this.segment=null;this.active=false;}
  async attach(context,stream){
    await context.audioWorklet.addModule('/pcm-worklet.js');
    this.source=context.createMediaStreamSource(stream);
    this.node=new AudioWorkletNode(context,'gobot-pcm-recorder',{processorOptions:{sampleRate:16000}});
    this.mute=context.createGain();this.mute.gain.value=0;
    this.source.connect(this.node);this.node.connect(this.mute).connect(context.destination);
    this.node.port.onmessage=e=>{
      if(!this.ready||!this.active||!e.data.pcm)return;
      const raw=e.data.pcm;
      this.ring.push(raw.slice(0));while(this.ring.reduce((n,x)=>n+x.byteLength,0)>32000)this.ring.shift();
      if(!this.segment)return;
      if(this.bytes+raw.byteLength<=192000){this.parts.push(raw.slice(0));this.bytes+=raw.byteLength;}
      if(this.bytes>=192000)void this.flush();
    };
  }
  begin(segment){if(!this.ready||!segment)return;this.segment=segment;this.parts=this.ring.map(x=>x.slice(0));this.bytes=this.parts.reduce((n,x)=>n+x.byteLength,0);}
  async flush(){
    const segment=this.segment,parts=this.parts;this.segment=null;this.parts=[];this.bytes=0;
    if(!segment||!this.ready)return;
    const size=parts.reduce((n,x)=>n+x.byteLength,0);
    // Report a short segment as unknown; never inherit identity from a long previous turn.
    const data=new Uint8Array(size<96000?0:size);let at=0;if(data.length)for(const part of parts){data.set(new Uint8Array(part),at);at+=part.byteLength;}
    const session=this.client.id;
    try{await this.client.fetcher('/api/'+(this.client.apiBase||'realtime')+'/sessions/'+session+'/speaker?'+new URLSearchParams({segment_id:segment}),{method:'POST',headers:{'Content-Type':'audio/pcm;rate=16000'},body:data,signal:this.client.abort?.signal});}
    catch(_){}finally{data.fill(0);parts.length=0;}
  }
  close(){this.active=false;this.ready=false;this.parts=[];this.ring=[];this.bytes=0;this.segment=null;if(this.node)this.node.port.onmessage=null;this.source?.disconnect();this.node?.disconnect();this.mute?.disconnect();}
};

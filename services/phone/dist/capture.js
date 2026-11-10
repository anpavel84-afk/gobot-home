// Shared microphone implementation for conversation and family enrollment.
'use strict';
window.GoBotCapture={
  active:null,pending:false,
  async start({context,onChunk,onStop,onError,maxMs=60000,signal,minDurationMs=0,minSpeechMs=0,onInputClosed,vad,onSilence,onVoiceStart}){
    if(this.active||this.pending)throw new Error('Микрофон уже записывает.');
    if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw new Error('Микрофон требует доверенного HTTPS.');
    this.pending=true;
    let stream;
    try{stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});}
    catch(error){this.pending=false;throw error;}
    if(signal?.aborted){stream.getTracks().forEach(t=>t.stop());this.pending=false;throw new DOMException('Запись отменена','AbortError');}
    let stop,timer,node,source,mute,recorder,meter,meterSource,meterTimer,speechMs=0,done=false,finishing=false;
    const started=performance.now();let previous=started,abort,closedAt=null;
    const gate=vad?new this.PCMVoiceGate(vad):null;
    const cleanup=()=>{clearTimeout(timer);clearInterval(meterTimer);signal?.removeEventListener('abort',abort);stream.getTracks().forEach(t=>t.stop());source?.disconnect();meterSource?.disconnect();node?.disconnect();mute?.disconnect();this.active=null;this.pending=false;};
    const finish=blob=>{if(done)return;done=true;const duration=performance.now()-started;cleanup();if(duration<minDurationMs||speechMs<minSpeechMs){onError?.(new Error('Слишком короткая или тихая запись. Удерживай экран и произнеси вопрос.'));return;}onStop?.(blob,{input_closed_at:closedAt??performance.now(),audio_seconds:gate&&blob?(blob.size-44)/48000:((closedAt??performance.now())-started)/1000});};
    try{
      if(minSpeechMs>0&&!gate){
        if(!context?.createAnalyser)throw Error('Не удалось включить локальную проверку записи.');
        meter=context.createAnalyser();meter.fftSize=512;meterSource=context.createMediaStreamSource(stream);meterSource.connect(meter);const samples=new Uint8Array(meter.fftSize);
        meterTimer=setInterval(()=>{meter.getByteTimeDomainData(samples);const now=performance.now(),rms=Math.sqrt(samples.reduce((s,v)=>s+((v-128)/128)**2,0)/samples.length);if(rms>.012)speechMs+=Math.min(now-previous,100);previous=now;},30);
      }
      if(onChunk||gate){
        await context.audioWorklet.addModule('/pcm-worklet.js');await context.resume();
        source=context.createMediaStreamSource(stream);node=new AudioWorkletNode(context,'gobot-pcm-recorder');mute=context.createGain();mute.gain.value=0;
        node.port.onmessage=e=>{
          if(done)return;
          if(e.data.pcm){
            if(gate){
              const previous=gate.started,result=gate.push(e.data.pcm);
              speechMs=gate.speechMs;
              if(!previous&&gate.started)onVoiceStart?.();
              if(result==='silence'){this.active?.cancel();onSilence?.();return;}
              if(result==='end')this.active?.stop();
            }else onChunk(e.data.pcm);
          }
          if(e.data.end)finish(gate?gate.wav():null);
        };
        source.connect(node);node.connect(mute).connect(context.destination);
        stop=()=>{if(finishing)return;finishing=true;node.port.postMessage('stop');};
      }else{
        const mime=['audio/webm;codecs=opus','audio/mp4','audio/webm','audio/ogg;codecs=opus'].find(x=>MediaRecorder.isTypeSupported(x));
        if(!mime)throw new Error('Формат записи браузера не поддерживается.');
        const parts=[];let bytes=0;recorder=new MediaRecorder(stream,{mimeType:mime});
        recorder.ondataavailable=e=>{parts.push(e.data);bytes+=e.data.size;if(bytes>8*1024*1024)stop();};
        recorder.onstop=()=>{if(done)return;if(bytes>8*1024*1024){done=true;cleanup();onError?.(new Error('Запись больше 8 MB.'));return;}finish(new Blob(parts,{type:mime}));};
        recorder.onerror=()=>{if(done)return;done=true;cleanup();onError?.(new Error('Ошибка микрофона.'));};
        stop=()=>{if(recorder.state==='recording')recorder.stop();};recorder.start(250);
      }
      const handle={stop:()=>{if(done||closedAt!==null)return;closedAt=performance.now();const accepted=closedAt-started>=minDurationMs&&speechMs>=minSpeechMs;stop();stream.getTracks().forEach(t=>t.stop());if(accepted)onInputClosed?.({input_closed_at:closedAt,audio_seconds:(closedAt-started)/1000});},cancel:()=>{if(done)return;done=true;cleanup();if(recorder?.state==='recording')recorder.stop();}};
      abort=()=>handle.cancel();signal?.addEventListener('abort',abort,{once:true});
      if(signal?.aborted){handle.cancel();throw new DOMException('Запись отменена','AbortError');}
      for(const track of stream.getAudioTracks())track.addEventListener('ended',()=>{if(!done&&closedAt===null){handle.cancel();onError?.(new Error('Микрофон был прерван браузером. Включи GoBot снова.'));}},{once:true});
      for(const track of stream.getAudioTracks())track.addEventListener('mute',()=>{if(!done&&closedAt===null){handle.cancel();onError?.(new Error('Микрофон приостановлен браузером. Возобнови GoBot.'));}},{once:true});
      this.active=handle;this.pending=false;timer=setTimeout(()=>handle.stop(),maxMs);return handle;
    }catch(error){cleanup();throw error;}
  }
};

// Bounded energy/spectral gate for an active-page prototype. No cloud processing.
window.GoBotCapture.PCMVoiceGate=class{
  constructor({windowMs=12000,silenceMs=900,minSpeechMs=300}={}){
    Object.assign(this,{windowMs,silenceMs,minSpeechMs});
    this.elapsed=0;this.speechMs=0;this.quiet=0;this.started=false;this.noise=.003;
    this.ring=[];this.parts=[];this.ringMs=0;
  }
  push(raw){
    const pcm=new Int16Array(raw),ms=pcm.length/24;
    let sum=0,crossings=0;
    for(let i=0;i<pcm.length;i++){sum+=(pcm[i]/32768)**2;if(i&&pcm[i]*pcm[i-1]<0)crossings++;}
    const rms=Math.sqrt(sum/Math.max(1,pcm.length));
    const speech=rms>Math.max(.012,this.noise*2.8)&&crossings/Math.max(1,pcm.length)<.35;
    this.elapsed+=ms;
    if(!this.started){
      this.ring.push(raw.slice(0));this.ringMs+=ms;
      while(this.ringMs>1000&&this.ring.length>1)this.ringMs-=this.ring.shift().byteLength/48;
      if(speech){this.speechMs+=ms;this.quiet=0;}else{this.speechMs=0;this.noise=.95*this.noise+.05*Math.min(rms,.01);}
      if(this.speechMs>=this.minSpeechMs){this.started=true;this.parts=this.ring;this.ring=[];}
      else if(this.elapsed>=this.windowMs&&!this.speechMs){this.ring=[];return 'silence';}
    }else{
      this.parts.push(raw.slice(0));
      if(speech){this.speechMs+=ms;this.quiet=0;}else this.quiet+=ms;
      if(this.quiet>=this.silenceMs)return 'end';
    }
    return 'continue';
  }
  wav(){
    const bytes=this.parts.reduce((n,p)=>n+p.byteLength,0),raw=new ArrayBuffer(44+bytes),view=new DataView(raw);
    const word=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
    word(0,'RIFF');view.setUint32(4,36+bytes,true);word(8,'WAVE');word(12,'fmt ');
    view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
    view.setUint32(24,24000,true);view.setUint32(28,48000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);
    word(36,'data');view.setUint32(40,bytes,true);let offset=44;
    for(const part of this.parts){new Uint8Array(raw,offset,part.byteLength).set(new Uint8Array(part));offset+=part.byteLength;}
    this.parts=[];this.ring=[];return new Blob([raw],{type:'audio/wav'});
  }
};

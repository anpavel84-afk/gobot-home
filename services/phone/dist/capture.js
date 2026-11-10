// Shared microphone implementation for conversation and family enrollment.
'use strict';
window.GoBotCapture={
  active:null,pending:false,
  async start({context,onChunk,onStop,onError,maxMs=60000,signal,minDurationMs=0,minSpeechMs=0,onInputClosed}){
    if(this.active||this.pending)throw new Error('Микрофон уже записывает.');
    if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw new Error('Микрофон требует доверенного HTTPS.');
    this.pending=true;
    let stream;
    try{stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});}
    catch(error){this.pending=false;throw error;}
    if(signal?.aborted){stream.getTracks().forEach(t=>t.stop());this.pending=false;throw new DOMException('Запись отменена','AbortError');}
    let stop,timer,node,source,mute,recorder,meter,meterSource,meterTimer,speechMs=0,done=false,finishing=false;
    const started=performance.now();let previous=started,abort,closedAt=null;
    const cleanup=()=>{clearTimeout(timer);clearInterval(meterTimer);signal?.removeEventListener('abort',abort);stream.getTracks().forEach(t=>t.stop());source?.disconnect();meterSource?.disconnect();node?.disconnect();mute?.disconnect();this.active=null;this.pending=false;};
    const finish=blob=>{if(done)return;done=true;const duration=performance.now()-started;cleanup();if(duration<minDurationMs||speechMs<minSpeechMs){onError?.(new Error('Слишком короткая или тихая запись. Удерживай экран и произнеси вопрос.'));return;}onStop?.(blob,{input_closed_at:closedAt??performance.now(),audio_seconds:((closedAt??performance.now())-started)/1000});};
    try{
      if(minSpeechMs>0){
        if(!context?.createAnalyser)throw Error('Не удалось включить локальную проверку записи.');
        meter=context.createAnalyser();meter.fftSize=512;meterSource=context.createMediaStreamSource(stream);meterSource.connect(meter);const samples=new Uint8Array(meter.fftSize);
        meterTimer=setInterval(()=>{meter.getByteTimeDomainData(samples);const now=performance.now(),rms=Math.sqrt(samples.reduce((s,v)=>s+((v-128)/128)**2,0)/samples.length);if(rms>.012)speechMs+=Math.min(now-previous,100);previous=now;},30);
      }
      if(onChunk){
        await context.audioWorklet.addModule('/pcm-worklet.js');await context.resume();
        source=context.createMediaStreamSource(stream);node=new AudioWorkletNode(context,'gobot-pcm-recorder');mute=context.createGain();mute.gain.value=0;
        node.port.onmessage=e=>{if(e.data.pcm)onChunk(e.data.pcm);if(e.data.end)finish(null);};
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
      for(const track of stream.getAudioTracks())track.addEventListener('ended',()=>{if(!done){handle.cancel();onError?.(new Error('Микрофон был прерван браузером. Включи GoBot снова.'));}},{once:true});
      for(const track of stream.getAudioTracks())track.addEventListener('mute',()=>{if(!done){handle.cancel();onError?.(new Error('Микрофон приостановлен браузером. Возобнови GoBot.'));}},{once:true});
      this.active=handle;this.pending=false;timer=setTimeout(()=>handle.stop(),maxMs);return handle;
    }catch(error){cleanup();throw error;}
  }
};

// Shared microphone implementation for conversation and family enrollment.
'use strict';
window.GoBotCapture={
  active:null,pending:false,
  async start({context,onChunk,onStop,onError,maxMs=60000}){
    if(this.active||this.pending)throw new Error('Микрофон уже записывает.');
    if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw new Error('Микрофон требует доверенного HTTPS.');
    this.pending=true;
    let stream;
    try{stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});}
    catch(error){this.pending=false;throw error;}
    let stop,timer,node,source,mute,recorder,done=false,finishing=false;
    const cleanup=()=>{clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());source?.disconnect();node?.disconnect();mute?.disconnect();this.active=null;this.pending=false;};
    const finish=blob=>{if(done)return;done=true;cleanup();onStop?.(blob);};
    try{
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
        recorder.onstop=()=>{if(bytes>8*1024*1024){cleanup();onError?.(new Error('Запись больше 8 MB.'));return;}finish(new Blob(parts,{type:mime}));};
        recorder.onerror=()=>{cleanup();onError?.(new Error('Ошибка микрофона.'));};
        stop=()=>{if(recorder.state==='recording')recorder.stop();};recorder.start(250);
      }
      const handle={stop:()=>stop(),cancel:()=>{done=true;cleanup();if(recorder?.state==='recording')recorder.stop();}};
      this.active=handle;this.pending=false;timer=setTimeout(()=>handle.stop(),maxMs);return handle;
    }catch(error){cleanup();throw error;}
  }
};

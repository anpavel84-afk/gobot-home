class PCMRecorder extends AudioWorkletProcessor {
  constructor(){super();this.tail=[];this.position=0;this.pending=[];this.stopped=false;this.port.onmessage=e=>{if(e.data==='stop'){this.stopped=true;this.flush();this.port.postMessage({end:true});}};}
  flush(){if(!this.pending.length)return;const out=new Int16Array(this.pending);this.pending=[];this.port.postMessage({pcm:out.buffer},[out.buffer]);}
  process(inputs){
    if(this.stopped)return true;const channel=inputs[0]?.[0];if(!channel)return true;
    const input=this.tail.concat(Array.from(channel)), step=sampleRate/24000;
    while(this.position+1<input.length){const i=Math.floor(this.position),fraction=this.position-i;
      const value=Math.max(-1,Math.min(1,input[i]*(1-fraction)+input[i+1]*fraction));this.pending.push(Math.round(value*32767));this.position+=step;
      if(this.pending.length>=2400)this.flush();
    }
    const consumed=Math.floor(this.position);this.tail=input.slice(consumed);this.position-=consumed;return true;
  }
}
registerProcessor('gobot-pcm-recorder',PCMRecorder);

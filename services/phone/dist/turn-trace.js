/* One client monotonic clock. Output start is estimated, never acoustic proof. */
(() => {
  'use strict';
  class TurnTrace {
    constructor(id,clock=()=>performance.now()){this.id=id;this.clock=clock;this.t0=null;this.events=[];this.complete=false;this.revision=0;}
    inputClosed(at=this.clock()){if(this.t0===null){this.t0=at;this.mark('input_closed',at);}return this;}
    mark(name,at=this.clock()){if(this.t0===null||this.events.some(e=>e.name===name))return;this.events.push({name,ms:Math.max(0,at-this.t0)});}
    playbackFinished(flush=true){this.events=this.events.filter(e=>e.name!=='playback_complete');this.mark('playback_complete');if(flush)this.flush();}
    snapshot(){return {trace_id:this.id,revision:this.revision,audio_seconds:this.audioSeconds??null,stt_mode:this.sttMode||'text',events:this.events.slice(0,64)};}
    flush(){if(this.t0===null)return;this.revision++;fetch('/api/telemetry/'+encodeURIComponent(this.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(this.snapshot()),keepalive:true}).catch(()=>{});}
  }
  class FeedbackController {
    constructor({play,stop,clock=()=>performance.now(),schedule=(callback,ms)=>setTimeout(callback,ms),clear=id=>clearTimeout(id)}){Object.assign(this,{play,stop,clock,schedule,clear});this.epoch=0;this.timer=null;this.trace=null;this.config={enabled:true,filler_enabled:true,threshold_ms:2250};}
    configure(config){Object.assign(this.config,config);}
    begin(trace){
      this.cancel();this.trace=trace;const epoch=this.epoch;this.ready=false;this.used=false;
      if(!this.config.enabled||this.config.quiet)return;
      this.play('earcon',trace);
      this.timer=this.schedule(()=>{if(epoch!==this.epoch||this.ready||this.used)return;this.used=true;if(this.config.filler_enabled)this.play('filler',trace);},Math.max(0,this.config.threshold_ms-(this.clock()-trace.t0)));
    }
    answerReady(){this.ready=true;this.clear(this.timer);this.timer=null;this.stop(true,this.trace);}
    cancel(){this.epoch++;this.clear(this.timer);this.timer=null;this.stop(false,this.trace);this.trace=null;}
  }
  window.GoBotTiming={TurnTrace,FeedbackController};
})();

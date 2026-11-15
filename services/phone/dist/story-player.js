/* One bounded AudioContext owner for narrator, cached clips and manual TTS. */
(() => {
  'use strict';
  class StoryPlayer {
    constructor({fetchAudio,ack=async()=>{},command=async()=>{},onState=()=>{},onSegment=()=>{}}={}) {
      Object.assign(this,{fetchAudio,ack,command,onState,onSegment});this.run=0;this.job=null;this.index=0;this.offset=0;this.state='idle';this.cache=new Map();this.acks=Promise.resolve();
    }
    stateTo(value){this.state=value;this.onState(value);}
    async unlock(){
      this.context=this.context||new (window.AudioContext||window.webkitAudioContext)();await this.context.resume();
      if(this.context.state!=='running')throw Error('Браузер не разрешил звук. Нажмите воспроизведение ещё раз.');
      if(!this.gain){this.gain=this.context.createGain();this.gain.gain.value=.8;this.meter=this.context.createAnalyser();this.meter.fftSize=256;this.gain.connect(this.meter);this.meter.connect(this.context.destination);}
    }
    async acquire(){
      if(!navigator.locks)throw Error('Безопасное владение звуком недоступно.');
      let signal,release;const acquired=new Promise(r=>signal=r);
      const task=navigator.locks.request('gobot-browser-device-audio',{ifAvailable:true},async lock=>{
        signal(!!lock);if(lock)await new Promise(r=>release=r);
      });
      if(!await acquired)throw Error('Звук занят другой вкладкой или B/C. Сначала завершите её.');
      const unlock=()=>release?.();unlock.done=task;return unlock;
    }
    played(){return this.source?Math.min(this.duration,this.offset+Math.max(0,this.context.currentTime-this.began)):this.offset;}
    sendAck(event,position){
      if(!this.job||this.job.local)return;
      const job=this.job,index=this.index;
      const data={client_id:job.client_id,stream_id:job.id,segment_id:String(index),epoch:job.epoch,event,
        position_seconds:position,precision:'audio_clock',clock_domain:'audio_context'};
      this.acks=this.acks.catch(()=>{}).then(()=>this.ack(job,data));this.acks.catch(error=>{this.ackError=error.message;});return this.acks;
    }
    async play(job,index=0,offset=0){
      if(this.state==='playing'||this.state==='loading')await this.pause();
      this.job=job;this.index=index;this.offset=offset;const token=++this.run;
      this.abort=new AbortController();let release;
      try {
        await this.unlock();release=await this.acquire();this.release=release;
        if(token!==this.run)return;
        if(!job.local)await this.command(job,'play');
        while(this.index<job.segments.length&&token===this.run){
          this.stateTo('loading');const item=job.segments[this.index];this.onSegment(item,this.index);
          const key=job.id+':'+job.epoch+':'+item.id;
          let buffer=this.cache.get(key);
          if(!buffer){const raw=job.local?job.raw:await this.fetchAudio(job,item,this.abort.signal);
            if(token!==this.run)return;buffer=await this.context.decodeAudioData(raw.slice(0));
            if(token!==this.run)return;this.cache.set(key,buffer);
            while(this.cache.size>2)this.cache.delete(this.cache.keys().next().value);
          }
          if(token!==this.run||this.context.state!=='running')return;
          const source=this.context.createBufferSource();source.buffer=buffer;source.connect(this.gain);
          this.source=source;this.duration=buffer.duration;this.offset=Math.min(this.offset,Math.max(0,buffer.duration-.01));this.began=this.context.currentTime;
          this.stateTo('playing');source.start(0,this.offset);this.sendAck('started',this.offset);
          const progress=setInterval(()=>{if(token===this.run)this.sendAck('progress',this.played());},250);
          const complete=await new Promise(resolve=>{source.onended=()=>resolve(token===this.run);});
          clearInterval(progress);source.disconnect();if(this.source===source)this.source=null;
          if(!complete||token!==this.run)return;
          await this.sendAck('drained',buffer.duration);
          if(token!==this.run)return;
          this.index++;this.offset=0;
        }
        if(token===this.run)this.stateTo('finished');
      }catch(error){if(token===this.run&&error.name!=='AbortError'){this.stateTo('blocked');throw error;}}
      finally {release?.();if(this.release===release)this.release=null;if(token===this.run&&this.state==='loading')this.stateTo('paused');}
    }
    async pause(){
      const job=this.job;this.offset=this.played();if(this.source)this.sendAck('interrupted',this.offset);this.run++;
      this.abort?.abort();const source=this.source;this.source=null;
      if(source){try{source.stop();}catch(_){}source.disconnect();}
      const release=this.release;this.release=null;release?.();if(release?.done)await release.done;
      this.stateTo('paused');if(job&&!job.local)await this.command(job,'pause');
    }
    async resume(){
      if(!this.job||this.state==='stopped')throw Error('Нет приостановленного рассказа.');
      return this.play(this.job,this.index,this.offset);
    }
    async stop(){
      const job=this.job;const pending=this.pause(),token=this.run;await pending;
      if(job&&!job.local)await this.command(job,'stop');
      if(token===this.run){this.cache.clear();this.stateTo('stopped');this.job=null;this.index=0;this.offset=0;}
    }
    async playOne(raw){
      const saved=this.job&&!this.job.local?{job:this.job,index:this.index,offset:this.played()}:null;
      if(saved)await this.pause();
      try{await this.play({local:true,id:'one-'+crypto.randomUUID(),epoch:1,segments:[{id:'0',text:''}],raw});}
      finally{if(saved&&this.state==='finished'){Object.assign(this,saved);this.stateTo('paused');}}
    }
    snapshot(){
      let level=0;if(this.meter&&this.state==='playing'){const a=new Uint8Array(this.meter.fftSize);this.meter.getByteTimeDomainData(a);level=Math.sqrt(a.reduce((n,v)=>n+((v-128)/128)**2,0)/a.length);}
      return {playing:this.state==='playing',level,state:this.context?.state||'closed',position:this.played(),segment:this.index};
    }
  }
  window.GoBotStoryPlayer=StoryPlayer;
})();

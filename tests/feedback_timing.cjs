// Deterministic races, not an iPhone timing claim.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let now=0,id=0;const jobs=new Map(),played=[],stopped=[];
// Browser Window timer APIs reject a foreign receiver. Arrow mocks hid this bug.
const env={window:{},performance:{now:()=>now},setTimeout:function(f,ms){assert.notEqual(this?.constructor?.name,'FeedbackController','Illegal invocation: foreign timer receiver');jobs.set(++id,{f,at:now+ms});return id;},clearTimeout:function(i){assert.notEqual(this?.constructor?.name,'FeedbackController','Illegal invocation: foreign timer receiver');jobs.delete(i);},fetch:async()=>({})};
vm.createContext(env);vm.runInContext(fs.readFileSync('services/phone/dist/turn-trace.js','utf8'),env);
const {TurnTrace,FeedbackController}=env.window.GoBotTiming;
const advance=t=>{now=t;for(const [i,job] of [...jobs])if(job.at<=now){jobs.delete(i);job.f();}};
const gate=new FeedbackController({play:(role,trace)=>{played.push(role);trace.mark(role==='earcon'?'earcon_started':'filler_started');},stop:(fade,trace)=>stopped.push(fade)});
let trace=new TurnTrace('synthetic-1').inputClosed();gate.begin(trace);gate.offer({id:'cached-fixture'},trace);assert.equal(played.join(','),'earcon');advance(2249);assert(!played.includes('filler'));advance(2250);assert.equal(played.filter(x=>x==='filler').length,1);advance(10000);assert.equal(played.filter(x=>x==='filler').length,1);
gate.answerReady();assert(stopped.includes(true));assert(!trace.events.some(e=>e.name==='first_answer_playback'));
trace=new TurnTrace('synthetic-2').inputClosed();gate.begin(trace);const count=played.length;advance(now+2200);gate.answerReady();advance(now+500);assert.equal(played.length,count);
for(const reason of ['cancel','profile-change','reconnect','hidden','early-error']){trace=new TurnTrace(reason).inputClosed();gate.begin(trace);const count=played.length;gate.cancel();advance(now+5000);assert.equal(played.length,count);}
gate.configure({quiet:true});const quietCount=played.length;gate.begin(new TurnTrace('quiet').inputClosed());advance(now+5000);assert.equal(played.length,quietCount);
gate.configure({quiet:false,enabled:false});gate.begin(new TurnTrace('muted').inputClosed());advance(now+5000);assert.equal(played.length,quietCount);
const timed=new TurnTrace('useful').inputClosed();timed.mark('earcon_started');advance(now+9000);timed.mark('first_answer_playback');assert.equal(timed.events.find(e=>e.name==='first_answer_playback').ms,9000);
trace=new TurnTrace('no-clip').inputClosed();gate.configure({enabled:true,quiet:false});gate.begin(trace);const noClip=played.length;advance(now+3000);assert.equal(played.length,noClip);gate.offer({id:'late-ready'},trace);assert.equal(played.length,noClip+1);gate.offer({id:'repeat'},trace);assert.equal(played.length,noClip+1);gate.cancel();
console.log('Feedback fixtures: threshold, once, TTS preemption, quiet, error, cancellation, epoch/reconnect and TTFA roles passed');

"""Public-data-only full Russian-reference MixedNet training; bounded CPU job.

Architecture from interkelstar/microwakeword-trainer example_ru_jarvis.yaml
at8fdbadc3b969a8c1993108c0d655910440dfb762. Target is Russian GoBot only.
Counts below are augmented feature windows, NOT distinct TTS voices/recordings.
No human recording, owner path, paid service or network is read by this script.
"""
import os
os.environ['TF_NUM_INTRAOP_THREADS']='2';os.environ['TF_NUM_INTEROP_THREADS']='2';os.environ['OPENBLAS_NUM_THREADS']='1'
import argparse,hashlib,json,time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import tensorflow as tf
from scipy.signal import lfilter
from pymicro_features import MicroFrontend
from microwakeword.mixednet import model
from microwakeword.layers.modes import Modes
from microwakeword.utils import to_streaming_inference
from augmentation import fit_positive,trim_background,place_keyword

SEED=20261114
FRAMES=204
BATCH=128
TRAIN=('denis','dmitri','espeak-ru','anna')
VALIDATION=('aleksandr',)
TEST=('elena',)
TAIL_SAMPLES=3200
WORD_ANCHORED=False

def files(root,speakers,expected_counts=(198,15),keyword_only=False):
    groups={0:[],1:[]}
    for speaker in speakers:
        directory=root/speaker
        entries=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        counts={0:0,1:0};seen=set();kept_positive=0
        for item in entries:
            name=item['file'];label={'negative':0,'positive':1}.get(item.get('label'))
            if Path(name).name!=name or name in seen or item.get('speaker')!=speaker or not item.get('synthetic') or label is None:
                raise ValueError('Invalid public synthetic manifest')
            path=directory/name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Synthetic PCM hash mismatch')
            seen.add(name);counts[label]+=1
            if not (keyword_only and label==1 and ',' in item.get('text','')):
                groups[label].append(np.fromfile(path,'<i2'))
                if label:kept_positive+=1
        if counts!={0:expected_counts[0],1:expected_counts[1]}:raise ValueError('Incomplete public speaker')
        if keyword_only and kept_positive!=15:raise ValueError('Unexpected isolated-name inventory')
    return groups

def features(pcm):
    front=MicroFrontend();rows=[]
    for i in range(0,len(pcm)-159,160):
        result=front.process_samples(pcm[i:i+160].astype('<i2').tobytes())
        if result.samples_read!=160:raise ValueError('Frontend lost input')
        if result.features:rows.append(result.features)
    return np.asarray(rows,np.float32)

def window(clip,rng,positive,following=None):
    raw=np.zeros(0) if clip is None else clip.astype(float)
    raw=trim_background(raw,retain_full=positive)
    speed=rng.uniform(.72,1.35)
    if len(raw):raw=np.interp(np.arange(0,len(raw),speed),np.arange(len(raw)),raw)
    delay=int(rng.integers(160,2880));raw=np.pad(raw,(0,delay))+rng.uniform(0,.4)*np.pad(raw,(delay,0))
    filt=rng.uniform(0,.6);raw=lfilter([1-filt],[1,-filt],raw)*rng.uniform(.2,4.)
    total=(FRAMES+2)*160
    if len(raw)>total:
        if positive:raw=fit_positive(raw,total)
        else:
            start=int(rng.integers(0,len(raw)-total+1));raw=raw[start:start+total]
    signal_rms=float(np.sqrt(np.mean(raw*raw)))
    floor=float(rng.uniform(0,1200))
    if clip is not None:floor=min(floor,max(30,signal_rms/1.8))
    noise=rng.normal(0,floor,total);room_noise=lfilter([.15],[1,-.85],rng.normal(0,floor,total))
    background=noise+room_noise
    if positive and WORD_ANCHORED:
        raw=fit_positive(raw,total-1920)
        end=int(rng.integers(max(len(raw),total-TAIL_SAMPLES),total+1))
        tail=np.zeros(0) if following is None else following.astype(float)
        if len(tail):
            tail=trim_background(tail);rms=max(1.,float(np.sqrt(np.mean(tail*tail))))
            tail=tail*min(4.,max(.1,signal_rms/rms))*float(rng.uniform(.5,1.2))
        background=place_keyword(background,raw,tail,end)
    else:
        gap=total-len(raw);left=int(rng.integers(max(0,gap-TAIL_SAMPLES),gap+1));background[left:left+len(raw)]+=raw
    warm=rng.normal(0,floor,int(rng.integers(50,250))*160)
    return features(np.clip(np.concatenate([warm,background]),-32768,32767))[-FRAMES:]

def prepare(groups,path,count,seed):
    rng=np.random.default_rng(seed);x=np.lib.format.open_memmap(path,mode='w+',dtype=np.float16,shape=(count,FRAMES,40))
    y=np.arange(count,dtype=np.int32)%2;rng.shuffle(y)
    for i,label in enumerate(y):
        candidates=groups[int(label)];clip=candidates[int(rng.integers(len(candidates)))]
        if not label and rng.random()<.15:clip=None
        following=groups[0][int(rng.integers(len(groups[0])))] if WORD_ANCHORED and label and rng.random()<.75 else None
        x[i]=window(clip,rng,bool(label),following)
        if (i+1)%2048==0:print(json.dumps({'prepared_windows':i+1,'total':count}),flush=True)
    x.flush();return x,y.astype(np.float32)

def select_checkpoint(history):
    """An untrained initialization is diagnostic, never an export candidate."""
    trained=[row for row in history if row['step']>0 and np.isfinite(row['validation_bce'])]
    if not trained:raise ValueError('No finite trained checkpoint')
    return min(trained,key=lambda row:row['validation_bce'])

def main(corpus,out,steps=10000,count=50000,reuse_public=None,cache=None,expanded=False,initial_weights=None,initial_sha=None,hard_replay=None,word_anchored=False):
    global TRAIN,TAIL_SAMPLES,WORD_ANCHORED
    WORD_ANCHORED=word_anchored
    if word_anchored and (not expanded or cache or reuse_public):raise ValueError('Word anchoring requires fresh expanded windows')
    if bool(initial_weights)!=bool(initial_sha):raise ValueError('Initial weights require their exact hash')
    if expanded:
        TRAIN=('denis','dmitri','espeak-ru','anna','irina');TAIL_SAMPLES=9600
        if reuse_public or cache:raise ValueError('Expanded profile requires fresh windows')
    if steps not in (1000,10000) or count not in (8192,50000):raise ValueError('Unsupported bounded reference profile')
    if set(TRAIN)&set(VALIDATION+TEST) or set(VALIDATION)&set(TEST):raise ValueError('Speaker leakage')
    out.mkdir(parents=True,exist_ok=True);tf.keras.utils.set_random_seed(SEED);tf.config.experimental.enable_op_determinism()
    config={'architecture':'upstream MixedNet full Russian reference','training_speakers':TRAIN,'validation_speakers':VALIDATION,'test_speakers':TEST,
        'human_training':False,'seed':SEED,'steps':steps,'augmented_windows':count,'context_frames':FRAMES,'batch_size':BATCH,'cpu_threads':2,
        'positive_front_crop':False,'public_tts_positive_seeds':60,'public_tts_negative_seeds':792,'reference_cutoff':231,'window':10,'split_revision':2,
        'reference_source':'interkelstar/microwakeword-trainer@8fdbadc3b969a8c1993108c0d655910440dfb762',
        'pooled':False,'checkpoint_selection':'finite trained validation BCE only',
        'background_only_negative_fraction':.15,'tail_samples':TAIL_SAMPLES}
    if expanded:
        provenance=json.loads((corpus/'provenance.json').read_text())
        if provenance['speakers']!=list(TRAIN) or provenance['synthetic_only'] is not True:raise ValueError('Expanded provenance mismatch')
        config.update(split_revision=3,public_tts_positive_seeds=375,public_tts_negative_seeds=2490,expanded_utterance_corpus=True,
            positive_weight=1.,negative_weight=2.)
        if provenance.get('wake_variants_source'):
            config.update(split_revision=4,wake_variants_source=provenance['wake_variants_source'])
    config['corpus_manifest_sha256']={speaker:hashlib.sha256((corpus/speaker/'manifest.json').read_bytes()).hexdigest() for speaker in (*TRAIN,*VALIDATION,*TEST)}
    if word_anchored:config.update(split_revision=5,word_end_anchored=True,public_tts_positive_seeds=75,following_speech_probability=.75)
    (out/'config.json').write_text(json.dumps(config,indent=2))
    if cache:
        cached_config=json.loads((cache/'config.json').read_text())
        for key in ('training_speakers','validation_speakers','test_speakers','human_training','seed','augmented_windows','context_frames','split_revision'):
            if cached_config.get(key)!=json.loads(json.dumps(config[key])):raise ValueError('Public cache split mismatch: '+key)
        x=np.load(cache/'train-features.npy',mmap_mode='r');y=np.load(cache/'train-labels.npy')
        if x.shape!=(count,FRAMES,40) or x.dtype!=np.float16 or y.shape!=(count,) or set(np.unique(y))!={0.,1.}:raise ValueError('Public cache shape/labels mismatch')
        config['public_cache_source']=cache.name
        config['background_only_negative_fraction']=cached_config.get('background_only_negative_fraction',0)
        with (cache/'train-features.npy').open('rb') as cached:config['public_cache_sha256']=hashlib.file_digest(cached,'sha256').hexdigest()
        (out/'config.json').write_text(json.dumps(config,indent=2))
    elif reuse_public:
        old_config=json.loads((reuse_public/'config.json').read_text())
        if old_config.get('human_training') is not False or old_config.get('training_speakers')!=['denis','dmitri','espeak-ru'] or old_config.get('seed')!=SEED or old_config.get('augmented_windows')!=count:
            raise ValueError('Only the exact public split1 feature cache can be reused')
        original=np.load(reuse_public/'train-features.npy',mmap_mode='r')
        if original.shape!=(count,FRAMES,40) or original.dtype!=np.float16:raise ValueError('Public cache shape mismatch')
        rng=np.random.default_rng(SEED);old_labels=np.arange(count,dtype=np.int32)%2;rng.shuffle(old_labels)
        keep=count*3//4;extra_count=count-keep
        extra,extra_y=prepare(files(corpus,('anna',)),out/'added-voice-features.npy',extra_count,SEED+77)
        x=np.lib.format.open_memmap(out/'train-features.npy',mode='w+',dtype=np.float16,shape=(count,FRAMES,40))
        for start in range(0,keep,1024):x[start:min(start+1024,keep)]=original[start:min(start+1024,keep)]
        x[keep:]=extra;x.flush();y=np.concatenate([old_labels[:keep].astype(np.float32),extra_y])
        with (reuse_public/'train-features.npy').open('rb') as cached:cache_sha=hashlib.file_digest(cached,'sha256').hexdigest()
        config['reused_public_windows']=keep;config['added_voice_windows']=extra_count;config['reused_public_features_sha256']=cache_sha
        config['background_only_negative_fraction']=.15*extra_count/count
        (out/'config.json').write_text(json.dumps(config,indent=2))
        del original,extra
    else:x,y=prepare(files(corpus,TRAIN,(498,75) if expanded else (198,15),keyword_only=word_anchored),out/'train-features.npy',count,SEED)
    if hard_replay:
        manifest=json.loads(hard_replay.with_suffix('.json').read_text())
        if not expanded or manifest.get('synthetic_only') is not True or manifest['training_speakers']!=list(TRAIN) or set(manifest['excluded_speakers'])!=set(VALIDATION+TEST) or hashlib.sha256(hard_replay.read_bytes()).hexdigest()!=manifest['sha256']:raise ValueError('Hard-replay provenance mismatch')
        extra=np.load(hard_replay)
        if extra.ndim!=3 or extra.shape[1:]!=(FRAMES,40) or not 1<=len(extra)<=20000 or not np.isfinite(extra).all():raise ValueError('Invalid hard-negative features')
        x=np.concatenate([x,extra]);y=np.pad(y,(0,len(extra)));config['extra_hard_negative_windows']=len(extra);config['hard_replay_sha256']=manifest['sha256'];config['negative_weight']=4.
        (out/'config.json').write_text(json.dumps(config,indent=2))
    np.save(out/'train-labels.npy',y)
    val,labels=prepare(files(corpus,VALIDATION,(498,75) if expanded else (198,15),keyword_only=word_anchored),out/'validation-features.npy',1024,SEED+1)
    flags=SimpleNamespace(pointwise_filters='64,64,64,64',repeat_in_block='1,1,1,1',mixconv_kernel_sizes='[5],[7,11],[9,15],[23]',
        residual_connection='0,0,0,0',first_conv_filters=32,first_conv_kernel_size=5,stride=3,max_pool=False,pooled=False,spatial_attention=False)
    net=model(flags,(FRAMES,40),BATCH)
    if initial_weights:
        prior=json.loads((initial_weights.parent/'config.json').read_text())
        if not expanded or prior.get('human_training') is not False or not prior.get('expanded_utterance_corpus') or prior.get('training_speakers')!=list(TRAIN) or prior.get('validation_speakers')!=list(VALIDATION) or prior.get('test_speakers')!=list(TEST) or not initial_sha or hashlib.sha256(initial_weights.read_bytes()).hexdigest()!=initial_sha:raise ValueError('Only hash-pinned public expanded weights with the same split are allowed')
        net.load_weights(initial_weights);config['initial_public_weights_sha256']=initial_sha
        config['specaugment_max_frames_bins']=2;config['specaugment_mask_count']=1
        (out/'config.json').write_text(json.dumps(config,indent=2))
    net.compile(optimizer=tf.keras.optimizers.Adam(.0002 if initial_weights else .001),loss='binary_crossentropy')
    def validation_bce():
        probs=np.concatenate([np.asarray(net(np.asarray(val[i:i+BATCH],np.float32),training=False)).reshape(-1) for i in range(0,len(val),BATCH)])
        p=np.clip(probs,1e-7,1-1e-7);return float(-np.mean(labels*np.log(p)+(1-labels)*np.log1p(-p)))
    rng=np.random.default_rng(SEED+2);best=float('inf');history=[{'step':0,'validation_bce':validation_bce()}];started=time.monotonic()
    for step in range(steps):
        ids=rng.integers(0,len(x),BATCH);batch=np.asarray(x[ids],np.float32).copy()
        for sample in batch:
            for _ in range(1 if initial_weights else 2):
                width=int(rng.integers(0,3 if initial_weights else 6));at=int(rng.integers(0,FRAMES-max(1,width)+1));sample[at:at+width]=0
                width=int(rng.integers(0,3 if initial_weights else 6));at=int(rng.integers(0,40-max(1,width)+1));sample[:,at:at+width]=0
        loss=net.train_on_batch(batch,y[ids],sample_weight=np.where(y[ids]>.5,1. if expanded else 1.5,4. if hard_replay else 2. if expanded else 1.).astype(np.float32))
        if (step+1)%100==0:print(json.dumps({'step':step+1,'steps':steps,'loss':float(loss),'elapsed_s':round(time.monotonic()-started,1)}),flush=True)
        if (step+1)%1000==0 or step+1==steps:
            metric=validation_bce()
            history.append({'step':step+1,'validation_bce':metric})
            net.save_weights(out/'last.weights.h5')
            if metric<best:best=metric;net.save_weights(out/'best.weights.h5')
            (out/'history.json').write_text(json.dumps(history,indent=2))
    selected=select_checkpoint(history)
    (out/'selection.json').write_text(json.dumps({'selected':selected,'initial':history[0],'accepted':False},indent=2))
    net.load_weights(out/'best.weights.h5')
    streamed=to_streaming_inference(net,dict(spectrogram_length=FRAMES,features_length=FRAMES,stride=3),mode=Modes.STREAM_INTERNAL_STATE_INFERENCE)
    export=tf.keras.export.ExportArchive();export.track(streamed);export.add_endpoint('serve',streamed.call,input_signature=[tf.TensorSpec((1,3,40),tf.float32)]);export.write_out(str(out/'saved'))
    converter=tf.lite.TFLiteConverter.from_saved_model(str(out/'saved'));converter.optimizations=[tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_ops=[tf.lite.OpsSet.TFLITE_BUILTINS_INT8];converter._experimental_variable_quantization=True
    converter.inference_input_type=tf.int8;converter.inference_output_type=tf.uint8
    def calibrate():
        for index in range(256):
            sample=np.asarray(x[index],np.float32).copy()
            if index==0:sample[0,:2]=[0,26]
            for block in sample.reshape(-1,3,40):yield [block[None]]
    converter.representative_dataset=calibrate;blob=converter.convert();(out/'gobot.tflite').write_bytes(blob)
    runtime=tf.lite.Interpreter(model_content=blob,num_threads=1);runtime.allocate_tensors()
    details={'sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob),'context_frames':FRAMES,'window':10,'cutoff':231,
        'input_quantization':runtime.get_input_details()[0]['quantization'],'output_quantization':runtime.get_output_details()[0]['quantization'],
        'ops':sorted({op['op_name'] for op in runtime._get_ops_details()}),'human_training':False,'cpu_only':True,'elapsed_train_s':time.monotonic()-started}
    (out/'model.json').write_text(json.dumps(details,indent=2));print(json.dumps(details),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('corpus',type=Path);p.add_argument('output',type=Path);p.add_argument('--steps',type=int,default=10000);p.add_argument('--windows',type=int,default=50000);p.add_argument('--reuse-public',type=Path);p.add_argument('--cache',type=Path);p.add_argument('--expanded',action='store_true');p.add_argument('--initial-weights',type=Path);p.add_argument('--initial-sha');p.add_argument('--hard-replay',type=Path);p.add_argument('--word-anchored',action='store_true');a=p.parse_args();main(a.corpus,a.output,a.steps,a.windows,a.reuse_public,a.cache,a.expanded,a.initial_weights,a.initial_sha,a.hard_replay,a.word_anchored)

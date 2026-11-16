"""PLAN-only bounded field adaptation; keeps third question out of training.

Uses existing microWakeWord, public encoder, DPAPI store and original deletion
deadline. Never arms recording, uploads Owner data, flashes or grants spending.
"""
import os
os.environ['TF_NUM_INTRAOP_THREADS']='2';os.environ['TF_NUM_INTEROP_THREADS']='1';os.environ['OPENBLAS_NUM_THREADS']='2'
import argparse,hashlib,io,json,math,sys,tempfile,time,wave
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'data/hardware/gobot-v1/mww-inputs/mww'),str(ROOT/'services/brain'),str(Path(__file__).parent)]
import numpy as np
import tensorflow as tf
from microwakeword.mixednet import model
from microwakeword.layers.modes import Modes
from microwakeword.utils import to_streaming_inference
from gobot.secrets_store import _dpapi
from sample_retention import paths,candidate_path,cleanup
import train_reference as reference
from original_replay import corpus
from parity import fingerprint
from guided_wake_plan import validate_capture


def validate_plan(metadata,plan,seconds,now):
    if metadata.get('capture_domain')!='mono_pcm16_pre_afe' or metadata.get('protocol')!='field_failed_wake_recheck' or metadata.get('capture_state')!='complete_crc_verified' or metadata.get('owner_reported_completion') is not True or not now<metadata.get('expires_at',0):raise ValueError('Completed unexpired approved field capture required')
    if plan.get('schema')!='field_recheck_v1' or plan.get('human_labels_verified') is not False or len(plan.get('positive_segments',[]))!=3 or len(plan.get('question_segments',[]))!=3 or len(plan.get('negative_segments',[]))!=1 or not 29.5<=seconds<=30:raise ValueError('Wrong provisional field protocol')
    for index,(a,b) in enumerate(plan['positive_segments']):
        qa,qb=plan['question_segments'][index]
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (a,b,qa,qb)) or not 0<=qa<=a<b<=qb<=seconds or not .3<=b-a<=1.6:raise ValueError('Invalid field keyword intervals')
        if index and qa<plan['question_segments'][index-1][1]:raise ValueError('Overlapping field questions')
    a,b=plan['negative_segments'][0]
    if not plan['question_segments'][2][1]<a<b<=seconds or b-a<6:raise ValueError('Negative/holdout overlap')
    return [0,1],[2],(a,b-2.5),(b-2,b)


def main(ident,adapt_last_block=False):
    p,meta=paths(ident);evidence=json.loads(meta.read_text());guided=evidence.get('protocol')=='guided_wake8'
    plan=evidence.get('capture_plan') if guided else json.loads(p.with_name(ident+'-labels.json').read_text())
    foundation=ROOT/'data/hardware/gobot-v1/kws/field-public-foundation';provenance=json.loads((foundation/'provenance.json').read_text())
    weights=foundation/'public.weights.h5';negative=foundation/'negative.npy'
    if provenance.get('owner_training') is not False or provenance.get('license')!='CC-BY-4.0' or hashlib.sha256(weights.read_bytes()).hexdigest()!=provenance.get('weights_sha256') or hashlib.sha256(negative.read_bytes()).hexdigest()!=provenance.get('negative_sha256'):raise ValueError('Changed public foundation')
    if time.time()>=evidence.get('expires_at',0):raise ValueError('Source expired before decryption')
    if fingerprint()!=(98,1987024791):raise ValueError('Local frontend does not match installed device')
    raw=bytearray(_dpapi(p.read_bytes(),decrypt=True));pcm=None;x=None;prefix=None
    try:
        with wave.open(io.BytesIO(raw),'rb') as wav:
            if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):raise ValueError('Wrong raw audio format')
            pcm=np.frombuffer(wav.readframes(wav.getnframes()),'<i2').copy()
        if guided:
            plan=validate_capture(evidence,len(pcm)/16000,time.time());names=[r for r in plan['steps'] if r['kind']=='name'];negative_steps=[r for r in plan['steps'] if r['kind']=='negative']
            isolated_train=plan['training_isolated_indices'];isolated_heldout=plan['heldout_isolated_indices'];train=[];heldout=plan['heldout_question_indices'];clips=[]
            baseline=pcm[:32000].astype(float);noise=float(np.sqrt(np.mean(baseline*baseline)))
            for index in isolated_train:
                row=names[index];raw_step=pcm[row['start']*16000:row['end']*16000]
                rms=np.sqrt(np.mean(raw_step[:len(raw_step)//160*160].astype(float).reshape(-1,160)**2,axis=1));active=np.flatnonzero(rms>=max(16,noise*3))
                if not len(active) or not 15<=active[-1]-active[0]+1<=200:raise ValueError('Missing/ambiguous speech in guided name step')
                a=max(0,int(active[0])*160-4800);b=min(len(raw_step),(int(active[-1])+1)*160+4800);clips.append(raw_step[a:b].copy())
            following=[np.zeros(0,dtype='<i2') for _ in clips];neg_train=(negative_steps[0]['start'],negative_steps[2]['end']);neg_holdout=(negative_steps[3]['start'],negative_steps[3]['end'])
            owner_negative=pcm[neg_train[0]*16000:neg_train[1]*16000].copy();baseline.fill(0)
        else:
            train,heldout,neg_train,neg_holdout=validate_plan(evidence,plan,len(pcm)/16000,time.time());isolated_train=[];isolated_heldout=[]
            clips=[pcm[int(plan['positive_segments'][i][0]*16000):int(plan['positive_segments'][i][1]*16000)].copy() for i in train]
            following=[pcm[int(plan['positive_segments'][i][1]*16000):int(plan['question_segments'][i][1]*16000)].copy() for i in train]
            owner_negative=pcm[int(neg_train[0]*16000):int(neg_train[1]*16000)].copy()
            prefix=reference.features(pcm[:int(plan['question_segments'][1][1]*16000)])
        public_root=ROOT/'data/hardware/gobot-v1/kws/expanded-replay';speakers=('denis','dmitri','espeak-ru','anna','irina')
        positive_paths,negative_paths=corpus(public_root,speakers);allowed=set(positive_paths);standalone=[]
        for speaker in speakers:
            for row in json.loads((public_root/speaker/'manifest.json').read_text(encoding='utf-8')):
                path=public_root/speaker/row['file']
                if row['label']=='positive' and ',' not in row['text'] and path in allowed:standalone.append(path)
        if len(standalone)!=75:raise ValueError('Unexpected public standalone-name inventory')
        public_negative=np.load(negative,mmap_mode='r')
        if public_negative.shape!=(2048,204,40):raise ValueError('Wrong public speech replay')
        reference.WORD_ANCHORED=True;reference.TAIL_SAMPLES=9600;rng=np.random.default_rng(20261123)
        x=np.empty((2048,204,40),np.float32);y=np.zeros(2048,np.float32)
        for i in range(len(x)):
            kind=i%8;j=int(rng.integers(len(clips)))
            if kind in (0,6):x[i]=reference.window(clips[j],rng,True,following[j] if kind==6 else None,quiet=True);y[i]=1
            elif kind==4:
                if prefix is None:x[i]=reference.window(clips[j],rng,True,quiet=True)
                else:
                    endpoint=int((plan['positive_segments'][j][1]+rng.uniform(.05,.6)-.02)*100)+1
                    x[i]=prefix[endpoint-204:endpoint]
                y[i]=1
            elif kind in (1,7):x[i]=reference.window(owner_negative,rng,False,quiet=True)
            elif kind==2:x[i]=reference.window(np.fromfile(standalone[int(rng.integers(len(standalone)))],'<i2'),rng,True,quiet=True);y[i]=1
            elif kind==3:x[i]=reference.window(np.fromfile(negative_paths[int(rng.integers(len(negative_paths)))],'<i2'),rng,False,quiet=True)
            else:x[i]=public_negative[int(rng.integers(len(public_negative)))]
        tf.keras.utils.set_random_seed(20261123)
        flags=SimpleNamespace(pointwise_filters='64,64,64,64',repeat_in_block='1,1,1,1',mixconv_kernel_sizes='[5],[7,11],[9,15],[23]',residual_connection='0,0,0,0',first_conv_filters=32,first_conv_kernel_size=5,stride=3,max_pool=False,pooled=False,spatial_attention=False)
        net=model(flags,(204,40),128);net.load_weights(weights)
        for layer in net.layers:layer.trainable=isinstance(layer,tf.keras.layers.Dense)
        if adapt_last_block:
            if [type(layer).__name__ for layer in net.layers[-8:]]!=['Stream','DepthwiseConv2D','Conv2D','BatchNormalization','Activation','Stream','Flatten','Dense']:raise ValueError('Unexpected final reference convolution block')
            for layer in net.layers[-8:]:layer.trainable=not isinstance(layer,tf.keras.layers.BatchNormalization)
        net.compile(optimizer=tf.keras.optimizers.Adam(.00005 if adapt_last_block else .0002),loss='binary_crossentropy');started=time.monotonic()
        for epoch in range(40):
            if time.time()>=evidence['expires_at'] or time.monotonic()-started>1800:raise ValueError('Private training expiry/time limit')
            for ids in rng.permutation(len(x)).reshape(-1,128):net.train_on_batch(x[ids],y[ids],sample_weight=np.where(y[ids]>.5,1.,1.5).astype(np.float32))
            print(json.dumps({'field_epoch':epoch+1,'epochs':40}),flush=True)
        stream=to_streaming_inference(net,dict(spectrogram_length=204,features_length=204,stride=3),mode=Modes.STREAM_INTERNAL_STATE_INFERENCE)
        with tempfile.TemporaryDirectory(prefix=ident+'-export-',dir=p.parent) as directory:
            export=tf.keras.export.ExportArchive();export.track(stream);export.add_endpoint('serve',stream.call,input_signature=[tf.TensorSpec((1,3,40),tf.float32)]);export.write_out(directory)
            converter=tf.lite.TFLiteConverter.from_saved_model(directory);converter.optimizations=[tf.lite.Optimize.DEFAULT];converter.target_spec.supported_ops=[tf.lite.OpsSet.TFLITE_BUILTINS_INT8];converter._experimental_variable_quantization=True;converter.inference_input_type=tf.int8;converter.inference_output_type=tf.uint8
            def calibration():
                for i in range(64):
                    sample=x[i].copy()
                    if i==0:sample[0,:2]=[0,26]
                    for block in sample.reshape(-1,3,40):yield [block[None]]
                    sample.fill(0)
            converter.representative_dataset=calibration;blob=converter.convert()
        if time.time()>=evidence['expires_at']:cleanup(ident);raise ValueError('Source expired before sealing')
        sha=hashlib.sha256(blob).hexdigest();target=candidate_path(ident,sha);target.write_bytes(_dpapi(blob));p.with_name(ident+'-personal-model.dpapi').write_bytes(target.read_bytes())
        report={'kind':'PLAN-only field adaptation','capture_domain':'mono_pcm16_pre_afe','model_sha256':sha,'bytes':len(blob),'context_frames':204,'window':10,'cutoff':231,'training_question_indices':train,'heldout_question_indices':heldout,'training_negative_seconds':neg_train,'heldout_negative_seconds':neg_holdout,'human_labels_verified':False,'label_source':'provisional existing field timings','owner_human_training':True,'contains_personal_weights':True,'epochs':40,'encoder_frozen':True,'base_public_weights_sha256':provenance['weights_sha256'],'expires_at':evidence['expires_at'],'retention_same_as_sample':True,'raw_or_features_exported':False,'product_accepted':False,'installed':False,'paid_calls':0}
        report.update(base_profile='field_public_speech',encoder_frozen=not adapt_last_block,lower_encoder_frozen=True,adapt_only_final_convolution_block=adapt_last_block,protocol=evidence['protocol'],training_isolated_indices=isolated_train,heldout_isolated_indices=isolated_heldout,persistent_selected_model_consent=evidence.get('persistent_selected_model_consent',False))
        if guided:
            report.update(kind='PLAN-only guided adaptation',label_source='sample-clock prompts with provisional energy margins')
        target.with_suffix('.json').write_text(json.dumps(report,indent=2));print(json.dumps({'field_model_sealed':True,'training_utterances':len(clips),'heldout_utterances':len(heldout)+len(isolated_heldout),'model_keeps_original_expiry':True,'installed':False,'paid_calls':0}),flush=True)
    finally:
        raw[:]=bytes(len(raw))
        for array in (pcm,x,prefix):
            if array is not None:array.fill(0)
        for name in ('clips','following'):
            for array in locals().get(name,[]):array.fill(0)
        if 'owner_negative' in locals():owner_negative.fill(0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('sample_id');parser.add_argument('--adapt-last-block',action='store_true');args=parser.parse_args();main(args.sample_id,args.adapt_last_block)

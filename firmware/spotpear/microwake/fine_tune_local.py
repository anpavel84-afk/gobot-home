"""Bounded PLAN-only neural adaptation; never uploads speech or admits a model."""
import os
os.environ['TF_NUM_INTRAOP_THREADS']='2';os.environ['TF_NUM_INTEROP_THREADS']='1';os.environ['OPENBLAS_NUM_THREADS']='2'
import argparse,hashlib,io,json,sys,tempfile,time,wave
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
from sample_retention import paths,candidate_path
from train import features,window,BATCH,FRAMES,STRIDE
from calibration_plan import validate

def main(ident,balanced_replay=False,audit_conversion=False,continuous_replay=False,original_replay=None,negative_weight=1.,context_frames=75,temporal_head=False,base_profile='model3',epochs=12,robust_replay=False,freeze_encoder=False,freeze_norm=False,hard_replay=False,coarticulation=False,adapt_last_block=False):
    global FRAMES
    if not 1<=negative_weight<=8:raise ValueError('Unbounded negative-loss weight')
    if context_frames not in (75,120,150,204):raise ValueError('Unsupported bounded context')
    if epochs not in (12,40) or base_profile not in ('model3','model7','reference','expanded','variant'):raise ValueError('Unsupported bounded training profile')
    if base_profile in ('reference','expanded','variant') and (context_frames!=204 or not original_replay or not temporal_head):raise ValueError('Reference requires exact temporal architecture and replay split')
    if adapt_last_block and (not freeze_encoder or base_profile!='variant'):raise ValueError('Last-block adaptation requires the fixed public variant encoder')
    import train as training
    FRAMES=training.FRAMES=context_frames
    training.POSITIVE_TAIL_SAMPLES=9600 if base_profile in ('reference','expanded','variant') else 4000
    replay_speakers=('denis','dmitri','espeak-ru','anna','irina') if base_profile in ('expanded','variant') else ('denis','dmitri','espeak-ru','anna') if base_profile=='reference' else ('denis','espeak-ru','anna','aleksandr')
    path,metadata=paths(ident)
    evidence=json.loads(metadata.read_text())
    if time.time()>=evidence['expires_at']:raise ValueError('Sample expired')
    if evidence.get('capture_domain')!='mono_pcm16_pre_afe':
        raise ValueError('Wake adaptation requires exact pre-AFE PCM, not conversation AFE/Opus audio')
    if evidence.get('protocol')!='wake10_questions':
        raise ValueError('This calibration script requires the labelled wake10_questions protocol')
    raw=bytearray(_dpapi(path.read_bytes(),decrypt=True));pcm=None;x=None
    try:
        with wave.open(io.BytesIO(raw),'rb') as w:
            assert (w.getframerate(),w.getnchannels(),w.getsampwidth())==(16000,1,2)
            pcm=np.frombuffer(w.readframes(w.getnframes()),'<i2').copy()
        assert 32*16000<=len(pcm)<=60*16000
        # Explicit private review instead of selecting loud peaks (which could
        # silently label a question/negative as the wake word).
        plan=json.loads(path.with_name(ident+'-labels.json').read_text())
        positives,negatives=validate(plan,len(pcm)/16000)
        train_ids=[i for i in range(10) if i not in {4,9}]
        clips=[pcm[int(positives[i][0]*16000):int(positives[i][1]*16000)].copy() for i in train_ids]
        clips += [pcm[int(a*16000):int(b*16000)].copy() for a,b in plan.get('training_question_prefixes',[])]
        if coarticulation:
            from coarticulation import append_speech
            for a,b in plan.get('training_question_prefixes',[]):
                end=min(b+.5,plan['question_segments'][1][1])
                clips.append(pcm[int(a*16000):int(end*16000)].copy())
        negative_clips=[pcm[int(a*16000):int(b*16000)].copy() for a,b in negatives]
        if coarticulation:
            from coarticulation import negative_speech_windows
            mined=negative_speech_windows(negative_clips)
            for clip in negative_clips:clip.fill(0)
            negative_clips=mined
        negative_paths=sorted((ROOT/'data/hardware/gobot-v1/kws/denis').glob('negative*.pcm'))
        # The pinned older PLAN corpus has29 negative phrases x3 speeds.
        # This is a calibration pilot, not the full198-clip acceptance corpus.
        assert len(negative_paths)==87,'Unexpected local negative corpus'
        synthetic_positive=[]
        if balanced_replay:
            second=sorted((ROOT/'data/hardware/gobot-v1/kws/dmitri').glob('negative*.pcm'))
            assert len(second)==87
            negative_paths+=second
            synthetic_positive=[p for speaker in ('denis','dmitri') for p in sorted((ROOT/f'data/hardware/gobot-v1/kws/{speaker}').glob('positive*.pcm'))]
            assert len(synthetic_positive)==18
        if original_replay:
            if not balanced_replay:raise ValueError('Original replay requires balanced profile')
            from original_replay import corpus
            synthetic_positive,negative_paths=corpus(original_replay,replay_speakers)
        hard_paths=[]
        if hard_replay:
            if not original_replay:raise ValueError('Hard replay requires verified original corpus')
            from original_replay import hard_negatives
            hard_paths=hard_negatives(original_replay,replay_speakers)
        count=1024 if original_replay else 512
        rng=np.random.default_rng(20261114);samples=[];labels=[]
        if continuous_replay:
            from continuous_replay import windows,training_audio
            heldout_questions=[plan['question_segments'][i] for i in plan.get('heldout_question_indices',[0,1,2])]
            masked=training_audio(pcm,positives,heldout_questions)
            try:continuous_features=features(masked)
            finally:masked.fill(0)
            stream_pos,stream_neg=windows(continuous_features,positives,negatives,rng,count=count,frames=FRAMES,positive_tail_frames=60 if base_profile=='variant' else 3)
        for i in range(count):
            owner_word=clips[i%len(clips)]
            if coarticulation and i%3:
                owner_word=append_speech(owner_word,np.fromfile(negative_paths[(i*11)%len(negative_paths)],'<i2'),rng)
            samples.append(window(owner_word,rng,True));labels.append(1.)
            samples.append(window(negative_clips[i%len(negative_clips)],rng,False));labels.append(0.)
            samples.append(window(np.fromfile(negative_paths[i%len(negative_paths)],'<i2'),rng,False));labels.append(0.)
            if balanced_replay:
                synthetic_word=np.fromfile(synthetic_positive[i%len(synthetic_positive)],'<i2')
                if coarticulation and i%3:synthetic_word=append_speech(synthetic_word,np.fromfile(negative_paths[(i*17)%len(negative_paths)],'<i2'),rng)
                samples.append(window(synthetic_word,rng,True));labels.append(1.)
                samples.append(window(np.fromfile(negative_paths[(i*7+13)%len(negative_paths)],'<i2'),rng,False));labels.append(0.)
            if continuous_replay:
                samples.extend([stream_pos[i],stream_neg[i]]);labels.extend([1.,0.])
            if hard_paths:
                samples.append(window(np.fromfile(hard_paths[i%len(hard_paths)],'<i2'),rng,False));labels.append(0.)
        x=np.stack(samples);y=np.asarray(labels,np.float32);samples.clear()
        tf.keras.utils.set_random_seed(20261114);tf.config.experimental.enable_op_determinism()
        flags=SimpleNamespace(pointwise_filters='24,24,24',repeat_in_block='1,1,1',mixconv_kernel_sizes='[3],[5],[7]',
            residual_connection='0,0,0',first_conv_filters=24,first_conv_kernel_size=3,stride=3,max_pool=False,pooled=True,spatial_attention=False)
        if base_profile=='model7':flags.pointwise_filters='40,40,40';flags.first_conv_filters=40;flags.mixconv_kernel_sizes='[3],[5],[9]'
        if base_profile in ('reference','expanded','variant'):
            flags.pointwise_filters='64,64,64,64';flags.repeat_in_block='1,1,1,1';flags.mixconv_kernel_sizes='[5],[7,11],[9,15],[23]'
            flags.residual_connection='0,0,0,0';flags.first_conv_filters=32;flags.first_conv_kernel_size=5;flags.pooled=False
        net=model(flags,(FRAMES,40),BATCH)
        weight_file,expected=('base.weights.h5','d33994d0a2f22a30b5db5b4f74fe5b4eb23ff8be33cd392f2cbcf07ec5fc4a3c') if base_profile=='model3' else ('model7.weights.h5','a66adc5eb3aa192ec6c70342ab55dbb6389e224d17f3c919954b5ba2d680d9d2')
        weights=ROOT/'data/hardware/gobot-v1/local-wake-models'/weight_file
        if base_profile=='reference':
            weights=weights.with_name('reference-temporal.weights.h5');expected='b0328f08db7428e5d0a84917cb402d6a86fa4cdc82de1d7bb3cae2b4651d8159'
        elif base_profile=='expanded':
            weights=weights.with_name('expanded-public.weights.h5');expected='73a6ceeca599bbdf59223ff3438fed274f71774d1389a61a69a187b04e0bdc2b'
        elif base_profile=='variant':
            weights=weights.with_name('variant-public.weights.h5');expected='e65b35666d4a911d5de12a3206bf10a056c4bb839485d7c47e3f1063d3c19dc1'
        assert hashlib.sha256(weights.read_bytes()).hexdigest()==expected
        net.load_weights(weights)
        if temporal_head and base_profile not in ('reference','expanded','variant'):
            pooled=net;flags.pooled=False;net=model(flags,(FRAMES,40),BATCH)
            from temporal_head import initialize
            initialize(net,pooled)
            probe=x[:BATCH]
            if not np.allclose(np.asarray(net(probe,training=False)),np.asarray(pooled(probe,training=False)),atol=1e-5):
                raise ValueError('Temporal initialization changed baseline function')
        if freeze_encoder:
            for layer in net.layers[:-1]:layer.trainable=False
        if adapt_last_block:
            if [type(layer).__name__ for layer in net.layers[-8:]]!=['Stream','DepthwiseConv2D','Conv2D','BatchNormalization','Activation','Stream','Flatten','Dense']:raise ValueError('Unexpected final convolution block')
            for layer in net.layers[-8:]:layer.trainable=not isinstance(layer,tf.keras.layers.BatchNormalization)
        if freeze_norm:
            for layer in net.layers:
                if isinstance(layer,tf.keras.layers.BatchNormalization):layer.trainable=False
        net.compile(optimizer=tf.keras.optimizers.Adam(.00005 if adapt_last_block else .0002),loss='binary_crossentropy')
        # Fixed bounded epochs, no search/early stopping on held-out owner questions.
        spectral_rng=np.random.default_rng(20262105)
        for epoch in range(epochs):
            net.reset_metrics()
            for batch in rng.permutation(len(x)).reshape(-1,BATCH):
                examples=x[batch].copy()
                if robust_replay:
                    bins=np.arange(40)
                    for j in range(len(examples)):
                        pos=np.clip(bins*spectral_rng.uniform(.96,1.04)+spectral_rng.uniform(-.8,.8),0,39);left=pos.astype(int);weight=(pos-left)[None,:]
                        examples[j]=examples[j][:,left]*(1-weight)+examples[j][:,np.minimum(39,left+1)]*weight
                        examples[j]*=np.linspace(spectral_rng.uniform(.9,1.1),spectral_rng.uniform(.9,1.1),40)
                net.train_on_batch(examples,y[batch],sample_weight=np.where(y[batch]>.5,1.,negative_weight).astype(np.float32));examples.fill(0)
            print(json.dumps({'local_epoch':epoch+1,'epochs':epochs,'loss':float(np.asarray(net.metrics[0].result()))}),flush=True)
        predictions=np.concatenate([np.asarray(net(x[i:i+BATCH],training=False)).reshape(-1) for i in range(0,len(x),BATCH)])
        train_diagnostic={'training_only':True,'positive_mean':float(predictions[y==1].mean()),
            'negative_mean':float(predictions[y==0].mean()),'binary_accuracy':float(((predictions>=.5)==y).mean())}
        if balanced_replay and continuous_replay and hard_paths:
            train_diagnostic['positive_origins']={name:{'mean':float(predictions[index::8].mean()),'fraction_above_point9':float(np.mean(predictions[index::8]>=.9))}
                for name,index in [('owner_augmented',0),('synthetic',3),('owner_continuous',5)]}
        print(json.dumps({'training_inference_diagnostic':train_diagnostic}),flush=True)
        if audit_conversion:
            from conversion_audit import offline_probes
            nonstream=offline_probes(net,pcm,plan,features,frames=FRAMES)
        streamed=to_streaming_inference(net,dict(spectrogram_length=FRAMES,features_length=FRAMES,stride=STRIDE),mode=Modes.STREAM_INTERNAL_STATE_INFERENCE)
        assert tuple(streamed.input_shape)==(1,3,40)
        parent=ROOT/'data/hardware/gobot-v1/wake-human';parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='model-export-',dir=parent) as directory:
            export=tf.keras.export.ExportArchive();export.track(streamed)
            export.add_endpoint('serve',streamed.call,input_signature=[tf.TensorSpec((1,3,40),tf.float32)])
            export.write_out(directory)
            float_blob=tf.lite.TFLiteConverter.from_saved_model(directory).convert() if audit_conversion else None
            converter=tf.lite.TFLiteConverter.from_saved_model(directory)
            converter.optimizations=[tf.lite.Optimize.DEFAULT];converter.target_spec.supported_ops=[tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
            converter._experimental_variable_quantization=True;converter.inference_input_type=tf.int8;converter.inference_output_type=tf.uint8
            def calibrate():
                c=x[:64].copy();c[0,0,:2]=[0,26]
                for sample in c:
                    for block in sample.reshape(-1,3,40):yield [block[np.newaxis]]
            converter.representative_dataset=calibrate;blob=converter.convert()
        if audit_conversion:
            from conversion_audit import audit
            diagnostic=audit(tf,float_blob,blob,pcm,plan,features)
            for probe,baseline in zip(diagnostic['probes'],nonstream):probe.update(baseline)
            path.with_name(ident+'-conversion-audit.json').write_text(json.dumps(diagnostic,indent=2))
        model_sha=hashlib.sha256(blob).hexdigest();sealed=_dpapi(blob)
        immutable=candidate_path(ident,model_sha)
        if not immutable.exists():immutable.write_bytes(sealed)
        path.with_name(ident+'-personal-model.dpapi').write_bytes(sealed)
        report={'kind':'local_existing_microWakeWord_neural_adaptation','epochs':epochs,'seed':20261114,'base_profile':base_profile,'robust_spectral_replay':robust_replay,'frozen_pretrained_encoder':freeze_encoder and not adapt_last_block,'lower_encoder_frozen':freeze_encoder,'frozen_batch_norm':freeze_norm,'hard_negative_clips':len(hard_paths),
            'training_utterances':len(clips),'heldout_isolated_indices':[4,9],
            'question_phrases_used_for_training':bool(plan.get('training_question_prefixes')),
            'training_question_indices':plan.get('training_question_indices',[]),'heldout_question_indices':plan.get('heldout_question_indices',[0,1,2]),
            'capture_domain':'mono_pcm16_pre_afe','label_source':'explicit private timing hypotheses; NOT independent acceptance',
            'negative_training_source':'reviewed owner confusable intervals plus existing licensed '+('/'.join(replay_speakers) if original_replay else 'Denis/Dmitri' if balanced_replay else 'Denis')+' negatives',
            'synthetic_negative_clips':len(negative_paths),
            'balanced_synthetic_replay':balanced_replay,'synthetic_positive_clips':len(synthetic_positive),
            'continuous_frontend_replay':continuous_replay,
            'continuous_positive_tail_frames':60 if base_profile=='variant' else 3,
            'original_training_replay':bool(original_replay),'validation_test_speakers_in_replay':False if original_replay else None,
            'negative_loss_weight':negative_weight,
            'context_frames':FRAMES,'positive_word_front_crop':False,
            'positive_tail_samples':training.POSITIVE_TAIL_SAMPLES,'replay_speakers':replay_speakers,
            'cutoff':231 if base_profile in ('reference','expanded','variant') else 250,'window':10 if base_profile in ('reference','expanded','variant') else 3,
            'temporal_dense_head':temporal_head,
            'immediate_following_speech_augmentation':coarticulation,
            'owner_negative_training_windows':len(negative_clips),
            'adapt_only_final_convolution_block':adapt_last_block,
            'training_inference_diagnostic':train_diagnostic,
            'model_sha256':model_sha,'bytes':len(blob),'human_labels_verified':False,
            'product_accepted':False,'installed':False,'raw_or_features_exported':False,'retention_same_as_sample':True}
        path.with_name(ident+'-neural-pilot.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
        immutable.with_suffix('.json').write_text(json.dumps(report,indent=2))
    finally:
        raw[:]=bytes(len(raw))
        if pcm is not None:pcm.fill(0)
        if x is not None:x.fill(0)
        if 'clips' in locals():
            for c in clips:c.fill(0)
        if 'negative_clips' in locals():
            for c in negative_clips:c.fill(0)
        if 'continuous_features' in locals():continuous_features.fill(0)
        if 'stream_pos' in locals():
            for c in stream_pos+stream_neg:c.fill(0)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('sample_id');parser.add_argument('--balanced-replay',action='store_true');parser.add_argument('--audit-conversion',action='store_true');parser.add_argument('--continuous-replay',action='store_true');parser.add_argument('--original-replay',type=Path);parser.add_argument('--negative-weight',type=float,default=1.);parser.add_argument('--context-frames',type=int,choices=[75,120,150,204],default=75);parser.add_argument('--temporal-head',action='store_true');parser.add_argument('--base-profile',choices=['model3','model7','reference','expanded','variant'],default='model3');parser.add_argument('--epochs',type=int,choices=[12,40],default=12);parser.add_argument('--robust-replay',action='store_true');parser.add_argument('--freeze-encoder',action='store_true');parser.add_argument('--freeze-norm',action='store_true');parser.add_argument('--hard-replay',action='store_true');parser.add_argument('--coarticulation',action='store_true');parser.add_argument('--adapt-last-block',action='store_true');args=parser.parse_args();main(args.sample_id,args.balanced_replay,args.audit_conversion,args.continuous_replay,args.original_replay,args.negative_weight,args.context_frames,args.temporal_head,args.base_profile,args.epochs,args.robust_replay,args.freeze_encoder,args.freeze_norm,args.hard_replay,args.coarticulation,args.adapt_last_block)

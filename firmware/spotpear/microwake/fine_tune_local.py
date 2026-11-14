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
from sample_retention import paths
from train import features,window,BATCH,FRAMES,STRIDE

def main(ident,balanced_replay=False):
    path,metadata=paths(ident)
    if time.time()>=json.loads(metadata.read_text())['expires_at']:raise ValueError('Sample expired')
    raw=bytearray(_dpapi(path.read_bytes(),decrypt=True));pcm=None;x=None
    try:
        with wave.open(io.BytesIO(raw),'rb') as w:
            assert (w.getframerate(),w.getnchannels(),w.getsampwidth())==(16000,1,2)
            pcm=np.frombuffer(w.readframes(w.getnframes()),'<i2').copy()
        assert 32*16000<=len(pcm)<=60*16000
        # Owner confirmed the requested sequence; energy timing is a hypothesis,
        # not a claim of independently labelled acoustic acceptance.
        energy=pcm[:19*16000//320*320].reshape(-1,320).astype(float)
        rms=np.sqrt((energy**2).mean(axis=1));peaks=[]
        for at in np.argsort(rms)[::-1]:
            if all(abs(int(at)-p)>=45 for p in peaks):peaks.append(int(at))
            if len(peaks)==10:break
        peaks=np.sort(peaks)*.02
        train_ids=[i for i in range(10) if i not in {4,9}]
        clips=[pcm[max(0,int((peaks[i]-.28)*16000)):int((peaks[i]+.34)*16000)].copy() for i in train_ids]
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
        rng=np.random.default_rng(20261114);samples=[];labels=[]
        for i in range(512):
            samples.append(window(clips[i%len(clips)],rng,True));labels.append(1.)
            at=rng.integers(32*16000,43*16000)
            samples.append(window(pcm[at:at+16000],rng,False));labels.append(0.)
            samples.append(window(np.fromfile(negative_paths[i%len(negative_paths)],'<i2'),rng,False));labels.append(0.)
            if balanced_replay:
                samples.append(window(np.fromfile(synthetic_positive[i%len(synthetic_positive)],'<i2'),rng,True));labels.append(1.)
                samples.append(window(np.fromfile(negative_paths[(i*7+13)%len(negative_paths)],'<i2'),rng,False));labels.append(0.)
        x=np.stack(samples);y=np.asarray(labels,np.float32);samples.clear()
        tf.keras.utils.set_random_seed(20261114);tf.config.experimental.enable_op_determinism()
        flags=SimpleNamespace(pointwise_filters='24,24,24',repeat_in_block='1,1,1',mixconv_kernel_sizes='[3],[5],[7]',
            residual_connection='0,0,0',first_conv_filters=24,first_conv_kernel_size=3,stride=3,max_pool=False,pooled=True,spatial_attention=False)
        net=model(flags,(FRAMES,40),BATCH)
        weights=ROOT/'data/hardware/gobot-v1/local-wake-models/base.weights.h5'
        assert hashlib.sha256(weights.read_bytes()).hexdigest()=='d33994d0a2f22a30b5db5b4f74fe5b4eb23ff8be33cd392f2cbcf07ec5fc4a3c'
        net.load_weights(weights);net.compile(optimizer=tf.keras.optimizers.Adam(.0002),loss='binary_crossentropy')
        # Fixed12 epochs, no search/early stopping on held-out owner questions.
        for epoch in range(12):
            for batch in rng.permutation(len(x)).reshape(-1,BATCH):net.train_on_batch(x[batch],y[batch])
            print(json.dumps({'local_epoch':epoch+1,'epochs':12}),flush=True)
        streamed=to_streaming_inference(net,dict(spectrogram_length=FRAMES,features_length=FRAMES,stride=STRIDE),mode=Modes.STREAM_INTERNAL_STATE_INFERENCE)
        assert tuple(streamed.input_shape)==(1,3,40)
        parent=ROOT/'data/hardware/gobot-v1/wake-human';parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='model-export-',dir=parent) as directory:
            export=tf.keras.export.ExportArchive();export.track(streamed)
            export.add_endpoint('serve',streamed.call,input_signature=[tf.TensorSpec((1,3,40),tf.float32)])
            export.write_out(directory)
            converter=tf.lite.TFLiteConverter.from_saved_model(directory)
            converter.optimizations=[tf.lite.Optimize.DEFAULT];converter.target_spec.supported_ops=[tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
            converter._experimental_variable_quantization=True;converter.inference_input_type=tf.int8;converter.inference_output_type=tf.uint8
            def calibrate():
                c=x[:64].copy();c[0,0,:2]=[0,26]
                for sample in c:
                    for block in sample.reshape(-1,3,40):yield [block[np.newaxis]]
            converter.representative_dataset=calibrate;blob=converter.convert()
        path.with_name(ident+'-personal-model.dpapi').write_bytes(_dpapi(blob))
        report={'kind':'local_existing_microWakeWord_neural_adaptation','epochs':12,'seed':20261114,
            'training_utterances':8,'heldout_isolated_indices':[4,9],'question_phrases_used_for_training':False,
            'negative_training_source':'owner ordinary speech32..44s plus existing licensed '+('Denis/Dmitri' if balanced_replay else 'Denis')+' negatives',
            'synthetic_negative_clips':len(negative_paths),
            'balanced_synthetic_replay':balanced_replay,'synthetic_positive_clips':len(synthetic_positive),
            'model_sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob),'human_labels_verified':False,
            'product_accepted':False,'installed':False,'raw_or_features_exported':False,'retention_same_as_sample':True}
        path.with_name(ident+'-neural-pilot.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
    finally:
        raw[:]=bytes(len(raw))
        if pcm is not None:pcm.fill(0)
        if x is not None:x.fill(0)
        if 'clips' in locals():
            for c in clips:c.fill(0)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('sample_id');parser.add_argument('--balanced-replay',action='store_true');args=parser.parse_args();main(args.sample_id,args.balanced_replay)

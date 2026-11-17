"""Train a NEW real microWakeWord MixedNet for synthetic Russian Мо́ника on CPU.

Builds TF2.18 streaming model with 3x40 features per 30ms step; exports INT8
TFLite micro weights, no old GoBot weight reuse, no private speech.
Speaker-disjoint, manifested synthetic training/validation/test sources.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

os.environ.setdefault("CUDA_VISIBLE_DEVICES","-1")
os.environ.setdefault("TF_NUM_INTRAOP_THREADS","2")
os.environ.setdefault("TF_NUM_INTEROP_THREADS","2")
os.environ.setdefault("OMP_NUM_THREADS","2")
os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL","2")

import numpy as np
import tensorflow as tf
from pymicro_features import MicroFrontend
from scipy.signal import lfilter

from microwakeword.mixednet import model
from microwakeword.layers.modes import Modes
from microwakeword.utils import to_streaming_inference

SEED=20261117
FRAMES=204
STRIDE=3
BATCH=128
HOP=160
TRAIN=("denis","dmitri","espeak-ru","anna","irina")
VALID=("aleksandr",)
TEST=("elena",)

def features(audio:np.ndarray) -> np.ndarray:
    frontend=MicroFrontend()
    results=[]
    audio=np.asarray(np.clip(audio,-32768,32767),dtype="<i2")
    for offset in range(0,len(audio)-159,160):
        result=frontend.process_samples(audio[offset:offset+160].tobytes())
        if result.samples_read!=160:
            raise RuntimeError("Native microfrontend lost PCM samples")
        if result.features:
            results.append(result.features)
    arr=np.asarray(results,np.float32)
    if arr.ndim!=2 or arr.shape[1]!=40:
        raise ValueError("native_feature_shape_failed")
    return arr

def clips(folder:Path,kind:str,speaker:str):
    manifest=json.loads((folder/f"manifest-{kind}.json").read_text(encoding="utf8"))
    source=[]
    for entry in manifest:
        if entry["speaker"]!=speaker or entry["label"]!=kind or entry["synthetic"] is not True:
            raise ValueError("invalid_speaker_label_or_provenance")
        f=folder/entry["file"]
        if f.name!=entry["file"] or f.is_symlink():
            raise ValueError("untrusted_path")
        audio=f.read_bytes()
        if hashlib.sha256(audio).hexdigest()!=entry["sha256"]:
            raise ValueError("source_clip_corrupted")
        pcm=np.frombuffer(audio,dtype="<i2").astype(np.float32)
        if not len(pcm)==entry["samples"]:
            raise ValueError("clip_sample_count_mismatch")
        source.append(pcm)
    if not source:raise ValueError("no_synthetic_samples")
    return source

def augment(audio:np.ndarray | None,rng:np.random.Generator,positive:bool) -> np.ndarray:
    length=(FRAMES+2)*HOP
    floor=float(np.exp(rng.uniform(np.log(3),np.log(550))))
    noise=rng.normal(0,floor,length)
    noise+=.20*lfilter([1.],[1.,-.82],rng.normal(0,floor,length))
    if audio is not None:
        # Speed/pitch is randomized during TTS generation and speed/room
        # perturbation here is separate and CPU-only.
        speed=rng.uniform(.84,1.16)
        sample=np.interp(np.arange(0,len(audio),speed),np.arange(len(audio)),audio)
        filt=rng.uniform(.02,.55)
        sample=lfilter([1-filt],[1,-filt],sample)
        if len(sample)>length-800:
            if positive:
                sample=np.interp(
                    np.linspace(0,len(sample)-1,length-800),
                    np.arange(len(sample)),sample)
            else:
                start=int(rng.integers(0,len(sample)-length+801))
                sample=sample[start:start+length-800]
        # Simulate medium/far gain, mild echo and background/noise variation.
        sample=sample*rng.uniform(.18,1.55)
        echo=int(rng.integers(320,1850))
        reflected=np.pad(sample,(echo,0))[:len(sample)]*rng.uniform(0,.23)
        sample=sample+reflected
        slack=length-len(sample)
        if positive:
            # Anchor positive around the actual name onset, NOT the entire
            # question's end; keep all microphone samples of the first word.
            left=int(rng.integers(max(0,slack-6400),slack+1))
        else:
            left=int(rng.integers(0,slack+1))
        noise[left:left+len(sample)]+=sample
    return features(noise)[-FRAMES:]

def feature_dataset(root:Path,speakers:tuple,count:int,seed:int,output:Path):
    rng=np.random.default_rng(seed)
    groups={}
    for speaker in speakers:
        folder=root/speaker
        groups[speaker]={
            0:clips(folder,"negative",speaker),
            1:clips(folder,"positive",speaker)
        }
    y=np.arange(count)%2
    rng.shuffle(y)
    x=np.lib.format.open_memmap(output,mode="w+",dtype=np.float16,
                                shape=(count,FRAMES,40))
    for i,label in enumerate(y):
        speaker=speakers[i%len(speakers)]
        bank=groups[speaker][int(label)]
        # Exhaustive cycling plus augmentation of pre-generated source clips;
        # underlying source files are never re-generated/mutated by this run.
        idx=int(rng.integers(len(bank)))
        audio=bank[idx]
        if not label and rng.random()<.13:
            audio=None  # genuine no-word noise hard negative
        x[i]=augment(audio,rng,bool(label))
        if (i+1)%512==0:
            print(json.dumps({"phase":"features","file":output.name,
                              "prepared":i+1,"total":count}),flush=True)
    x.flush()
    np.save(output.with_suffix(".labels.npy"),y.astype(np.float32))
    return x,y.astype(np.float32)

def probability_bce(net,x,y):
    result=[]
    for i in range(0,len(y),BATCH):
        batch=np.asarray(x[i:i+BATCH],np.float32)
        if len(batch)!=BATCH:
            raise ValueError("must_evaluate_full_fixed_batches")
        result.append(np.asarray(net(batch,training=False)).reshape(-1))
    probs=np.concatenate(result)
    p=np.clip(probs,1e-7,1-1e-7)
    return float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p)))

def export(net,x,out:Path):
    streamed=to_streaming_inference(net,
        {"spectrogram_length":FRAMES,"features_length":FRAMES,"stride":STRIDE},
        mode=Modes.STREAM_INTERNAL_STATE_INFERENCE)
    if tuple(streamed.input_shape)!=(1,STRIDE,40):
        raise ValueError("stream_model_shape_invalid")
    archive=tf.keras.export.ExportArchive()
    archive.track(streamed)
    archive.add_endpoint("serve",streamed.call,
        input_signature=[tf.TensorSpec((1,STRIDE,40),tf.float32)])
    archive.write_out(str(out/"saved"))
    converter=tf.lite.TFLiteConverter.from_saved_model(str(out/"saved"))
    converter.optimizations=[tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_ops=[tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter._experimental_variable_quantization=True
    converter.inference_input_type=tf.int8
    converter.inference_output_type=tf.uint8
    def cal():
        for i in range(min(128,len(x))):
            wav=np.asarray(x[i],dtype=np.float32)
            if i==0:wav[0,0:2]=[0,26]
            for block in wav.reshape(-1,STRIDE,40):
                yield [block[None]]
    converter.representative_dataset=cal
    blob=converter.convert()
    p=out/"monika_int8.tflite"
    p.write_bytes(blob)
    ref=tf.lite.Interpreter(model_content=blob,num_threads=1,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    ref.allocate_tensors()
    a,b=ref.get_input_details()[0],ref.get_output_details()[0]
    if tuple(a["shape"])!=(1,3,40) or a["dtype"]!=np.int8 \
            or tuple(b["shape"])!=(1,1) or b["dtype"]!=np.uint8:
        raise RuntimeError("int8_streaming_export_not_native_compatible")
    metadata={"schema":"monika_mww_int8_v1","target":"Мо́ника","trained":True,
        "synthetic_only":True,"owner_audio":False,"paid_calls":0,
        "model_sha256":hashlib.sha256(blob).hexdigest(),"bytes":len(blob),
        "context_frames":FRAMES,"feature_step_size_ms":10,"inference_stride_frames":3,
        "input_quantization":a["quantization"],
        "output_quantization":b["quantization"],
        "model_ops":sorted({v["op_name"] for v in ref._get_ops_details()}),
        "initial_probability_cutoff":0.9,"initial_sliding_window_average_size":5,
        "arena_bytes_unmeasured_on_board":True,
        "human_accepted":False,"board_installed":False}
    (out/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    print("INT8_TFLITE_STREAMING_EXPORT_OK",json.dumps(metadata,ensure_ascii=False),flush=True)
    return metadata

def train(corpus:Path,out:Path,steps:int,windows:int):
    for name in (TRAIN,VALID,TEST):
        if not name:raise ValueError("no_speakers")
    if set(TRAIN)&set(VALID+TEST) or set(VALID)&set(TEST):
        raise ValueError("speaker_leakage")
    if out.exists():raise ValueError("never_overwrite_previous_model")
    out.mkdir(parents=True)
    tf.config.set_visible_devices([],"GPU")
    tf.keras.utils.set_random_seed(SEED)
    tf.config.experimental.enable_op_determinism()
    x,y=feature_dataset(corpus,TRAIN,windows,SEED,out/"train.npy")
    val,labels=feature_dataset(corpus,VALID,512,SEED+1,out/"val.npy")
    # Keep the TEST speaker entirely out of training and selection;
    # separate scorer consumes her PCM only AFTER exported checkpoint.
    flags=SimpleNamespace(
        pointwise_filters="48,48,48,48",
        repeat_in_block="1,1,1,1",
        mixconv_kernel_sizes="[5],[7,11],[9,15],[23]",
        residual_connection="0,0,0,0",
        first_conv_filters=24,first_conv_kernel_size=5,
        stride=STRIDE,max_pool=False,pooled=False,spatial_attention=False,
    )
    net=model(flags,(FRAMES,40),BATCH)
    net.compile(optimizer=tf.keras.optimizers.Adam(.0008),
                loss="binary_crossentropy")
    rng=np.random.default_rng(SEED+2)
    history=[]
    initial=probability_bce(net,val,labels)
    best=float("inf")
    start=time.monotonic()
    for step in range(steps):
        idx=rng.integers(0,len(y),BATCH)
        batch=np.asarray(x[idx],np.float32).copy()
        # SpecAugment, including confusable negatives.
        for sample in batch:
            if rng.random()<.7:
                w=int(rng.integers(1,7))
                at=int(rng.integers(0,FRAMES-w+1))
                sample[at:at+w]=0
            if rng.random()<.5:
                w=int(rng.integers(1,4))
                at=int(rng.integers(0,40-w+1))
                sample[:,at:at+w]=0
        loss=net.train_on_batch(batch,y[idx],
            sample_weight=np.where(y[idx]>0.5,1.2,1.8).astype(np.float32))
        if (step+1)%100==0:
            print(json.dumps({"step":step+1,"total_steps":steps,
                             "training_loss":float(loss),
                             "elapsed_s":round(time.monotonic()-start,1)}),flush=True)
        if (step+1)%250==0 or step+1==steps:
            metric=probability_bce(net,val,labels)
            row={"step":step+1,"val_bce":metric,"train_loss":float(loss)}
            history.append(row)
            if np.isfinite(metric) and metric<best:
                best=metric
                net.save_weights(out/"best.weights.h5")
            (out/"history.json").write_text(json.dumps(history,indent=2))
            print("VALIDATION_CHECKPOINT",json.dumps(row),flush=True)
    if not np.isfinite(best) or not (out/"best.weights.h5").is_file():
        raise RuntimeError("no_trained_finite_checkpoint")
    net.load_weights(out/"best.weights.h5")
    info={"seed":SEED,"train_speakers":TRAIN,"validation_speakers":VALID,
          "test_speakers":TEST,"initial_validation_bce":initial,
          "best_validation_bce":best,
          "selected_step":min(history,key=lambda v:v["val_bce"])["step"],
          "steps":steps,"train_augmented_windows":windows,"validation_windows":512,
          "architecture":"official_microWakeWord_MixedNet","cpu_only":True,
          "elapsed_training_s":round(time.monotonic()-start,2),
          "no_old_model_weights_reused":True}
    (out/"training_selection.json").write_text(json.dumps(info,indent=2))
    print("CHECKPOINT_SELECTED",json.dumps(info),flush=True)
    export(net,x,out)
    print("TRAINING_AND_STREAMING_EXPORT_FINISHED",flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--corpus",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--steps",type=int,default=1500)
    p.add_argument("--windows",type=int,default=8192)
    args=p.parse_args()
    if not 250<=args.steps<=5000 or not 2048<=args.windows<=20000 or args.windows%128:
        p.error("CPU-only fixed bounded training settings required")
    train(args.corpus,args.output,args.steps,args.windows)

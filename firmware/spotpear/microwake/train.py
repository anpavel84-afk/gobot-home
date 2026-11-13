"""CPU pilot: real microWakeWord MixedNet, native streaming state, integer-only export."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import tensorflow as tf
from scipy.signal import lfilter
from pymicro_features import MicroFrontend
from microwakeword.mixednet import model
from microwakeword.layers.modes import Modes
from microwakeword.utils import to_streaming_inference

SEED = 7611
FRAMES = 75
STRIDE = 3
BATCH = 32
HOP = 160
def features(audio):
    frontend = MicroFrontend()
    rows = []
    for offset in range(0, len(audio) - HOP + 1, HOP):
        result = frontend.process_samples(audio[offset:offset + HOP].astype("<i2").tobytes())
        if result.samples_read != HOP:
            raise RuntimeError("Frontend dropped PCM")
        if result.features:
            rows.append(result.features)
    return np.array(rows, np.float32)

def channel(raw, rng):
    speed = rng.uniform(.77, 1.25)
    raw = np.interp(np.arange(0, len(raw), speed), np.arange(len(raw)), raw)
    visible = np.where(abs(raw) > max(20, np.max(abs(raw)) * .025))[0]
    if visible.size:
        raw = raw[max(0, visible[0]-160):visible[-1]+321]
    room = rng.integers(160, 1200)
    raw = np.pad(raw, (0, room)) + rng.uniform(0, .35) * np.pad(raw, (room, 0))
    filt = rng.uniform(0, .75)
    raw = lfilter([1-filt], [1, -filt], raw)
    return raw * rng.uniform(.11, 1.4)

def window(clip, rng, positive):
    total = (FRAMES + 2) * HOP
    floor = rng.uniform(0, 90)
    noise = rng.normal(0, floor, total)
    if clip is not None:
        sample = channel(clip, rng)
        if len(sample) > total:
            start = len(sample) - total if positive else rng.integers(0, len(sample)-total+1)
            sample = sample[start:start+total]
        gap = total - len(sample)
        left = rng.integers(max(0,gap-4000), gap+1)
        noise[left:left+len(sample)] += sample
    warmup = rng.normal(0, floor, HOP * rng.integers(35, 200))
    return features(np.clip(np.concatenate([warmup,noise]), -32768, 32767))[-FRAMES:]

def dataset(folder, count, seed, positive_fraction=.5):
    rng = np.random.default_rng(seed)
    positives = [np.fromfile(p, "<i2") for p in sorted(folder.glob("positive-*.pcm"))]
    negatives = [np.fromfile(p, "<i2") for p in sorted(folder.glob("negative-*.pcm"))]
    if not positives or not negatives:
        raise ValueError(f"Missing corpus {folder}")
    ys = rng.integers(0, 2, count) if positive_fraction==.5 else (rng.random(count)<positive_fraction).astype(np.int32)
    xs = []
    for y in ys:
        group = positives if y else negatives
        sample = group[rng.integers(len(group))]
        if not y and rng.random() < .13:
            sample = None
        xs.append(window(sample, rng, y))
    return np.stack(xs), ys.astype(np.float32)

def main(corpus, output, mined=None, robust=False,frames=75,positive_fraction=.5,negative_weight=1.):
    global FRAMES
    if frames<75 or frames>150 or frames%STRIDE or not 0<positive_fraction<=.5 or not 1<=negative_weight<=10:
        raise ValueError('Unbounded training profile')
    FRAMES=frames
    output.mkdir(parents=True, exist_ok=True)
    tf.keras.utils.set_random_seed(SEED)
    tf.config.experimental.enable_op_determinism()
    train_sets = [dataset(corpus / speaker, 3072, SEED+i*37,positive_fraction) for i,speaker in enumerate(("denis","espeak-ru","anna","aleksandr"))]
    x,y = (np.concatenate(parts) for parts in zip(*train_sets))
    if mined is not None:
        negatives=np.load(mined,allow_pickle=False)
        if negatives.shape[1]<FRAMES:
            negatives=np.pad(negatives,((0,0),(FRAMES-negatives.shape[1],0),(0,0)),mode='edge')
        x=np.concatenate((x, negatives[:len(negatives)//BATCH*BATCH]))
        y=np.pad(y,(0,len(x)-len(y)))
    val,labels = dataset(corpus / "dmitri", 512, SEED+1,positive_fraction)
    flags = SimpleNamespace(pointwise_filters="24,24,24", repeat_in_block="1,1,1",
        mixconv_kernel_sizes="[3],[5],[7]", residual_connection="0,0,0", first_conv_filters=24,
        first_conv_kernel_size=3, stride=STRIDE, max_pool=False, pooled=True, spatial_attention=False)
    if robust:
        flags.pointwise_filters="40,40,40"
        flags.first_conv_filters=40
        flags.mixconv_kernel_sizes="[3],[5],[9]"
    net = model(flags, (FRAMES,40), BATCH)
    net.compile(optimizer=tf.keras.optimizers.Adam(.0015), loss="binary_crossentropy", metrics=["accuracy"])
    # Fixed batch size is part of the upstream training architecture.
    rng = np.random.default_rng(SEED)
    best = float("inf")
    report = []
    for epoch in range(40):
        indices = rng.permutation(len(x))
        net.reset_metrics()
        for batch in indices.reshape(-1,BATCH):
            samples=x[batch].copy()
            if robust:
                # Simulate smooth spectral tilt, shifted formants and imperfect mic response.
                bins=np.arange(40)
                for j in range(len(samples)):
                    pos=np.clip(bins*rng.uniform(.91,1.10)+rng.uniform(-1,1),0,39)
                    left=pos.astype(int)
                    weight=(pos-left)[None,:]
                    samples[j]=samples[j][:,left]*(1-weight)+samples[j][:,np.minimum(39,left+1)]*weight
                    samples[j]*=np.linspace(rng.uniform(.85,1.15),rng.uniform(.85,1.15),40)
                    if rng.random()<.4:
                        at=rng.integers(1,37)
                        samples[j,:,at:at+2]=0
            if negative_weight==1:net.train_on_batch(samples, y[batch])
            else:net.train_on_batch(samples,y[batch],sample_weight=np.where(y[batch]>.5,1.,negative_weight).astype(np.float32))
        net.reset_metrics()
        if robust:
            probs=np.concatenate([net(val[b:b+BATCH],training=False).numpy().ravel()
                                  for b in range(0,len(val),BATCH)])
            clipped=np.clip(probs,1e-7,1-1e-7)
            scores={"loss":-np.mean(labels*np.log(clipped)+(1-labels)*np.log1p(-clipped)),
                    "accuracy":np.mean((probs>=.5)==labels)}
        else:
            for batch in np.arange(len(val)).reshape(-1,BATCH):
                scores = net.test_on_batch(val[batch],labels[batch],return_dict=True)
        loss = float(scores["loss"])
        report.append(dict(epoch=epoch+1, validation_loss=loss, validation_accuracy=float(scores["accuracy"])))
        if loss < best:
            best = loss
            net.save_weights(output / "best.weights.h5")
    net.load_weights(output / "best.weights.h5")
    (output / "history.json").write_text(json.dumps(report))
    streamed = to_streaming_inference(net, dict(spectrogram_length=FRAMES,features_length=FRAMES,stride=STRIDE),
                                     mode=Modes.STREAM_INTERNAL_STATE_INFERENCE)
    if tuple(streamed.input_shape) != (1,STRIDE,40):
        raise ValueError(streamed.input_shape)
    export = tf.keras.export.ExportArchive()
    export.track(streamed)
    export.add_endpoint("serve", streamed.call, input_signature=[tf.TensorSpec((1,STRIDE,40),tf.float32)])
    export.write_out(str(output / "saved"))
    def calibrate():
        calibration = x[:64].copy()
        calibration[0,0,:2] = [0,26]
        for sample in calibration:
            for block in sample.reshape(-1,STRIDE,40):
                yield [block[np.newaxis]]
    conv = tf.lite.TFLiteConverter.from_saved_model(str(output / "saved"))
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv._experimental_variable_quantization = True
    conv.inference_input_type, conv.inference_output_type = tf.int8, tf.uint8
    conv.representative_dataset = calibrate
    blob = conv.convert()
    interp = tf.lite.Interpreter(model_content=blob)
    interp.allocate_tensors()
    inp,out = interp.get_input_details()[0],interp.get_output_details()[0]
    assert tuple(inp["shape"]) == (1,STRIDE,40) and inp["dtype"] == np.int8
    assert tuple(out["shape"]) == (1,1) and out["dtype"] == np.uint8
    (output / "gobot.tflite").write_bytes(blob)
    metadata = dict(sha256=hashlib.sha256(blob).hexdigest(), bytes=len(blob), train=["denis","espeak-ru","anna","aleksandr"], validation="dmitri",
                    test="elena", input_quantization=inp["quantization"], output_quantization=out["quantization"],
                    ops=sorted(set(op["op_name"] for op in interp._get_ops_details())), human_trials=0)
    metadata.update(context_frames=FRAMES,positive_fraction=positive_fraction,negative_weight=negative_weight)
    (output / "model.json").write_text(json.dumps(metadata, indent=2))
if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("corpus",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--mined",type=Path)
    p.add_argument("--robust",action="store_true")
    p.add_argument('--frames',type=int,default=75)
    p.add_argument('--positive-fraction',type=float,default=.5)
    p.add_argument('--negative-weight',type=float,default=1.)
    a=p.parse_args()
    main(a.corpus,a.output,a.mined,a.robust,a.frames,a.positive_fraction,a.negative_weight)

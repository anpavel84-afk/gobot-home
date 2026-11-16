"""One bounded PUBLIC-only correction using continuous TRAIN negative windows."""
import argparse,hashlib,json,time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import train_reference as reference
import tensorflow as tf
from microwakeword.mixednet import model
from public_data_scope import public_training_scope


def validate_sources(source,hard):
    config=json.loads((source/'config.json').read_text());meta=json.loads(hard.with_suffix('.json').read_text())
    train=['denis','dmitri','espeak-ru','anna','irina']
    if not public_training_scope(config) or config.get('training_speakers')!=train or config.get('alias_positive_total')!=1000 or meta.get('training_speakers')!=train or set(meta.get('excluded_speakers',[]))!={'aleksandr','elena'} or meta.get('synthetic_only') is not True or meta.get('kernel_baseline')!='native_reference' or meta.get('stream_offline_alignment_frames')!=1:raise ValueError('Public correction split mismatch')
    if hashlib.sha256(hard.read_bytes()).hexdigest()!=meta.get('sha256'):raise ValueError('Changed negative windows')
    model_meta=json.loads((source/'model.json').read_text())
    if meta.get('source_model_sha256')!=model_meta['sha256'] or hashlib.sha256((source/'gobot.tflite').read_bytes()).hexdigest()!=model_meta['sha256']:raise ValueError('Changed public teacher')
    return config,meta


def alias_indices(labels):
    rng=np.random.default_rng(reference.SEED);expected=np.arange(102000)%2;rng.shuffle(expected)
    if len(labels)<len(expected) or not np.array_equal(labels[:len(expected)],expected) or np.any(labels[len(expected):]!=0):raise ValueError('Alias feature schedule changed')
    schedule=reference.source_schedule({0:range(10000),1:range(51000)},102000,rng)
    result=np.flatnonzero(labels==1)[schedule[1]%10200>=10000]
    if len(result)!=1000:raise ValueError('Alias source count mismatch')
    return result


def main(source,hard,out,alias_balanced=False,phonetic_replay=None):
    config,meta=validate_sources(source,hard);out.mkdir();rng=np.random.default_rng(20261120)
    features_path=source/('combined-features.npy' if config.get('public_human_negative_training') else 'train-features.npy')
    x=np.load(features_path,mmap_mode='r');y=np.load(source/'train-labels.npy')
    h=np.load(hard,mmap_mode='r')
    count=config.get('total_training_windows',102000)
    if not 102000<=count<=122000 or x.shape!=(count,204,40) or y.shape!=(count,) or h.ndim!=3 or h.shape[1:]!=(204,40) or not 100<=len(h)<=20000:raise ValueError('Invalid correction shape')
    positive=np.flatnonzero(y==1);negative=np.flatnonzero(y==0);order=rng.permutation(len(h));cut=max(1,len(h)//10)
    aliases=alias_indices(y) if alias_balanced else None
    if alias_balanced and (meta.get('complete_train_negative_coverage') is not True or meta.get('source_negative_clips')!=10000):raise ValueError('Balanced correction requires complete TRAIN negatives')
    heldout=order[:cut];train=order[cut:]
    paired=None;pair_validation=None
    if phonetic_replay:
        info=json.loads(phonetic_replay.with_suffix('.json').read_text())
        if info.get('schema')!='public-whole-partial-replay-v1' or info.get('synthetic_only') is not True or info.get('training_speakers')!=config['training_speakers'] or set(info.get('excluded_speakers',[]))!={'aleksandr','elena'} or info.get('corpus_manifest_sha256')!=config['corpus_manifest_sha256'] or hashlib.sha256(phonetic_replay.read_bytes()).hexdigest()!=info.get('sha256'):raise ValueError('Invalid public phonetic replay')
        paired=np.load(phonetic_replay,mmap_mode='r');groups=np.asarray(info['validation_groups'])
        if paired.shape!=(8000,204,40) or paired.dtype!=np.float16 or len(groups)!=200 or len(np.unique(groups))!=200 or np.any(groups<0) or np.any(groups>=2000):raise ValueError('Invalid phonetic split')
        rows=np.arange(8000);pair_validation=np.flatnonzero(np.isin(rows//4,groups));pair_training=~np.isin(rows//4,groups)
        pair_alias=rows[pair_training & (rows%2==0) & (rows//4<1000)]
        pair_normal=rows[pair_training & (rows%2==0) & (rows//4>=1000)]
        pair_negative=rows[pair_training & (rows%2==1)]
    val=np.load(source/'validation-features.npy',mmap_mode='r');labels=np.arange(1024)%2;np.random.default_rng(reference.SEED+1).shuffle(labels)
    tf.keras.utils.set_random_seed(20261120)
    flags=SimpleNamespace(pointwise_filters='64,64,64,64',repeat_in_block='1,1,1,1',mixconv_kernel_sizes='[5],[7,11],[9,15],[23]',residual_connection='0,0,0,0',first_conv_filters=32,first_conv_kernel_size=5,stride=3,max_pool=False,pooled=False,spatial_attention=False)
    net=model(flags,(204,40),128);net.load_weights(source/'best.weights.h5')
    net.compile(optimizer=tf.keras.optimizers.Adam(.0001),loss='binary_crossentropy')
    config={**config,'correction':'public continuous TRAIN negatives','alias_balanced_batches':alias_balanced,'steps':3000,'learning_rate':.0001,'positive_weight':1.5,'negative_weight':2.,'hard_windows':len(h),'hard_train_windows':len(train),'hard_validation_windows':len(heldout),'hard_sha256':meta['sha256'],'initial_public_weights_sha256':hashlib.sha256((source/'best.weights.h5').read_bytes()).hexdigest(),'source_waveform_counts_unchanged':True}
    if phonetic_replay:config.update(phonetic_replay_sha256=info['sha256'],phonetic_validation_split='source clip',positive_name_end_context_ms=600,quiet_positive_replay=True,additional_phonetic_windows=8000)
    (out/'config.json').write_text(json.dumps(config,indent=2))
    def predict(data):
        values=[]
        for at in range(0,len(data),128):
            part=np.asarray(data[at:at+128],np.float32);n=len(part);part=np.pad(part,((0,128-n),(0,0),(0,0)))
            values.extend(np.asarray(net(part,training=False)).reshape(-1)[:n])
        return np.clip(np.array(values),1e-7,1-1e-7)
    def metric():
        p=predict(val);bce=float(-np.mean(labels*np.log(p)+(1-labels)*np.log1p(-p)))
        q=predict(h[heldout]);negative_bce=float(-np.mean(np.log1p(-q)))
        details={'validation_bce':bce,'continuous_train_holdout_bce':negative_bce};value=bce+negative_bce
        if paired is not None:
            targets=1-pair_validation%2;p=predict(paired[pair_validation]);paired_bce=float(-np.mean(targets*np.log(p)+(1-targets)*np.log1p(-p)))
            value+=paired_bce;details['phonetic_source_holdout_bce']=paired_bce
        return value,details
    initial,details=metric();history=[{'step':0,'selection_loss':initial,**details}];best=float('inf');started=time.monotonic()
    for step in range(3000):
        if time.monotonic()-started>3600:raise RuntimeError('Correction training time limit')
        if paired is not None:
            ids=np.concatenate([rng.choice(positive,32),rng.choice(negative,32)])
            pair_ids=np.concatenate([rng.choice(pair_alias,16),rng.choice(pair_normal,16),rng.choice(pair_negative,16)])
            batch=np.concatenate([np.asarray(x[ids],np.float32),np.asarray(paired[pair_ids],np.float32),np.asarray(h[rng.choice(train,16)],np.float32)])
            targets=np.concatenate([y[ids],1-pair_ids%2,np.zeros(16)])
        else:
            ids=np.concatenate([rng.choice(positive,32),rng.choice(aliases,32),rng.choice(negative,32)]) if alias_balanced else np.concatenate([rng.choice(positive,32),rng.choice(negative,32)])
            hard_count=128-len(ids)
            batch=np.concatenate([np.asarray(x[ids],np.float32),np.asarray(h[rng.choice(train,hard_count)],np.float32)]);targets=np.concatenate([y[ids],np.zeros(hard_count)])
        loss=net.train_on_batch(batch,targets,sample_weight=np.where(targets>.5,1.5,2.).astype(np.float32))
        if (step+1)%100==0:print(json.dumps({'step':step+1,'steps':3000,'loss':float(loss)}),flush=True)
        if (step+1)%500==0:
            value,details=metric();history.append({'step':step+1,'selection_loss':value,**details})
            if value<best:best=value;net.save_weights(out/'best.weights.h5')
            (out/'history.json').write_text(json.dumps(history,indent=2))
    selected=min(history[1:],key=lambda row:row['selection_loss']);(out/'selection.json').write_text(json.dumps({'selected':selected,'initial':history[0],'accepted':False}))
    net.load_weights(out/'best.weights.h5');reference.export_stream(net,x,out,started)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','hard','output'):p.add_argument(key,type=Path)
    p.add_argument('--alias-balanced',action='store_true');p.add_argument('--phonetic-replay',type=Path);a=p.parse_args();main(a.source,a.hard,a.output,a.alias_balanced,a.phonetic_replay)

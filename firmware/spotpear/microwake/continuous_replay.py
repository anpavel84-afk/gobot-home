"""Retain frontend history in local training windows, without saving features."""
import numpy as np

def training_audio(pcm,positives,heldout_questions,rate=16000):
    """Exclude holdouts before the adaptive frontend, not just after it."""
    result=pcm.copy()
    for a,b in [positives[4],positives[9],*heldout_questions]:
        result[max(0,int(a*rate)):min(len(result),int(np.ceil(b*rate)))]=0
    return result

def windows(rows,positives,negatives,rng,count=512,frames=75):
    train_ids=[i for i in range(10) if i not in {4,9}]
    ends=[]
    for a,b in negatives:
        lo=int(np.ceil(a*100))+frames
        hi=int(np.floor(b*100))-2
        if hi>=lo:ends.extend(range(lo,hi+1))
    if not ends:raise ValueError('No complete negative window without label crossover')
    # A longer receptive field must not silently pull held-out utterance audio
    # into the context of a later training example.
    heldout=[(int(a*100)-2,int(np.ceil(b*100))) for a,b in (positives[4],positives[9])]
    positive_ends=[]
    for index in train_ids:
        a,b=positives[index]
        for shift in range(-4,4):
            end=int(b*100)-2+shift
            if end<frames or end>len(rows):continue
            if any(max(end-frames,left)<min(end,right) for left,right in heldout):continue
            positive_ends.append(end)
    if not positive_ends:raise ValueError('No positive context without holdout leakage')
    positive=[];negative=[]
    for i in range(count):
        end=int(positive_ends[int(rng.integers(len(positive_ends)))])
        positive.append(rows[end-frames:end].copy())
        end=int(ends[int(rng.integers(len(ends)))])
        if end>len(rows):raise ValueError('Negative window outside sample')
        negative.append(rows[end-frames:end].copy())
    return positive,negative

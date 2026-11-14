"""Retain frontend history in local training windows, without saving features."""
import numpy as np

def windows(rows,positives,negatives,rng,count=512,frames=75):
    train_ids=[i for i in range(10) if i not in {4,9}]
    ends=[]
    for a,b in negatives:
        lo=int(np.ceil(a*100))+frames
        hi=int(np.floor(b*100))-2
        if hi>=lo:ends.extend(range(lo,hi+1))
    if not ends:raise ValueError('No complete negative window without label crossover')
    positive=[];negative=[]
    for i in range(count):
        a,b=positives[train_ids[i%len(train_ids)]]
        end=int(b*100)-2+int(rng.integers(-4,4))
        if end<frames or end>len(rows):raise ValueError('Positive window outside sample')
        positive.append(rows[end-frames:end].copy())
        end=int(ends[int(rng.integers(len(ends)))])
        if end>len(rows):raise ValueError('Negative window outside sample')
        negative.append(rows[end-frames:end].copy())
    return positive,negative

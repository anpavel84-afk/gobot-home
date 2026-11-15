"""Positive KWS examples must retain the complete activation word."""
import numpy as np

def trim_background(sample,retain_full=False):
    # A low-energy final consonant must never be removed from a positive label.
    if retain_full or not len(sample):return sample
    visible=np.flatnonzero(np.abs(sample)>max(20,np.max(np.abs(sample))*.025))
    return sample[max(0,visible[0]-160):visible[-1]+321] if len(visible) else sample

def fit_positive(sample,limit):
    if limit<2:raise ValueError('Positive window must hold both endpoints')
    if len(sample)<=limit:return sample
    # Time-compress a long augmentation, never delete its first phonemes.
    return np.interp(np.linspace(0,len(sample)-1,limit),np.arange(len(sample)),sample)

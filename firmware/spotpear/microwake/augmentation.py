"""Positive KWS examples must retain the complete activation word."""
import numpy as np

def fit_positive(sample,limit):
    if limit<2:raise ValueError('Positive window must hold both endpoints')
    if len(sample)<=limit:return sample
    # Time-compress a long augmentation, never delete its first phonemes.
    return np.interp(np.linspace(0,len(sample)-1,limit),np.arange(len(sample)),sample)

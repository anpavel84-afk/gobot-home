"""Initialize upstream MixedNet's nonpooled head equivalently to average pooling."""
import numpy as np

def initialize(target,pooled):
    source=[layer for layer in pooled.layers[:-1] if layer.get_weights()]
    dest=[layer for layer in target.layers[:-1] if layer.get_weights()]
    if len(source)!=len(dest):raise ValueError('Unexpected MixedNet feature stack')
    for a,b in zip(source,dest):
        if type(a).__name__!=type(b).__name__ or [w.shape for w in a.get_weights()]!=[w.shape for w in b.get_weights()]:
            raise ValueError('Feature stack mismatch')
        b.set_weights(a.get_weights())
    kernel,bias=pooled.layers[-1].get_weights();new_kernel,new_bias=target.layers[-1].get_weights()
    if new_kernel.shape[1:]!=kernel.shape[1:] or new_kernel.shape[0]%kernel.shape[0] or bias.shape!=new_bias.shape:
        raise ValueError('Unsupported temporal head layout')
    count=new_kernel.shape[0]//kernel.shape[0]
    target.layers[-1].set_weights([np.tile(kernel,(count,1))/count,bias])
    return count

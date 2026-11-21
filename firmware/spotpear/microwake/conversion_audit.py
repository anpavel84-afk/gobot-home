"""PLAN-only float/INT8 streaming diagnostic, using in-memory sample clips."""
import numpy as np

def offline_probes(net,pcm,plan,features,frames=75,batch=32):
    intervals=[('heldout',plan['positive_segments'][i]) for i in [4,9]]
    intervals += [('negative',pair) for pair in plan['negative_segments']]
    result=[]
    for kind,(a,b) in intervals:
        signal=np.concatenate([np.zeros(24000,np.int16),pcm[int(a*16000):int(b*16000)],np.zeros(24000,np.int16)])
        rows=features(signal);xs=np.stack([rows[end-frames:end] for end in range(frames,len(rows)+1,3)])
        values=[]
        for i in range(0,len(xs),batch):
            part=xs[i:i+batch];padded=np.pad(part,((0,batch-len(part)),(0,0),(0,0)))
            values.extend(np.asarray(net(padded,training=False)).reshape(-1)[:len(part)].tolist());padded.fill(0)
        result.append({'kind':kind,'offline_peak':round(float(max(values,default=0))*255,2)})
        signal.fill(0);rows.fill(0);xs.fill(0)
    return result

def audit(tf,float_blob,int_blob,pcm,plan,features):
    result=[]
    intervals=[('heldout',plan['positive_segments'][i]) for i in [4,9]]
    intervals += [('negative',pair) for pair in plan['negative_segments']]
    for kind,(a,b) in intervals:
        signal=np.concatenate([np.zeros(24000,np.int16),pcm[int(a*16000):int(b*16000)],np.zeros(24000,np.int16)])
        rows=features(signal);entry={'kind':kind}
        for name,blob in [('float',float_blob),('int8',int_blob)]:
            runtime=tf.lite.Interpreter(model_content=blob,num_threads=1,experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
            runtime.allocate_tensors();inp=runtime.get_input_details()[0];out=runtime.get_output_details()[0];scores=[]
            for i in range(0,len(rows)-2,3):
                q=rows[None,i:i+3]
                if inp['dtype']==np.int8:q=np.clip(np.rint(q/inp['quantization'][0])+inp['quantization'][1],-128,127).astype(np.int8)
                runtime.set_tensor(inp['index'],q);runtime.invoke();v=float(runtime.get_tensor(out['index'])[0,0])
                scores.append(v if out['dtype']==np.uint8 else v*255)
            smooth=np.convolve(scores,np.ones(3)/3,mode='valid')[24:]
            entry[name+'_peak']=round(float(max(smooth,default=0)),2)
            entry[name+'_detected']=bool(any(smooth>=250))
        result.append(entry);signal.fill(0);rows.fill(0)
    return {'independent_acceptance':False,'fresh_runtime_per_interval':True,'padding':'synthetic_zero_context_not_natural_room_silence','probes':result}

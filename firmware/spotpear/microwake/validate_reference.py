"""Fixed-policy streaming evaluation of public-only reference checkpoints.

Validation/test speakers follow the saved split; no threshold sweep, training,
personal audio, paid service, firmware admission or remote provider access.
"""
import argparse
import hashlib
import json
from pathlib import Path
from evaluate import traces,score
from train_reference import files


def main(corpus,output,kernel='desktop_optimized',alias_validation=None):
    config=json.loads((output/'config.json').read_text())
    if config.get('alias_positive_total') and not alias_validation:raise ValueError('Alias-trained model requires held-out alias evaluation')
    metadata=json.loads((output/'model.json').read_text())
    selected=json.loads((output/'selection.json').read_text())
    if selected['selected']['step']<=0:raise ValueError('Untrained checkpoint')
    if config['human_training'] is not False:raise ValueError('Public-only evaluator')
    if hashlib.sha256((output/'gobot.tflite').read_bytes()).hexdigest()!=metadata['sha256']:raise ValueError('Model hash mismatch')
    train=set(config['training_speakers']);validation=set(config['validation_speakers']);test=set(config['test_speakers'])
    if train&validation or train&test or validation&test:raise ValueError('Speaker split leakage')
    result={'sha256':metadata['sha256'],'window':10,'cutoff':231,'warmup':68,'validation':{},'test':{},
        'human_trials':0,'installed':False,'product_accepted':False,'paid_calls':0,'kernel_baseline':kernel}
    for category,speakers in [('validation',sorted(validation)),('test',sorted(test))]:
        files(corpus,tuple(speakers),(498,75) if config.get('expanded_utterance_corpus') else (198,15))
        for speaker in speakers:
            metric=score(traces(output/'gobot.tflite',corpus/speaker,20261114,kernel=kernel),231,window=10,warmup=68)
            result[category][speaker]=metric
            print(json.dumps({'split':category,'speaker':speaker,**{k:v for k,v in metric.items() if k!='mistakes'}}),flush=True)
    metrics=[value for group in ('validation','test') for value in result[group].values()]
    if alias_validation:
        provenance=json.loads((alias_validation/'provenance.json').read_text())
        if provenance.get('evaluation_only') is not True or provenance.get('synthetic_only') is not True or set(provenance['speakers'])!=validation|test or set(provenance['excluded_training_speakers'])!=train:raise ValueError('Alias validation split mismatch')
        result['alias_validation']={}
        for speaker in sorted(validation|test):
            files(alias_validation,(speaker,),(0,20))
            metric=score(traces(output/'gobot.tflite',alias_validation/speaker,20261115,kernel=kernel),231,window=10,warmup=68)
            result['alias_validation'][speaker]=metric;metrics.append(metric)
            print(json.dumps({'alias_heldout':speaker,**{k:v for k,v in metric.items() if k!='mistakes'}}),flush=True)
    result['candidate_passed']=all(item['tp']>=.9*item['positive'] and item['false_events']==0 for item in metrics)
    name='stream-reference-report.json' if kernel=='native_reference' else 'stream-report.json'
    (output/name).write_text(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('corpus',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--kernel',choices=['desktop_optimized','native_reference'],default='desktop_optimized')
    parser.add_argument('--alias-validation',type=Path)
    args=parser.parse_args();main(args.corpus,args.output,args.kernel,args.alias_validation)

"""Validate explicitly reviewed LOCAL timing hypotheses; never call them truth."""
import math

def validate(plan,seconds):
    if plan.get('capture_domain')!='mono_pcm16_pre_afe' or plan.get('human_labels_verified') is not False:
        raise ValueError('Calibration requires exact input and explicitly provisional labels')
    groups=[]
    for name in ('positive_segments','negative_segments'):
        segments=plan.get(name,[])
        if not segments or (name=='positive_segments' and len(segments)!=10):raise ValueError('Unexpected calibration protocol')
        previous=-1
        for pair in segments:
            if len(pair)!=2:raise ValueError('Invalid interval')
            a,b=pair
            if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in pair) or not 0<=a<b<=seconds or a<previous:
                raise ValueError('Unordered/out-of-range interval')
            if name=='positive_segments' and not .3<=b-a<=1.2:raise ValueError('Ambiguous wake interval')
            previous=b;groups.append((a,b,name))
    for i,(a,b,name) in enumerate(groups):
        for c,d,other in groups[i+1:]:
            if name!=other and max(a,c)<min(b,d):raise ValueError('Negative overlaps wake/holdout')
    if plan.get('heldout_isolated_indices')!=[4,9]:raise ValueError('Holdout must stay fixed')
    extra=plan.get('training_question_prefixes',[])
    if extra:
        if plan.get('training_question_indices')!=[1] or plan.get('heldout_question_indices')!=[0,2] or len(extra)!=1:
            raise ValueError('Question split must be explicit and keep two held out')
        a,b=extra[0]
        if not 0<=a<b<=seconds or not .3<=b-a<=1.2:raise ValueError('Invalid question prefix')
        questions=plan.get('question_segments',[])
        if len(questions)!=3 or not questions[1][0]<=a<b<=questions[1][1]:raise ValueError('Prefix outside training question')
        if any(max(a,c)<min(b,d) for c,d in plan['positive_segments']):raise ValueError('Question prefix overlaps isolated trial')
        if any(max(a,c)<min(b,d) for c,d in plan['negative_segments']):raise ValueError('Question prefix overlaps negative')
    return plan['positive_segments'],plan['negative_segments']

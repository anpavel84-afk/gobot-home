"""Multimodal planning, independent of answer executor and transport."""
import json,re
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .presentation import PresentationDecision

class PresentationPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    always_visual_for_explicit_show_requests:Literal[True]=True
    auto_visual_for_helpful_topics:bool=True
    auto_visual_for_trivial_smalltalk:Literal[False]=False
    helpful_timeout_seconds:float=Field(default=8,ge=.05,le=12)
    paid_image_generation_enabled:Literal[False]=False

class ResponsePresentationPlan(BaseModel):
    visual_needed:bool=False
    visual_priority:Literal['required','helpful','optional']='optional'
    visual_type:Literal['none','image_card','image_gallery','illustration','diagram','info_card','timer','weather','status','music']='none'
    visual_strategy:Literal['retrieve','generate','render_local','mixed']='render_local'
    visual_query:str=''
    template:str|None=None
    speech_policy:Literal['follow_answer','brief_visual','silent']='follow_answer'
    origin:Literal['explicit','implicit','structured','none']='none'
    reason:str='no_helpful_visual'
    subject_source:Literal['request','answer']='request'
    subject_label:str=Field(default='',max_length=160)
    labels:list[str]=Field(default_factory=list,max_length=3)

class MultimodalResponsePlanner:
    def __init__(self,policy=None):
        if policy is None:
            path=Path(__file__).parents[1]/'presentation-policy.json'
            policy=PresentationPolicy(**json.loads(path.read_text(encoding='utf-8'))) if path.exists() else PresentationPolicy()
        self.policy=policy;self.explicit=PresentationDecision()
    def template(self,lower):
        if re.search(r'кратер.*лун|лун.*кратер',lower):return 'lunar_crater'
        if re.search(r'(?:расстояни|далеко|сколько.*километр).*лун|лун.*расстояни',lower):return 'earth_moon'
        if re.search(r'солнечн.*затмени|затмени.*солн',lower):return 'solar_eclipse'
        if re.search(r'вулкан',lower):return 'volcano'
        if re.search(r'млечн.*пут',lower):return 'milky_way'
        if re.search(r'томат|помидор',lower) and re.search(r'куст|строени|устроен',lower):return 'tomato_plant'
        if re.search(r'бычь[её] сердце',lower) and re.search(r'отлич|сравни',lower):return 'tomato_comparison'
        if re.search(r'лабрадор',lower) and re.search(r'золотист|golden',lower) and re.search(r'отлич|сравни',lower):return 'dog_comparison'
    def plan(self,query,*,route=None,context=None,answer_plan=None,final_answer=None):
        lower=query.casefold()
        if re.search(r'без\s+(?:картинок|изображений|визуал)|не\s+показывай|только\s+(?:текст|голос)',lower):return ResponsePresentationPlan(reason='user_disabled_visual')
        intent=self.explicit.detect(query)
        if intent:
            template=self.template(lower) if intent.kind=='diagram' else None
            if template:return ResponsePresentationPlan(visual_needed=True,visual_priority='required',visual_type='diagram',
                visual_strategy='generate',template=template,origin='explicit',speech_policy='brief_visual',reason='explicit_local_illustration')
            strategy='retrieve' if intent.kind=='image' else 'render_local'
            visual_type=('image_gallery' if intent.gallery else 'image_card') if intent.kind=='image' else 'info_card' if intent.kind=='info' else intent.kind
            return ResponsePresentationPlan(visual_needed=True,visual_priority='required',visual_type=visual_type,
                visual_strategy=strategy,visual_query=intent.query,origin='explicit' if intent.kind in {'image','diagram'} else 'structured',
                speech_policy='brief_visual',reason='explicit_visual_or_widget')
        tool=getattr(route,'tool',None)
        if tool=='timer':return ResponsePresentationPlan(visual_needed=True,visual_priority='required',visual_type='timer',origin='structured',reason='operational_timer')
        quality=getattr(route,'quality',None) or {}
        if quality.get('consequence_risk',0)>=2 or quality.get('verification_required') or tool in {'memory','file_permission','verification','clarify_topic','control','home'}:
            return ResponsePresentationPlan(reason='safety_or_source_gate')
        if not self.policy.auto_visual_for_helpful_topics:return ResponsePresentationPlan(reason='automatic_visual_disabled')
        if context and context.get('topic',{}).get('outcome')=='ambiguous':return ResponsePresentationPlan(reason='ambiguous_topic')
        template=self.template(lower)
        if template=='volcano' and not re.search(r'что такое|как устроен|как работает|объясни|расскажи',lower):template=None
        if template:
            return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='illustration',
                visual_strategy='generate',template=template,origin='implicit',reason='educational_local_illustration')
        if re.search(r'^(?:что такое|что за|расскажи (?:мне )?(?:про|о))\s+',lower):
            topic=re.sub(r'^(?:что такое|что за|расскажи (?:мне )?(?:про|о))\s+','',query,flags=re.I).strip(' .?!')
            if re.search(r'пончик|растени|животн|пород|дерев|цветок|орхиде|лабрадор|велосипед|телескоп|самол[её]т|пингвин|коал|жираф|кратер',topic,re.I):
                return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='image_card',visual_strategy='retrieve',
                    visual_query=topic[:180],origin='implicit',reason='concrete_object_explanation')
        return ResponsePresentationPlan()

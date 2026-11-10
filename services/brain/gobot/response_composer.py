"""Every product answer gets a scene, including an intentional avatar scene."""
import re
from typing import Literal
from pydantic import BaseModel,Field
from .device_contract import ScreenPreferences
from .presentation_planner import MultimodalResponsePlanner,ResponsePresentationPlan
from .answer_illustration import social

class ResponseScene(BaseModel):
    version:Literal[1]=1
    scene_type:Literal['avatar','icon','image','diagram','widget','info_card']='avatar'
    visual_subject:str=Field(default='GoBot',max_length=180)
    visual_strategy:Literal['retrieve_photo','generate_illustration','render_diagram','render_widget','show_emoji_or_icon','show_avatar']='show_avatar'
    visual_payload:dict=Field(default_factory=dict)
    display_text:str=''
    speech_text:str|None=None
    speech_policy:str='follow_answer'
    scene_duration:int=12
    source_metadata:dict=Field(default_factory=dict)
    preserve_visual:bool=False

class VisualResponseComposer:
    def __init__(self,planner=None):self.planner=planner or MultimodalResponsePlanner()
    def answer_visual_eligible(self,req,route=None,context=None,plan=None):
        from .visual_subject import PRIVATE_QUERY
        pref=req.screen_preferences or ScreenPreferences()
        quality=getattr(route,'quality',None) or {}
        return (pref.automatic_illustrations and pref.style!='minimal' and pref.prefer_real_photos
                and self.planner.policy.auto_visual_for_helpful_topics
                and not PRIVATE_QUERY.search(req.text)
                and (plan is None or plan.origin in {'none','implicit'})
                and (plan is None or plan.visual_strategy=='retrieve' or plan.reason=='no_helpful_visual')
                and not getattr(route,'tool',None) and not quality.get('verification_required')
                and not quality.get('consequence_risk',0)>=2
                and (context or {}).get('topic',{}).get('outcome')!='ambiguous')
    def plan_from_answer(self,req,answer,route=None,context=None,plan=None,directive=None):
        """Read a v1 archived directive. Live turns use the request-side extractor."""
        if not self.answer_visual_eligible(req,route,context,plan):return None
        from .visual_subject import grounded
        if directive is None or not grounded(directive,req.text,answer):return None
        if directive.kind=='avatar':return ResponsePresentationPlan(origin='implicit',reason='model_selected_avatar')
        if directive.kind=='diagram':
            return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='diagram',
                visual_strategy='generate',template=directive.template,subject_label=directive.subject,
                subject_source='answer',origin='implicit',reason='main_response_visual_plan')
        subject=directive.subject
        return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='image_card',
            visual_strategy='retrieve',visual_query=subject,subject_label=subject,subject_source='answer',
            origin='implicit',reason='main_response_visual_plan')
    def plan(self,req,route=None,context=None):
        plan=self.planner.plan(req.text,route=route,context=context)
        pref=req.screen_preferences or ScreenPreferences()
        if plan.reason=='user_disabled_visual':return plan
        if (pref.automatic_illustrations and pref.style!='minimal'
                and re.search(r'придумай|сказочн|фантастическ',req.text,re.I)
                and re.search(r'планет|город|пейзаж|мир',req.text,re.I)):
            from .visual_subject import PRIVATE_QUERY
            if not PRIVATE_QUERY.search(req.text):
                ai=pref.generation_allowed and pref.generation_mode!='off' and pref.generation_consent and pref.generation_daily_limit>0
                if not ai and not re.search(r'планет',req.text,re.I):return plan
                return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='illustration',
                    visual_strategy='generate',template=None if ai else 'fantasy_planet',
                    visual_query=req.text[:180],subject_label=req.text[:160],origin='implicit',
                    reason='ai_illustration' if ai else 'educational_local_illustration')
        if plan.origin=='implicit' and (not pref.automatic_illustrations or pref.style=='minimal'):
            return ResponsePresentationPlan(reason='user_prefers_avatar_or_minimal')
        if plan.origin=='implicit' and plan.visual_strategy=='retrieve' and not pref.prefer_real_photos:
            return ResponsePresentationPlan(reason='user_prefers_local_or_avatar')
        if (plan.visual_strategy=='retrieve' and plan.visual_needed and pref.source_preference=='illustrations'
                and pref.generation_mode=='helpful' and pref.generation_allowed and pref.generation_consent
                and pref.generation_daily_limit>0):
            return plan.model_copy(update={'visual_strategy':'generate','template':None,'subject_label':plan.visual_query,
                                          'reason':'ai_illustration'})
        if plan.visual_needed:return plan
        if not pref.automatic_illustrations or pref.style=='minimal':return plan
        if getattr(route,'tool',None) in {'verification','memory','file_permission','control','home'}:return plan
        quality=getattr(route,'quality',None) or {}
        if quality.get('consequence_risk',0)>=2 or quality.get('verification_required'):return plan
        if not pref.prefer_real_photos:return plan
        lower=req.text.casefold()
        recipe=re.search(r'как приготовить\s+(.+?)[?.!]*$',lower)
        if recipe:
            query=recipe[1].rstrip('?.!')
            if re.search(r'греческ.*салат',query):query='Greek salad'
            return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='image_card',
                visual_strategy='retrieve',visual_query=query[:180],origin='implicit',reason='recipe_reference_photo')
        animal=re.search(r'(?:сколько (?:лет )?жив[еёу]т|продолжительность жизни)\s+(.+?)[?.!]*$',lower)
        if animal:
            query=animal[1].rstrip('?.!')
            return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='image_card',
                visual_strategy='retrieve',visual_query=query[:180],origin='implicit',reason='animal_explanation_photo')
        if pref.style=='rich':
            subject=re.search(r'^(?:что такое|расскажи (?:про|о)|где находится)\s+(.+?)[?.!]*$',lower)
            if subject:return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='image_card',
                visual_strategy='retrieve',visual_query=subject[1].rstrip('?.!')[:180],origin='implicit',reason='rich_style_public_subject')
        return plan
    def compose(self,req,*,route=None,context=None,answer='',plan=None,has_visual=None,capabilities=None):
        plan=plan or self.plan(req,route,context);pref=req.screen_preferences or ScreenPreferences()
        scene=ResponseScene(display_text=answer,speech_policy=plan.speech_policy,scene_duration=pref.hold_after_response_seconds,
            preserve_visual=bool(has_visual),source_metadata={'basis':'response_content_and_route','verification':'not_implied_by_visual'})
        if plan.reason in {'model_selected_avatar','user_disabled_visual'}:return scene
        if plan.origin=='implicit' and has_visual is False:return scene
        if plan.visual_needed:
            strategy={'retrieve':'retrieve_photo','generate':'generate_illustration','render_local':'render_widget','mixed':'render_widget'}[plan.visual_strategy]
            if plan.template in {'lunar_crater','earth_moon','solar_eclipse','volcano','tomato_plant'}:strategy='render_diagram'
            scene.scene_type='image' if plan.visual_strategy=='retrieve' else 'diagram' if plan.visual_strategy=='generate' else 'widget'
            if plan.reason=='answer_map':scene.scene_type='diagram';strategy='render_diagram'
            scene.visual_strategy=strategy;scene.visual_subject=plan.visual_query or plan.template or plan.visual_type
            scene.visual_payload={'plan':plan.model_dump(),'loading':not has_visual};return scene
        lower=(req.text+' '+answer[:1200]).casefold();tool=getattr(route,'tool',None)
        icon,title=None,None
        if tool=='memory':icon,title='◷','Память разговора'
        elif tool=='calculator':icon,title='=','Результат'
        elif tool=='verification' or re.search(r'не удалось подтвердить|нет проверенн|не найден',answer,re.I):icon,title='?','Нужен проверенный источник'
        elif re.search(r'праздник|выходной',lower):icon,title='✦','Календарь'
        elif re.search(r'анекдот|шутк',lower):scene.visual_payload={'mood':'smile','decorative':True};return scene
        elif re.search(r'\bпопуга\w*',req.text,re.I):icon,title='🦜','Попугаи'
        elif re.search(r'пингвин',answer,re.I):icon,title='🐧','Пингвины'
        elif re.search(r'\b(?:растени\w*|цвет(?:ок|ка|ки|ков|ами|ах|ку|ком|ке)|дерев\w*)\b',answer,re.I):icon,title='❧','Растения'
        elif re.search(r'географ|страна|бразили|столиц|находится',lower):icon,title='◎','География'
        elif re.search(r'истори|древн',lower):icon,title='◴','История'
        elif re.search(r'техническ|архитектур|программ',lower):icon,title='⚙','Объяснение'
        if icon and pref.thematic_icons:
            scene.scene_type='info_card' if tool in {'memory','calculator','verification'} else 'icon'
            scene.visual_strategy='render_widget' if scene.scene_type=='info_card' else 'show_emoji_or_icon'
            scene.visual_subject=title;scene.visual_payload={'icon':icon,'title':title,'text':answer[:400],
                'data_status':'unverified' if tool=='verification' else 'answer_excerpt','decorative':tool not in {'memory','calculator'}}
        return scene

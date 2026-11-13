"""Typed view over the existing scenario/QuickIntent libraries, not a new inventory."""
from .quick_intents import library
from .hybrid_contract import SkillManifest

ALIASES={'clock_time':'clock.now','clock_date':'clock.date','clock_weekday':'clock.weekday',
    'timer_start':'timer.start','timer_cancel':'timer.cancel','timer_status':'timer.status'}
def manifests():
    result={}
    for row in library()['entries']:
        ident=ALIASES.get(row['intent'],row['intent'])
        if row['executor'] not in {'clock','timer','timer_status','calculator','quick_help'}:continue
        result[ident]=SkillManifest(skill_id=ident,category=row['executor'],implementation_status=row['status'],
            templates=row['patterns'],parameter_schema={'type':'object'},side_effect_class='write' if row['executor']=='timer' else 'read',
            allowed_context=['timer_duration'] if row['intent']=='timer_start' else [])
    for ident,category,status in [('weather.current','weather','implemented'),('weather.forecast','weather','implemented'),
        ('story.play','story','implemented'),('story.generate','story','unavailable'),('media.control','media','implemented'),
        ('conversation.b','conversation','experimental'),('conversation.c','conversation','experimental'),('device.volume','settings','implemented')]:
        result[ident]=SkillManifest(skill_id=ident,category=category,implementation_status=status,
            provider_dependencies=['Open-Meteo'] if category=='weather' else [],
            response_template='story_fixture_explicit' if ident=='story.play' else 'verified_result')
    return list(result.values())

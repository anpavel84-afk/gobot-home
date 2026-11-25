"""Bounded direct mode commands from a final user transcript, never tool text."""
import re


def direct_mode_intent(text):
    """Select the next input route only for a complete, explicit speech act.

    A question about modes, a quoted command, a negation or a second task must
    remain an ordinary question. Recognition grants no model/budget authority.
    """
    if not isinstance(text, str) or not text or len(text) > 240:
        return None
    if re.search(r'[\"\'«»“”„`]', text):
        return None
    value = ' '.join(re.sub(r'[,.!?:;—–-]+', ' ',
                           text.casefold().replace('ё', 'е')).split())
    guidance = bool(re.search(r'\b(?:подскажи|подскажите|скажите|послушай)\b', value))
    prefix = (r'(?:софия|софья|sophia|sofia|гобот|го бот|пожалуйста|слушай|'
              r'подскажи|подскажите|скажите|послушай|ну|а|хорошо|ладно) ')
    for _ in range(6):
        previous = value
        value = re.sub(r'^' + prefix, '', value)
        if value == previous:
            break
    value = ' '.join(word for word in value.split() if word != 'пожалуйста')
    value = re.sub(r'(?:(?: сейчас| давай)){1,3}$', '', value)
    value = re.sub(r'^(?:(?:ты|вы) )?(?:(?:можешь|можете|сможешь|сможете)'
                   r'(?: ли)?(?: ты| вы)?|могла бы|мог бы|могли бы|'
                   r'смогла бы|смог бы|смогли бы) ', '', value)
    value = re.sub(r'^(?:пожалуйста |прямо сейчас |сейчас ){1,2}', '', value)
    value = re.sub(r'^(?:давай|давайте|прошу|хочу|я хочу) ', '', value)
    verb = (r'(?:включи|включить|включим|переключи(?:сь| меня| нас| себя)?|'
            r'переключить(?: меня| нас| себя)?|переключиться|переключимся|'
            r'переведи(?: меня| нас)?|перевести(?: меня| нас)?|'
            r'перейди|перейти|перейдем|верни(?:сь| меня| нас)?|'
            r'вернуть(?: меня| нас)?|вернуться)')
    required_command = verb + r'(?: в| на| к)? '
    command = required_command if guidance else r'(?:' + required_command + r')?'
    if re.fullmatch(command + r'(?:экспертный|вдумчивый) режим(?: [aа])?', value):
        return 'expert'
    if re.fullmatch(r'(?:включи|включить|подключи|подключить) эксперта', value):
        return 'expert'
    # Final ASR can retain the spoken noun instead of the adjective. Still
    # require a complete switching verb; a bare mention is not a command.
    if re.fullmatch(required_command + r'режим эксперт(?:а)?', value):
        return 'expert'
    if re.fullmatch(command + r'(?:быстрый режим|обычный режим|живой разговор)', value):
        return 'fast'
    if value in {'вернись к обычному разговору', 'вернуться к обычному разговору'}:
        return 'fast'
    return None

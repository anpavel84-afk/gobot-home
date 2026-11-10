"""Procedural educational illustrations. Not photos, not generative model calls."""
import io,math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from .visual_images import ImageCandidate

TITLES={'lunar_crater':'Лунный кратер · условный разрез','earth_moon':'Земля и Луна',
 'solar_eclipse':'Солнечное затмение','volcano':'Как устроен вулкан','milky_way':'Млечный Путь · условный вид',
 'tomato_plant':'Строение томатного куста','tomato_comparison':'Сердцевидный и округлый томат',
 'dog_comparison':'Лабрадор и золотистый ретривер'}

def draw_illustration(cache,template):
    if template not in TITLES:raise ValueError('Unsupported local illustration')
    key='local:educational-'+template+'-v1';record=cache.source(key)
    if record:return record,TITLES[template]
    image=Image.new('RGB',(960,560),(12,20,26));draw=ImageDraw.Draw(image)
    font_path=Path('C:/Windows/Fonts/segoeui.ttf')
    font=ImageFont.truetype(str(font_path),25) if font_path.exists() else ImageFont.load_default(size=24)
    ink=(238,245,244);mint=(163,229,205);muted=(156,175,183)
    def label(x,y,text,color=ink):draw.text((x,y),text,fill=color,font=font)
    label(35,25,TITLES[template]);label(35,510,'Условная иллюстрация GoBot · не фотография · не в масштабе',muted)
    if template in {'earth_moon','solar_eclipse'}:
        if template=='earth_moon':
            draw.ellipse((70,180,270,380),fill=(42,100,180),outline=mint,width=3);draw.ellipse((750,230,850,330),fill=(166,171,176))
            draw.line((290,280,725,280),fill=mint,width=4);label(120,400,'Земля');label(755,355,'Луна')
            label(335,310,'Расстояние меняется',muted)
        else:
            draw.ellipse((50,170,250,370),fill=(239,190,72));draw.polygon([(470,255),(820,200),(820,340)],fill=(39,49,57))
            draw.ellipse((445,245,495,295),fill=(166,171,176));draw.ellipse((770,210,890,330),fill=(42,100,180),outline=mint,width=2)
            label(95,395,'Солнце');label(430,345,'Луна');label(780,365,'Земля');label(280,115,'Луна между Солнцем и Землёй')
    elif template=='lunar_crater':
        shape=[(40,320),(180,320),(250,240),(320,360),(600,360),(680,240),(750,320),(920,320),(920,455),(40,455)]
        draw.polygon(shape,fill=(90,99,110));draw.line(shape[:9],fill=muted,width=4)
        label(160,180,'Край кратера');label(380,385,'Дно кратера');label(645,180,'Край кратера')
    elif template=='volcano':
        draw.polygon([(100,430),(390,190),(455,220),(505,190),(820,430)],fill=(84,93,105))
        draw.ellipse((350,385,590,465),fill=(205,83,53));draw.line([(470,420),(470,225)],fill=(231,109,60),width=30)
        label(515,255,'Канал');label(350,465,'Магматическая камера');label(360,135,'Кратер')
    elif template=='tomato_plant':
        draw.line((460,420,460,160),fill=(71,162,100),width=12)
        for x,y in [(340,230),(580,250),(330,350),(600,360)]:
            draw.line((460,y+20,x,y),fill=(71,162,100),width=6);draw.ellipse((x-45,y-20,x+45,y+20),fill=(49,133,78))
        for x,y in [(385,275),(535,340)]:draw.ellipse((x-26,y-26,x+26,y+26),fill=(208,85,70))
        draw.line((100,425,860,425),fill=muted,width=2)
        for x in [370,410,505,550]:draw.line((460,420,x,480),fill=(162,134,96),width=4)
        label(480,160,'Стебель');label(645,235,'Лист');label(550,285,'Плод');label(170,450,'Корни')
    elif template=='tomato_comparison':
        draw.polygon([(150,225),(220,195),(285,225),(350,195),(420,225),(405,320),(285,425),(165,320)],fill=(201,93,86))
        draw.ellipse((570,215,810,415),fill=(207,82,60));label(145,125,'Сердцевидный тип');label(575,125,'Округлый тип')
        label(200,455,'Не определитель сорта; размер и форма различаются',muted)
    elif template=='dog_comparison':
        for x,color in [(265,(174,137,82)),(690,(213,177,108))]:
            draw.ellipse((x-95,200,x+95,385),fill=color);draw.ellipse((x-130,235,x-65,380),fill=color);draw.ellipse((x+65,235,x+130,380),fill=color)
            for eye in [x-35,x+35]:draw.ellipse((eye-7,260,eye+7,274),fill=(12,20,26))
            draw.ellipse((x-20,315,x+20,340),fill=(12,20,26))
        label(170,130,'Лабрадор');label(550,130,'Золотистый ретривер');label(175,450,'Условные силуэты; различия — в текстовом ответе',muted)
    else:
        for arm in range(4):
            points=[]
            for n in range(200):
                t=n/35;radius=10+n*1.3;angle=t+arm*math.pi/2
                points.append((480+radius*math.cos(angle),285+radius*.55*math.sin(angle)))
            draw.line(points,fill=(102+arm*25,150,191),width=10)
        draw.ellipse((450,260,510,310),fill=(238,219,176));label(230,440,'Схематичный вид галактики, не научная карта',muted)
    buffer=io.BytesIO();image.save(buffer,'JPEG',quality=90)
    candidate=ImageCandidate(key,TITLES[template]+' · локальная иллюстрация, не фотография',None,'GoBot Home','Локальная процедурная иллюстрация',None,'GoBot · procedural illustration')
    return cache.put(candidate,buffer.getvalue()),TITLES[template]

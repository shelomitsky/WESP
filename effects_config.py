"""Bounded, versioned native effect configuration. No network or credentials."""
import copy
import hashlib
import json
import re
from functools import lru_cache

MAX_PRESETS=8
TUNING={'sensitivity':(50,200),'gate':(0,30),'attack_ms':(0,300),
        'decay_ms':(80,600),'repeat_ms':(0,5000)}
KEYS={'sensitivity':'equalizer_sensitivity','gate':'equalizer_gate',
      'attack_ms':'equalizer_attack_ms','decay_ms':'equalizer_decay_ms','repeat_ms':'music_repeat_ms'}
DEFAULTS={'sensitivity':100,'gate':6,'attack_ms':0,'decay_ms':250,'repeat_ms':1000}


def integer(value,low,high):
    if type(value) is not int or not low<=value<=high:
        raise ValueError('Invalid native effect integer')
    return value


def colors(value):
    if not isinstance(value,list) or len(value)!=10:
        raise ValueError('Native effects require ten palette colors')
    for rgb in value:
        if not isinstance(rgb,(list,tuple)) or len(rgb)!=3:
            raise ValueError('Invalid native effect color')
        for channel in rgb:integer(channel,0,255)
    return [list(c) for c in value]


def revision(document):
    clean={key:value for key,value in document.items() if key!='revision'}
    return hashlib.sha256(json.dumps(clean,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]


def validate(value,count):
    if not isinstance(value,dict) or set(value)!={'schema','revision','sections','presets','active',
            'wallpaper_timeout_ms','wallpaper_fade_ms','notification'} or type(value['schema']) is not int or value['schema']!=1:
        raise ValueError('Invalid native effect schema')
    integer(count,1,1024)
    sections=value['sections'];occupied=set()
    if not isinstance(sections,list) or not 1<=len(sections)<=128:
        raise ValueError('Invalid native effect sections')
    for section in sections:
        if not isinstance(section,list) or len(section)!=3 or type(section[2]) is not bool:
            raise ValueError('Invalid native effect section')
        start=integer(section[0],0,count-1);length=integer(section[1],1,count-start)
        pixels=set(range(start,start+length))
        if pixels&occupied:raise ValueError('Native effect sections overlap')
        occupied.update(pixels)
    presets=value['presets'];ids=set()
    if not isinstance(presets,list) or not 1<=len(presets)<=MAX_PRESETS:
        raise ValueError('Too many native presets')
    for preset in presets:
        if not isinstance(preset,dict) or set(preset)!={'id','style','colors',*TUNING}:
            raise ValueError('Invalid native preset')
        ident=preset['id']
        if not isinstance(ident,str) or not re.fullmatch('[a-z0-9_-]{1,16}',ident) or ident in ids:
            raise ValueError('Invalid or duplicate native preset ID')
        ids.add(ident)
        if preset['style'] not in ('meter','pulse'):raise ValueError('Invalid native preset style')
        colors(preset['colors'])
        for key,(low,high) in TUNING.items():integer(preset[key],low,high)
        if 0<preset['repeat_ms']<180:raise ValueError('Native repeated pulse is too fast')
    if value['active'] not in ids:raise ValueError('Unknown active native preset')
    integer(value['wallpaper_timeout_ms'],1500,60000);integer(value['wallpaper_fade_ms'],0,10000)
    event=value['notification']
    if not isinstance(event,dict) or set(event)!={'style','color','strength','duration_ms'}:
        raise ValueError('Invalid native notification')
    if event['style'] not in ('flash','pulse','tint','pixel'):raise ValueError('Invalid native notification style')
    colors([event['color']]*10);integer(event['strength'],10,100);integer(event['duration_ms'],100,10000)
    if value['revision']!=revision(value):raise ValueError('Native effect revision does not match its content')
    if len(json.dumps(value,separators=(',',':')).encode())>6500:
        raise ValueError('Native effect configuration is too large')
    return copy.deepcopy(value)


def preset(prefs,ident):
    import layout
    return dict(id=ident,style=prefs.get('music_style','meter'),
                colors=colors(layout.palette_colors(prefs.get('equalizer_palette','classic'))),
                **{key:prefs.get(field,DEFAULTS[key]) for key,field in KEYS.items()})


def from_preferences(prefs):
    import layout,scenes
    count=prefs['controller']['count']
    sections=layout.validate(prefs['sections'],count)
    presets=[preset(prefs,'custom')]
    for name,tuning in scenes.PRESETS.items():presets.append(preset(dict(prefs,**tuning),name))
    saved=prefs.get('native_presets',[])
    if not isinstance(saved,list) or len(saved)>MAX_PRESETS-3:raise ValueError('Too many saved native presets')
    for item in saved:
        if not isinstance(item,dict) or not isinstance(item.get('settings'),dict):raise ValueError('Invalid saved native preset')
        presets.append(preset(item['settings'],item['id']))
    active=prefs.get('native_active_preset') or prefs.get('music_preset','custom')
    if active not in {item['id'] for item in presets}:active='custom'
    color=prefs.get('notify_color','#8000ff')
    if not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color):raise ValueError('Invalid native notification color')
    style=prefs.get('notify_style','flash')
    result=dict(schema=1,sections=[[s['start'],s['count'],s['reverse']] for s in sections],
        presets=presets,active=active,wallpaper_timeout_ms=prefs.get('wallpaper_timeout_ms',8000),
        wallpaper_fade_ms=prefs.get('wallpaper_fade_ms',1000),notification=dict(style=style,
        color=[int(color[i:i+2],16) for i in (1,3,5)],strength=prefs.get('notify_strength',60),
        duration_ms=2400 if style=='pulse' else 1600))
    result['revision']=revision(result)
    return validate(result,count)


@lru_cache(maxsize=8)
def _cached(serialized):
    return from_preferences(json.loads(serialized))


def cached(prefs):
    fields={'sections','music_style','music_preset','native_active_preset','native_presets',
            'equalizer_palette','notify_color','notify_style','notify_strength','wallpaper_timeout_ms',
            'wallpaper_fade_ms',*KEYS.values()}
    selected={key:prefs[key] for key in fields if key in prefs}
    selected['controller']={'count':prefs['controller']['count']}
    return _cached(json.dumps(selected,sort_keys=True,separators=(',',':')))

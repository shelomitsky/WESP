"""Named user tuning; controller identity and network are never preset data."""
import copy
import secrets
from i18n import tr

FIELDS=('music_style','equalizer_palette','equalizer_sensitivity','equalizer_gate',
        'equalizer_attack_ms','equalizer_decay_ms','music_repeat_ms')


def edit(prefs,action,value):
    import control
    result=copy.deepcopy(prefs)
    presets=result.setdefault('native_presets',[])
    if not isinstance(presets,list):raise ValueError(tr('Invalid saved presets'))
    if action=='save':
        if not isinstance(value,str) or not 1<=len(value.strip())<=32 or len(value.strip().encode())>64:
            raise ValueError(tr('Enter a preset name up to 32 characters'))
        if len(presets)>=5:raise ValueError(tr('Five custom presets are already saved'))
        settings={key:result.get(key,control.DEFAULTS[key]) for key in FIELDS}
        for key,current in settings.items():
            control.validate_decay_ms(current) if key=='equalizer_decay_ms' else control.validate_tuning(key,current)
        presets.append(dict(id='p'+secrets.token_hex(6),name=value.strip(),settings=settings))
    elif action in ('load','delete'):
        item=next((p for p in presets if isinstance(p,dict) and p.get('id')==value),None)
        if item is None:raise ValueError(tr('Choose a saved preset'))
        if action=='delete':
            result['native_presets']=[p for p in presets if p['id']!=value]
            if result.get('native_active_preset')==value:result.pop('native_active_preset',None)
        else:
            settings=item.get('settings')
            if not isinstance(settings,dict) or set(settings)!=set(FIELDS):raise ValueError(tr('Invalid saved presets'))
            for key,current in settings.items():
                result[key]=control.validate_decay_ms(current) if key=='equalizer_decay_ms' else control.validate_tuning(key,current)
            result.update(native_active_preset=value,music_preset='custom')
    else:raise ValueError(tr('Unknown preset action'))
    return result

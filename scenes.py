"""Small validated desktop scenes/presets; hardware identity is never a preset."""
import copy
from i18n import tr
from preferences import DEFAULTS, RESPONSE_FIELDS, validate_value

TUNING = RESPONSE_FIELDS
PRESETS = {
    'soft': dict(equalizer_sensitivity=90,equalizer_gate=8,equalizer_attack_ms=40,equalizer_decay_ms=380),
    'vivid': dict(equalizer_sensitivity=125,equalizer_gate=6,equalizer_attack_ms=0,equalizer_decay_ms=220),
}


def mode(prefs):
    return 'music' if prefs.get('equalizer') else 'calm' if prefs.get('kde') else 'manual'


def preset(prefs, name):
    if name not in (*PRESETS,'custom'):
        raise ValueError(tr('Unknown music preset'))
    result = copy.deepcopy(prefs)
    if name != 'custom' and prefs.get('music_preset','custom') == 'custom':
        result['music_custom'] = {key:prefs.get(key,DEFAULTS[key]) for key in TUNING}
    values = result.get('music_custom',{}) if name == 'custom' else PRESETS[name]
    if not isinstance(values,dict) or set(values)-set(TUNING):
        raise ValueError(tr('Invalid saved music tuning'))
    for key,value in values.items():
        result[key] = validate_value(key,value)
    result['music_preset'] = name
    return result


def select(prefs, name):
    if name not in ('music','calm'):
        raise ValueError(tr('Unknown lighting scene'))
    result=copy.deepcopy(prefs)
    if mode(prefs) != name:
        result['scene_generation']=int(prefs.get('scene_generation',0))+1
    result['equalizer']=name=='music'
    if name=='calm':
        result['kde']=True
    return result


def memory(prefs, saved):
    result=dict(saved)
    generation=prefs.get('scene_generation',0)
    if saved.get('scene_generation',0)!=generation:
        result.pop('equalizerBase',None)
        result.pop('overlayBase',None)
    result['scene_generation']=generation
    return result


def activity(prefs, mem, state, now):
    import first_light
    base=mode(prefs)
    labels={'music':tr('Music'),'calm':tr('Calm light'),'manual':tr('Manual lighting')}
    if mem.get('suspended'):
        effective,label='sleep',tr('Paused for sleep')
    elif not state.get('on'):
        effective,label='off',tr('Lighting is off')
    elif first_light.active(prefs,mem):
        effective,label='calibration',tr('Checking strip: %1',mem['firstLight'].get('name',''))
    elif mem.get('volumeUntil',0)>now:
        effective,label='volume',tr('Volume · then %1',labels[base])
    else:
        import notification_fx
        if notification_fx.active(prefs,mem,now):
            effective,label='notification',tr('Notification over %1',labels[base])
        else:
            effective,label=base,labels[base]
    return dict(base=base,effective=effective,label=label)

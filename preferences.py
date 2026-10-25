"""Desktop preference defaults and validation, without storage or device access."""
from i18n import tr
import re

DEFAULTS = dict(host='', kde=True, volume=True, notify=True,
                equalizer=False, transport='usb', reverse_first=False, reverse_second=False,
                equalizer_decay_ms=250, controller=None, sections=[])
DEFAULTS.update(equalizer_sensitivity=100,equalizer_gate=6,notify_style='flash',
                notify_color='#8000ff',notify_strength=60,equalizer_attack_ms=0,
                equalizer_palette='classic',music_style='meter',music_preset='custom',music_custom={})
DEFAULTS.update(music_repeat_ms=1000,wallpaper_timeout_ms=8000,wallpaper_fade_ms=1000,native_presets=[])


def validate_tuning(key,value):
    if key=='music_style':
        if value not in ('meter','pulse'):
            raise ValueError(tr('Unknown music style'))
        return value
    if key=='equalizer_palette':
        import layout
        layout.palette_colors(value)
        return value
    if key=='notify_style':
        if value not in ('flash','pulse','tint','pixel'):
            raise ValueError(tr("Unknown notification style"))
        return value
    if key=='notify_color':
        if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
            raise ValueError(tr("Color must use the #RRGGBB format"))
        return value.lower()
    low,high={'equalizer_sensitivity':(50,200),'equalizer_gate':(0,30),
              'equalizer_attack_ms':(0,300),'notify_strength':(10,100),'music_repeat_ms':(0,5000),
              'wallpaper_timeout_ms':(1500,60000),'wallpaper_fade_ms':(0,10000)}[key]
    if type(value) is str and re.fullmatch(r'[0-9]+',value):
        value=int(value)
    if type(value) is not int or not low<=value<=high:
        raise ValueError(tr('Value must be an integer from %1 to %2',low,high))
    if key=='music_repeat_ms' and 0<value<180:raise ValueError(tr('Repeated pulses must be at least 180 ms apart'))
    return value


def validate_decay_ms(value):
    if type(value) is str and re.fullmatch(r'[0-9]+', value):
        value = int(value)
    if type(value) is not int or not 80 <= value <= 600:
        raise ValueError(tr("Decay must be an integer from 80 to 600 ms"))
    return value



RESPONSE_FIELDS = ('equalizer_sensitivity', 'equalizer_gate',
                   'equalizer_attack_ms', 'equalizer_decay_ms')
MUSIC_FIELDS = ('music_style', 'equalizer_palette', *RESPONSE_FIELDS, 'music_repeat_ms')


def validate_value(key, value):
    """Validate one desktop value, including the dedicated decay range."""
    return validate_decay_ms(value) if key == 'equalizer_decay_ms' else validate_tuning(key, value)

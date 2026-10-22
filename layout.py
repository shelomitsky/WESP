"""Logical sections in WLED's global physical pixel buffer (RGB only)."""
from i18n import tr
import math

MAX_PIXELS = 1024
COLORS = [(0,180,130),(0,205,95),(0,225,55),(45,240,10),(110,240,0),
          (180,220,0),(240,170,0),(255,110,0),(255,55,0),(255,15,15)]
PALETTES = {
    'classic': COLORS,
    'fire': [(255,24,0),(255,110,0),(255,230,120)],
    'ocean': [(0,40,255),(0,170,255),(100,255,220)],
    'violet': [(70,0,255),(190,0,255),(255,80,160)],
    'rainbow': [(255,0,0),(255,190,0),(0,220,60),(0,150,255),(150,0,255)],
    'wallpaper': COLORS,  # Safe fallback until the background sampler is ready.
}


def palette_colors(name):
    """Ten position colors, preserving the original classic palette exactly."""
    if not isinstance(name,str) or name not in PALETTES:
        raise ValueError(tr("Unknown equalizer palette"))
    stops=PALETTES[name]
    colors=[]
    for index in range(10):
        position=index*(len(stops)-1)/9
        left=min(int(position),len(stops)-2)
        fraction=position-left
        colors.append(tuple(round(a+(b-a)*fraction) for a,b in zip(stops[left],stops[left+1])))
    return colors


def validate(sections, count):
    if type(count) is not int or not 1 <= count <= MAX_PIXELS:
        raise ValueError(tr("Between 1 and 1024 RGB LEDs are supported"))
    if not isinstance(sections,list) or not 1 <= len(sections) <= min(count,128):
        raise ValueError(tr("Use 1–128 nonempty sections within the LED count"))
    result, occupied, ids = [], set(), set()
    for section in sections:
        if not isinstance(section,dict):
            raise ValueError(tr("Invalid section"))
        start, length = section.get('start'), section.get('count')
        ident, name = section.get('id'), section.get('name')
        if (type(start) is not int or type(length) is not int or start < 0
                or length < 1 or start+length > count):
            raise ValueError(tr("Section range exceeds the WLED LED count"))
        if (not isinstance(ident,str) or not 1 <= len(ident) <= 64 or ident in ids
                or not isinstance(name,str) or not 1 <= len(name.strip()) <= 64):
            raise ValueError(tr("A unique section ID and name are required"))
        if type(section.get('reverse')) is not bool:
            raise ValueError(tr("Invalid section direction"))
        if section.get('placement') not in ('left','right','top','bottom','custom'):
            raise ValueError(tr("Invalid section placement"))
        positions=set(range(start,start+length))
        if positions & occupied:
            raise ValueError(tr("Section ranges overlap"))
        occupied.update(positions)
        ids.add(ident)
        result.append(dict(id=ident,name=name.strip(),start=start,count=length,
                           reverse=section['reverse'],placement=section['placement']))
    return result


def legacy(count, reverse_first=False, reverse_second=False):
    if count == 20:
        return [dict(id='first',name=tr("Strip 1"),start=0,count=10,
                     reverse=bool(reverse_first),placement='custom'),
                dict(id='second',name=tr("Strip 2"),start=10,count=10,
                     reverse=bool(reverse_second),placement='custom')]
    return [dict(id='main',name=tr("Lighting"),start=0,count=count,
                 reverse=False,placement='custom')]


def indices(section):
    positions=list(range(section['start'],section['start']+section['count']))
    return positions[::-1] if section['reverse'] else positions


def marker(sections):
    return indices(sections[0])[0]


def meter(level, sections, count, color=None, palette='classic', colors=None):
    if not math.isfinite(level):
        raise ValueError(tr("Invalid level"))
    frame=[[0,0,0] for _ in range(count)]
    colors=palette_colors(palette) if colors is None else colors
    for section in sections:
        length=section['count']
        for logical,physical in enumerate(indices(section)):
            rgb=color or colors[min(9,logical*10//length)]
            amount=max(0,min(1,level*length-logical))
            frame[physical]=[round(channel*amount) for channel in rgb]
    return frame


def solid(color,sections,count):
    return meter(1,sections,count,color)

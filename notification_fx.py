"""Notification overlays on a copy of the current RGB frame."""
import math
import layout


def phase(prefs,mem,now):
    if not prefs.get('notify',True) or mem.get('suspended'):
        return None
    if mem.get('notifyPreviewUntil',0)>now:
        start=mem.get('notifyPreviewStart',now)
    elif mem.get('ids'):
        start=mem.get('notifyStarted',0)
    else:
        return None
    elapsed=now-start
    if elapsed<0:
        return None
    if mem.get('nativeEffects') and elapsed>=(2.4 if prefs.get('notify_style')=='pulse' else 1.6):return None
    if prefs.get('notify_style','flash')=='flash' and elapsed>=1.6:
        return None
    return elapsed


def active(prefs,mem,now):
    return phase(prefs,mem,now) is not None


def overlay(frame,sections,prefs,mem,now):
    elapsed=phase(prefs,mem,now)
    if elapsed is None:
        return frame
    style=prefs.get('notify_style','flash')
    strength=prefs.get('notify_strength',60)/100
    if style=='flash':
        strength*=math.sin(math.pi*(elapsed%0.8)/0.8)**2
    elif style=='pulse':
        strength*=.15+.85*math.sin(math.pi*(elapsed%2.4)/2.4)**2
    color=prefs.get('notify_color','#8000ff')
    rgb=[int(color[i:i+2],16) for i in (1,3,5)]
    result=[list(pixel) for pixel in frame]
    positions=[layout.marker(sections)] if style=='pixel' else [i for section in sections for i in layout.indices(section)]
    for index in positions:
        result[index]=[round(value*(1-strength)+target*strength) for value,target in zip(frame[index],rgb)]
    return result

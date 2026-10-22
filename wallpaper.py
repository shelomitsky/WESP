"""Local KDE wallpaper palette. Image decoding never runs in the audio worker."""
from i18n import tr
import colorsys
import configparser
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import unquote, urlsplit

import layout

LOG=logging.getLogger('wled-control.wallpaper')


def current_activity():
    try:
        import dbus
        obj=dbus.SessionBus().get_object('org.kde.ActivityManager','/ActivityManager/Activities')
        return str(obj.get_dbus_method('CurrentActivity','org.kde.ActivityManager.Activities')(timeout=.3))
    except Exception:
        return None


def live_wallpaper(screen):
    """Read Plasma's in-memory wallpaper map; never writes desktop settings."""
    try:
        import dbus
        obj=dbus.SessionBus().get_object('org.kde.plasmashell','/PlasmaShell',introspect=False)
        method=obj.get_dbus_method('wallpaper','org.kde.PlasmaShell')
        return dict(method(dbus.UInt32(screen),timeout=.5))
    except Exception as error:
        raise ValueError(tr("Could not read the current slide from Plasma")) from error


def local_image(value):
    url=urlsplit(value)
    if url.scheme and (url.scheme!='file' or url.netloc not in ('','localhost')):
        raise ValueError(tr("Only local wallpaper images are supported"))
    path=Path(unquote(url.path) if url.scheme else value)
    if not path.is_absolute():
        raise ValueError(tr("No local wallpaper file found"))
    if path.is_dir():
        images=[p for p in (path/'contents/images').glob('*')
                if p.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.avif')]
        if not images:
            raise ValueError(tr("No image found in the wallpaper package"))
        path=max(images,key=lambda p:(p.stat().st_size,p.name))
    return path


def discover(config,cache,activity=None):
    parser=configparser.ConfigParser(interpolation=None,strict=False)
    parser.read(config,encoding='utf-8')
    desktops=[]
    for section in parser.sections():
        match=re.fullmatch(r'Containments\]\[(\d+)',section)
        if not match or parser.get(section,'plugin',fallback='') not in ('org.kde.plasma.folder','org.kde.desktop'):
            continue
        screen=parser.getint(section,'lastScreen',fallback=-1)
        if screen<0 or (activity and parser.get(section,'activityId',fallback='')!=activity):
            continue
        desktops.append((screen,-int(match[1]),section))
    if not desktops:
        raise ValueError(tr("No KDE desktop found"))
    screen,_,section=min(desktops)
    plugin=parser.get(section,'wallpaperplugin',fallback='')
    group=section+'][Wallpaper]['+plugin+'][General'
    if plugin=='org.kde.image':
        return local_image(parser.get(group,'Image',fallback='')), tr("Wallpaper colors")
    if plugin=='org.kde.slideshow':
        live=live_wallpaper(screen)
        if live.get('wallpaperPlugin')!=plugin:
            raise ValueError(tr("Wallpaper plugin changed — waiting for KDE settings to update"))
        image=live.get('Image','')
        if not image:
            raise ValueError(tr("Plasma has not reported the current slide yet"))
        return local_image(str(image)), tr("Slideshow colors")
    if plugin=='org.kde.potd':
        provider=parser.get(group,'Provider',fallback='apod')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',provider):
            raise ValueError(tr("Unknown Picture of the Day provider"))
        candidates=[p for p in Path(cache).glob(provider+'*') if p.is_file()
                    and re.fullmatch(re.escape(provider)+r'(?::\d+)*',p.name)]
        if not candidates:
            raise ValueError(tr("KDE has not downloaded the Picture of the Day yet"))
        return max(candidates,key=lambda p:(p.stat().st_mtime_ns,p.stat().st_size)), tr('Picture of the Day colors · %1',provider)
    raise ValueError(tr("This wallpaper plugin is not supported yet"))


def sample_pixels(path):
    from PIL import Image
    if Path(path).stat().st_size>64*1024*1024:
        raise ValueError(tr("Wallpaper file is too large to analyze"))
    with Image.open(path) as image:
        if image.width*image.height>64_000_000:
            raise ValueError(tr("Wallpaper image is too large to analyze"))
        image.thumbnail((64,64),Image.Resampling.BOX)
        data=image.convert('RGBA').tobytes()
    return [tuple(data[i:i+4]) for i in range(0,len(data),4)]


def extract(pixels):
    visible=[p[:3] for p in pixels if p[3]>=128]
    useful=[p for p in visible if max(p)>=24 and max(p)-min(p)>=16]
    if not useful:
        useful=[p for p in visible if max(p)>=24] or [(96,96,96)]
    bins={}
    for pixel in useful:
        key=tuple(c//32 for c in pixel)
        bucket=bins.setdefault(key,[0,0,0,0])
        bucket[0]+=1
        for i,c in enumerate(pixel):
            bucket[i+1]+=c
    ranked=sorted(bins.items(),key=lambda item:(-item[1][0],item[0]))
    stops=[]
    for _,bucket in ranked:
        rgb=tuple(c/bucket[0] for c in bucket[1:])
        # Nearby histogram buckets must not crowd out another dominant hue.
        if any(sum((a-b)**2 for a,b in zip(rgb,old))<60**2 for old in stops):
            continue
        stops.append(rgb)
        if len(stops)==3:
            break
    stops.sort(key=lambda c:.2126*c[0]+.7152*c[1]+.0722*c[2])
    bright=[]
    for rgb in stops:
        h,s,v=colorsys.rgb_to_hsv(*(c/255 for c in rgb))
        bright.append(tuple(round(c*255) for c in colorsys.hsv_to_rgb(h,s,max(v,.38))))
    if len(bright)==1:
        bright*=2
    colors=[]
    for i in range(10):
        position=i*(len(bright)-1)/9
        left=min(int(position),len(bright)-2)
        colors.append([round(a+(b-a)*(position-left)) for a,b in zip(bright[left],bright[left+1])])
    return colors


def fallback(status=None):
    return dict(available=False,colors=[list(c) for c in layout.COLORS],
                status=tr("Wallpaper unavailable — classic palette") if status is None else status)


def cached(runtime):
    try:
        record=json.loads((Path(runtime)/'wallpaper-palette.json').read_text())
        colors=record['colors']
        if (type(record['available']) is not bool or not isinstance(record['status'],str)
                or not isinstance(colors,list) or len(colors)!=10
                or any(not isinstance(c,list) or len(c)!=3 or any(type(v) is not int or not 0<=v<=255 for v in c) for c in colors)):
            raise ValueError('Invalid cached palette')
        return record
    except (OSError,ValueError,KeyError,TypeError):
        return fallback()


class Watcher:
    def __init__(self,config,cache,runtime):
        self.config,self.cache,self.runtime=Path(config),Path(cache),Path(runtime)
        self.last_check=float('-inf')
        self.signature=None
        self.record=None

    def refresh(self,now=None):
        now=time.monotonic() if now is None else now
        if now-self.last_check<2:
            return
        self.last_check=now
        try:
            path,label=discover(self.config,self.cache,current_activity())
            stat=path.stat()
            signature=(path,stat.st_mtime_ns,stat.st_size)
            if signature==self.signature:
                return
            record=dict(available=True,colors=extract(sample_pixels(path)),status=label)
            self.signature=signature
        except Exception as error:
            self.signature=None
            record=fallback(tr('%1 — classic palette',str(error)))
        if record==self.record:
            return
        if not record['available']:
            LOG.warning('Wallpaper palette unavailable: %s',record['status'])
        self.runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.NamedTemporaryFile(mode='w',dir=self.runtime,delete=False) as handle:
            temporary=Path(handle.name)
            json.dump(record,handle)
        try:
            temporary.replace(self.runtime/'wallpaper-palette.json')
        finally:
            temporary.unlink(missing_ok=True)
        self.record=record


def desktop_watcher(runtime):
    config=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))
    cache=Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))
    return Watcher(config/'plasma-org.kde.plasma.desktop-appletsrc',cache/'plasma_engine_potd',runtime)

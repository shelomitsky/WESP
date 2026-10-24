#!/usr/bin/python3
"""Shared HTTP/settings helper for the existing WLED desktop services."""
from i18n import tr
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request

CONFIG = Path(os.environ.get('WLED_CONFIG_DIR', str(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config'))) / 'wled-control-desktop')))
RUNTIME = Path(os.environ.get('WLED_RUNTIME_DIR',
               str(Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/wled-control-desktop-{os.getuid()}')) / 'wled-control-desktop')))
DEFAULTS = dict(host='', kde=True, volume=True, notify=True,
                equalizer=False, transport='usb', reverse_first=False, reverse_second=False,
                equalizer_decay_ms=250, controller=None, sections=[])
DEFAULTS.update(equalizer_sensitivity=100,equalizer_gate=6,notify_style='flash',
                notify_color='#8000ff',notify_strength=60,equalizer_attack_ms=0,
                equalizer_palette='classic')


def validate_tuning(key,value):
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
              'equalizer_attack_ms':(0,300),'notify_strength':(10,100)}[key]
    if type(value) is str and re.fullmatch(r'[0-9]+',value):
        value=int(value)
    if type(value) is not int or not low<=value<=high:
        raise ValueError(tr('Value must be an integer from %1 to %2',low,high))
    return value


def validate_decay_ms(value):
    if type(value) is str and re.fullmatch(r'[0-9]+', value):
        value = int(value)
    if type(value) is not int or not 80 <= value <= 600:
        raise ValueError(tr("Decay must be an integer from 80 to 600 ms"))
    return value


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default.copy()


def write_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value))
    tmp.chmod(0o600)
    tmp.replace(path)


@contextlib.contextmanager
def locked(name='command'):
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (RUNTIME / (name + '.lock')).open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def settings():
    return DEFAULTS | read_json(CONFIG / 'settings.json', {})


def persist_enrollment(selected):
    """Prepare both documents before the USB owner commits its new Device."""
    import layout
    prefs=settings()
    previous=prefs.get('controller') or {}
    sections=None
    if previous.get('mac')==selected['mac'] and prefs.get('sections'):
        try:
            sections=layout.validate(prefs['sections'],selected['count'])
        except ValueError:
            if previous.get('count')==selected['count']:
                raise
    if sections is None:
        sections=[dict(id='main',name=tr("Lighting"),start=0,count=selected['count'],
                       reverse=False,placement='custom')]
    prefs.update(controller=selected,sections=sections,equalizer=False,transport='usb')
    documents={RUNTIME/'state.json':dict(ids=[],volumeUntil=0,base={},suspended=False,
                                        resume=None,controller_mac=selected['mac']),
               CONFIG/'settings.json':prefs}
    temporary=[]
    retained=set()
    prepared,previous={},{}
    applied=[]

    def stage(path,data,mode):
        fd,name=tempfile.mkstemp(prefix='.wesp-enroll-',dir=path.parent)
        staged=Path(name)
        temporary.append(staged)
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return staged

    try:
        for path,value in documents.items():
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            prepared[path]=stage(path,json.dumps(value).encode(),0o600)
            previous[path]=stage(path,path.read_bytes(),path.stat().st_mode & 0o777) if path.exists() else None
        try:
            for path in documents:
                prepared[path].replace(path)
                applied.append(path)
        except Exception:
            failed=[]
            for path in reversed(applied):
                try:
                    if previous[path] is None:
                        path.unlink(missing_ok=True)
                    else:
                        previous[path].replace(path)
                except OSError:
                    if previous[path] is not None:
                        retained.add(previous[path])
                    failed.append(str(path))
            if failed:
                raise RuntimeError(tr('Could not restore controller settings; backups: %1; files: %2',
                                      ', '.join(map(str,retained)), ', '.join(failed)))
            raise
    finally:
        for path in temporary:
            if path not in retained:
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    print('WESP: could not remove enrollment temporary file: '+str(error),file=sys.stderr)
    return prefs


def runtime():
    identity=(settings().get('controller') or {}).get('mac')
    default=dict(ids=[],volumeUntil=0,base={},suspended=False,resume=None,controller_mac=identity)
    saved=read_json(RUNTIME/'state.json',{})
    if saved.get('controller_mac') != identity:
        return default  # never replay another controller's snapshot
    return default | saved


def request(prefs, payload=None):
    if os.environ.get('WLED_TRANSPORT', prefs.get('transport', 'usb')) == 'usb':
        import usb_transport
        # Any ordinary command must release realtime before changing effects,
        # brightness, or power; the next music frame may resume if still enabled.
        return usb_transport.client(dict(payload, live=False) if payload is not None else None)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(prefs['host'] + '/json/state', data=data,
                                 headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=2) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError(tr("Invalid WLED response"))
    return result


def device_state(prefs):
    state = request(prefs)
    if type(state.get('on')) is not bool or type(state.get('bri')) is not int:
        raise ValueError(tr("The device did not return its WLED state"))
    return state


def kde_color():
    try:
        text = (Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config'))) / 'kdeglobals').read_text()
    except FileNotFoundError:
        return [0, 112, 254]
    for key in ('AccentColor', 'LastUsedCustomAccentColor'):
        m = re.search(r'^' + key + r'=(\d+),(\d+),(\d+)\s*$', text, re.M)
        if m and all(0 <= int(v) <= 255 for v in m.groups()):
            return [int(v) for v in m.groups()]
    return [0, 112, 254]


def base_segments(state):
    return {str(seg['id']): {'col': seg.get('col', [[0, 112, 254]]),
                            'bri': seg.get('bri', 128), 'fx': seg.get('fx', 0),
                            'sx': seg.get('sx', 128), 'ix': seg.get('ix', 128),
                            'pal': seg.get('pal', 0)}
            for seg in state.get('seg', []) if type(seg.get('id')) is int}


def apply(prefs, mem, state=None, marker_visible=True):
    state = state or device_state(prefs)
    if (mem['suspended'] or not state['on'] or mem['volumeUntil'] > time.time()
            or (prefs.get('equalizer') and mem.get('equalizerBase'))):
        return
    if not prefs['kde'] and not mem['base']:
        mem['base'] = base_segments(state)
    color = kde_color() if prefs['kde'] else None
    if prefs.get('controller') and prefs.get('sections'):
        import layout, usb_transport
        count=prefs['controller']['count']
        sections=layout.validate(prefs['sections'],count)
        import notification_fx
        if color is None and not notification_fx.active(prefs,mem,time.time()):
            snapshot=mem.get('overlayBase')
            if snapshot:
                present={str(seg['id']) for seg in state.get('seg',[])}
                segments=[dict(id=int(i),frz=False,**v) for i,v in snapshot.items() if i in present]
                if segments:
                    request(prefs,{'seg':segments,'tt':0})
                mem['overlayBase']={}
            return
        if not mem.get('overlayBase'):
            mem['overlayBase']=base_segments(state)
        frame=layout.solid(color or [0,112,254],sections,count)
        if color is None:
            owned={i for section in sections for i in layout.indices(section)}
            for seg in state.get('seg',[]):
                rgb=seg.get('col',[[0,0,0]])[0][:3]
                for i in range(max(0,seg.get('start',0)),min(count,seg.get('stop',0))):
                    if i in owned:
                        frame[i]=list(rgb)
        frame=notification_fx.overlay(frame,sections,prefs,mem,time.time())
        usb_transport.client(pixels=frame)
        return
    marker_id = 2 if any(s['id'] == 2 for s in state.get('seg', [])) else 0
    segments = []
    for i in [s['id'] for s in state.get('seg', [])]:
        existing = next((s for s in state.get('seg', []) if s.get('id') == i), None)
        if existing is None and state.get('seg'):
            continue
        base = mem['base'].get(str(i), {'col': [[0, 112, 254]], 'bri': 128, 'fx': 0})
        seg = {'id': i, 'frz': False, **({'col': [color], 'bri': 128, 'fx': 0} if color else base)}
        if i == marker_id:
            rgb = color or base['col'][0][:3]
            has_marker = marker_visible and prefs['notify'] and mem['ids']
            if has_marker or color or base.get('fx', 0) == 0:
                marker = [128, 0, 255] if has_marker else rgb
                count = existing.get('len', existing.get('stop', 5) - existing.get('start', 0)) if existing else 5
                seg['i'] = [0, marker] + [rgb] * max(0, count-1)
                seg['fx'] = 0
            else:
                seg['frz'] = False
        segments.append(seg)
    request(prefs, {'seg': segments})


def volume(prefs, mem, percent):
    if mem['suspended'] or not prefs['volume']:
        return
    state = device_state(prefs)
    if not state['on']:
        return
    if (not mem.get('equalizerBase') and mem['volumeUntil'] <= time.time()
            and (prefs['kde'] or not mem['base'])):
        mem['base'] = base_segments(state)
    mem['volumeUntil'] = time.time() + 2
    if prefs.get('controller') and prefs.get('sections'):
        import layout, usb_transport
        sections=layout.validate(prefs['sections'],prefs['controller']['count'])
        if not mem.get('overlayBase'):
            mem['overlayBase']=mem.get('equalizerBase') or base_segments(state)
        color=[255,0,0] if percent > 85 else [255,165,0] if percent > 50 else [0,255,0]
        frame=layout.meter(min(100,percent)/100,sections,prefs['controller']['count'],color)
        usb_transport.client(pixels=frame)
        return
    ids = {seg['id'] for seg in state.get('seg', [])}
    if not {2, 3}.issubset(ids) and state.get('seg'):
        seg = state['seg'][0]
        count = seg.get('len', seg.get('stop', 20) - seg.get('start', 0))
        count = max(1, min(1024, count))
        lit = min(count, round(count * percent / 100))
        color = [255,0,0] if percent > 85 else [255,165,0] if percent > 50 else [0,255,0]
        pixels = [color] * lit + [[0,0,0]] * (count-lit)
        request(prefs, {'seg': [dict(id=seg['id'], fx=0, frz=False, bri=255, i=[0]+pixels)]})
        return
    if percent > 100:
        segments = [dict(id=i, bri=255, fx=1, frz=False, sx=200, col=[[255, 0, 0], [0, 0, 0]]) for i in (2, 3)]
    else:
        color = [255, 0, 0] if percent > 85 else [255, 165, 0] if percent > 50 else [0, 255, 0]
        ix2 = min(100, percent * 2)
        if 0 < percent < 10:
            ix2 = 20
        segments = [dict(id=i, bri=255, fx=98, frz=False, ix=ix, pal=0,
                         col=[color, [30, 30, 30], [0, 0, 0]])
                    for i, ix in ((2, ix2), (3, max(0, (percent - 50) * 2)))]
    request(prefs, {'seg': segments})


def release_equalizer(prefs, mem):
    """Restore the pre-music state; keep snapshot if restoration must retry."""
    snapshot = mem.get('equalizerBase')
    if not snapshot or mem['suspended'] or mem['volumeUntil'] > time.time():
        return
    state = device_state(prefs)
    if not state['on']:
        return
    present = {str(s['id']) for s in state.get('seg', [])}
    if set(snapshot) - present:
        # Historical HTTP snapshots may describe another layout/controller.
        # Do not recreate those segments or import their old colors.
        snapshot = base_segments(state)
        mem['base'] = snapshot.copy()
        print('WLED: discarded snapshot of missing segments', file=sys.stderr)
    segments = [dict(id=int(i), frz=False, **seg) for i, seg in snapshot.items()]
    request(prefs, {'seg': segments, 'tt': 0})
    mem['equalizerBase'] = {}
    apply(dict(prefs, equalizer=False), mem, state)


def equalizer_frame(prefs, mem, rgb, pixels=None):
    if not prefs.get('equalizer') or mem['suspended'] or mem['volumeUntil'] > time.time():
        return False
    state = device_state(prefs)
    if not state['on']:
        return False
    if not mem.get('equalizerBase'):
        mem['equalizerBase'] = base_segments(state)
        if not prefs['kde'] and not mem['base']:
            mem['base'] = mem['equalizerBase'].copy()
        # Persist before the first mutation, so restart can still restore it.
        write_json(RUNTIME / 'state.json', mem)
    if pixels is not None:
        import usb_transport
        if prefs.get('sections'):
            import notification_fx
            pixels=notification_fx.overlay(pixels,prefs['sections'],prefs,mem,time.time())
        return usb_transport.client(pixels=pixels)
    segments = []
    for seg in state.get('seg', []):
        i = seg['id']
        if str(i) not in mem['equalizerBase']:
            continue
        out = dict(id=i, fx=0, frz=False, col=[rgb],
                   bri=mem['equalizerBase'][str(i)]['bri'])
        if i == 2 and prefs['notify'] and mem['ids']:
            out['i'] = [0, [128, 0, 255], rgb, rgb, rgb, rgb]
        segments.append(out)
    if segments:
        request(prefs, {'seg': segments, 'tt': 0})
        return True
    return False


def normalize_host(value):
    if '://' not in value:
        value = 'http://' + value
    p = urllib.parse.urlsplit(value)
    if (p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password
            or p.path not in ('', '/') or p.query or p.fragment
            or not re.fullmatch(r'[A-Za-z0-9.:-]+', p.netloc)):
        raise ValueError(tr("Enter the device IP address or hostname, such as wled.local"))
    _ = p.port
    return value.rstrip('/')


def prepare_enrollment():
    """Called by the USB owner with the shared command lock held."""
    prefs,mem=settings(),runtime()
    if mem.get('equalizerBase'):
        release_equalizer(prefs,mem)
        if mem.get('equalizerBase'):
            raise ValueError(tr("Turn off the equalizer and wait for the volume indicator to finish first"))
    if mem['volumeUntil'] > time.time():
        raise ValueError(tr("Wait for the volume indicator to finish"))


def execute(args):
    cmd = args[0]
    prefs = settings()
    mem = runtime()
    if cmd == 'ports':
        import serial.tools.list_ports
        ports = [dict(port=p.device, name=p.description, label=p.device+' · '+p.description) for p in serial.tools.list_ports.comports()
                 if re.fullmatch(r'/dev/tty(?:USB|ACM)[0-9]+',p.device)]
        return dict(ok=True, ports=ports, settings=prefs)
    if cmd == 'config':
        return dict(ok=True, settings=prefs)
    if cmd == 'ambient-tick':
        import notification_fx
        if (not prefs.get('controller') or mem['suspended'] or mem['volumeUntil']>time.time()
                or (prefs.get('equalizer') and mem.get('equalizerBase'))):
            return dict(ok=True)
        active=notification_fx.active(prefs,mem,time.time())
        if active or mem.get('notifyRendered'):
            apply(prefs,mem)
            mem['notifyRendered']=active
            write_json(RUNTIME/'state.json',mem)
        return dict(ok=True)
    if cmd == 'enroll':
        import usb_transport
        expected=json.loads(args[2]) if len(args)>2 else None
        selected=prefs.get('controller') or {}
        if expected is None and selected.get('backend')=='wesp' and selected.get('port')==args[1]:
            expected=dict(backend='wesp',mac=selected['mac'])
        if expected is not None and (not isinstance(expected,dict)
                or not re.fullmatch(r'[0-9a-f]{12}',expected.get('mac',''))
                or ('count' in expected and (type(expected['count']) is not int or not 1<=expected['count']<=1024))):
            raise ValueError(tr("Invalid expected controller configuration"))
        usb_transport.client(enroll=args[1],expected=expected)
        return dict(ok=True,settings=settings())
    if cmd == 'layout':
        import layout
        if not prefs.get('controller'):
            raise ValueError(tr("Select a controller first"))
        sections=layout.validate(json.loads(args[1]),prefs['controller']['count'])
        prefs['sections']=sections
        CONFIG.mkdir(parents=True,exist_ok=True,mode=0o700)
        write_json(CONFIG/'settings.json',prefs)
        return dict(ok=True,settings=prefs)
    if cmd == 'status':
        import wallpaper
        wallpaper_palette=wallpaper.cached(RUNTIME)
        if not prefs.get('controller') and os.environ.get('WLED_TRANSPORT') != 'http':
            return dict(ok=True,settings=prefs,configured=False,notifications=0,wallpaper=wallpaper_palette)

        worker = read_json(RUNTIME / 'equalizer-status.json', {})
        if prefs['equalizer'] and time.time() - worker.get('updated', 0) > 6:
            worker = dict(message=tr("Equalizer worker is not running"))
        return dict(ok=True, state=device_state(prefs), settings=prefs,
                    notifications=len(mem['ids']), equalizer=worker,wallpaper=wallpaper_palette)
    if not prefs.get('controller') and cmd in ('volume','volume-end','notify-add','notify-close','clear','apply','sleep','wake','shutdown'):
        return dict(ok=True)
    if cmd == 'session-start':
        mem['suspended'] = False
        mem['resume'] = None
        mem['volumeUntil'] = 0
        write_json(RUNTIME / 'state.json', mem)
        return dict(ok=True)
    if cmd in ('sleep', 'shutdown'):
        if not mem['suspended']:
            state = device_state(prefs)
            mem['resume'] = {'on': state['on'], 'bri': state['bri']}
        mem['suspended'] = True
        mem['volumeUntil'] = 0
        write_json(RUNTIME / 'state.json', mem)
        request(prefs, {'on': False})
        return dict(ok=True)
    if cmd == 'wake':
        if mem['resume'] is not None:
            request(prefs, mem['resume'])
        mem['suspended'] = False
        mem['resume'] = None
        write_json(RUNTIME / 'state.json', mem)
        apply(prefs, mem)
        write_json(RUNTIME / 'state.json', mem)
        return dict(ok=True)
    if cmd == 'setting':
        key, value = args[1:3]
        if key == 'host':
            target = normalize_host(value.strip())
            if target == prefs['host']:
                return dict(ok=True, settings=prefs)
            if target != prefs['host'] and mem.get('equalizerBase'):
                release_equalizer(prefs, mem)
                if mem.get('equalizerBase'):
                    raise ValueError(tr("Turn on the previous lighting and wait for the volume indicator to finish so its color can be restored"))
            prefs[key] = target
            mem = dict(ids=[], volumeUntil=0, base={}, suspended=False, resume=None)
        elif key == 'equalizer_decay_ms':
            prefs[key] = validate_decay_ms(value)
        elif key in ('equalizer_palette','equalizer_sensitivity','equalizer_gate','equalizer_attack_ms','notify_style','notify_color','notify_strength'):
            prefs[key]=validate_tuning(key,value)
            if key=='notify_style' and mem['ids']:
                mem['notifyStarted']=max(time.time(),mem['volumeUntil'])
        elif key in ('kde', 'volume', 'notify', 'equalizer', 'reverse_first', 'reverse_second') and value in ('true', 'false'):
            if key == 'kde' and value == 'false' and mem['volumeUntil'] <= time.time():
                try:
                    mem['base'] = mem.get('equalizerBase') or base_segments(device_state(prefs))
                except Exception as e:
                    print(f'WLED: unable to capture manual color: {e}', file=sys.stderr)
            prefs[key] = value == 'true'
            if key == 'volume' and value == 'false':
                mem['volumeUntil'] = 0
        else:
            raise ValueError(tr("Invalid setting"))
        CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json(CONFIG / 'settings.json', prefs)
        write_json(RUNTIME / 'state.json', mem)
        warning = ''
        if key not in ('host', 'reverse_first', 'reverse_second', 'equalizer_decay_ms',
                       'equalizer_palette','equalizer_sensitivity','equalizer_gate','equalizer_attack_ms','notify_style','notify_color','notify_strength'):
            try:
                if key == 'equalizer' and value == 'false':
                    release_equalizer(prefs, mem)
                else:
                    apply(prefs, mem)
            except Exception as e:
                warning = tr("Setting saved, but the device is unavailable")
                print(f'WLED: {e}', file=sys.stderr)
        write_json(RUNTIME / 'state.json', mem)
        return dict(ok=True, settings=prefs, warning=warning)
    if cmd in ('power', 'brightness'):
        if cmd == 'power':
            if args[1] not in ('true', 'false'):
                raise ValueError(tr("Invalid power value"))
            payload = {'on': args[1] == 'true'}
        else:
            value = int(args[1])
            if not 1 <= value <= 255:
                raise ValueError(tr("Brightness must be between 1 and 255"))
            state = device_state(prefs)
            if mem['suspended'] or not state['on']:
                return dict(ok=True, state=state)
            payload = {'bri': value}
        request(prefs, payload)
        state = device_state(prefs)
        if cmd == 'power':
            if state['on'] != payload['on']:
                raise ValueError(tr("WLED did not confirm the power change"))
            mem['volumeUntil'] = 0
            if state['on']:
                apply(prefs, mem, state)
        write_json(RUNTIME / 'state.json', mem)
        return dict(ok=True, state=state)
    if cmd == 'equalizer-frame':
        rgb = [int(v) for v in args[1].split(',')]
        if len(rgb) != 3 or any(not 0 <= v <= 255 for v in rgb):
            raise ValueError(tr("Invalid equalizer color"))
        equalizer_frame(prefs, mem, rgb)
    elif cmd == 'equalizer-idle':
        release_equalizer(prefs, mem)
    elif cmd == 'volume':
        volume(prefs, mem, max(0, int(args[1])))
    elif cmd == 'volume-end':
        if mem['volumeUntil'] and mem['volumeUntil'] <= time.time():
            mem['volumeUntil'] = 0
            apply(prefs, mem)
    elif cmd == 'notify-add':
        ident = int(args[1])
        import notification_fx
        now=time.time()
        running=notification_fx.active(prefs,mem,now)
        preview=mem.get('notifyPreviewUntil',0)>now
        if ident not in mem['ids']:
            mem['ids'].append(ident)
        mem['notifyPreviewUntil']=0
        if not running or preview or mem['volumeUntil']>now:
            mem['notifyStarted']=max(now,mem['volumeUntil'])
        mem['notifyRendered']=True
        write_json(RUNTIME / 'state.json', mem)
        apply(prefs, mem)
    elif cmd == 'notify-close':
        ident = int(args[1])
        mem['ids'] = [i for i in mem['ids'] if i != ident]
        write_json(RUNTIME / 'state.json', mem)
        apply(prefs, mem)
    elif cmd == 'clear':
        mem['ids'] = []
        mem['notifyPreviewUntil']=0
        write_json(RUNTIME / 'state.json', mem)
        apply(prefs, mem)
    elif cmd == 'apply':
        apply(prefs, mem)
    elif cmd == 'notify-preview':
        if mem['suspended'] or not prefs.get('controller') or not device_state(prefs)['on']:
            raise ValueError(tr("Turn on the lighting first"))
        mem['notifyPreviewStart']=max(time.time(),mem['volumeUntil'])
        mem['notifyPreviewUntil']=mem['notifyPreviewStart']+3
        mem['notifyRendered']=True
        write_json(RUNTIME/'state.json',mem)
        apply(prefs,mem)
    else:
        raise ValueError(tr("Unknown command"))
    write_json(RUNTIME / 'state.json', mem)
    return dict(ok=True, notifications=len(mem['ids']))


def dispatch(args):
    if args==['desktop-open']:
        import subprocess
        subprocess.Popen(['/usr/bin/python3',str(Path(__file__).with_name('desktop.py'))],
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,start_new_session=True)
        return dict(ok=True)
    if args[:1]==['firmware-native-ready']:
        import firmware
        root=firmware.state_root()
        with firmware.job_lock(root):
            data=firmware.read_job(root)
            if len(args)!=2 or data.get('token')!=args[1] or data.get('flavor')!='wesp' or data['stage']!='flashed':
                raise ValueError(tr("Prepare the board before confirming installation"))
            firmware.stage(root,data,'installed')
        return dict(ok=True,firmware=data)
    if args[:1]==['receiver-setup-link']:
        import receiver_setup
        return dict(ok=True,setup=read_json(RUNTIME/'receiver-setup.json',{}))
    if args[:1] == ['firmware-connect']:
        import firmware
        root=firmware.state_root()
        with firmware.job_lock(root):
            data=firmware.read_job(root)
            if len(args) != 2 or data['stage'] != 'flashed' or args[1] != data.get('token'):
                raise ValueError(tr("Prepare the board before confirming installation"))
            firmware.stage(root, data, 'connecting', pid=os.getpid(), stamp=firmware.process_stamp(os.getpid()))
        try:
            # Discover LED count only after the firmware's exact MAC matches.
            result=execute(['enroll', data['port'], json.dumps(dict(mac=data['board']['mac']))])
        except Exception:
            with firmware.job_lock(root):
                if firmware.read_job(root).get('token') == data['token']:
                    firmware.stage(root, data, 'installed')
            raise
        with firmware.job_lock(root):
            current=firmware.read_job(root)
            if current.get('token') != data['token'] or current['stage'] != 'connecting':
                raise ValueError(tr("The USB controller changed. Prepare the selected board again"))
            firmware.stage(root, data, 'connected')
        result['firmware']=data
        return result
    if args[:1] == ['firmware-status']:
        import firmware
        return dict(ok=True, firmware=firmware.status())
    if args[:1] in (['firmware-prepare'], ['firmware-prepare-native'], ['firmware-install'], ['firmware-cancel']):
        import firmware
        if len(args) != 2:
            raise ValueError(tr("Prepare the board before confirming installation"))
        return dict(ok=True, firmware=firmware.start(args[0].removeprefix('firmware-'), args[1]))
    import firmware
    if firmware.read_job()['stage'] in firmware.BUSY and args[:1] not in (['config'], ['ports'], ['status']):
        raise ValueError(tr("A controller installation is already running"))
    # Enrollment is serialized by the USB owner, which also serves clients
    # that use the socket protocol directly. Do not hold this lock across it.
    if args[:1]==['enroll']:
        return execute(args)
    with locked():
        return execute(args)


def main():
    try:
        if sys.argv[1:2] == ['blink']:
            ident = int(sys.argv[2])
            for step in range(6):
                with locked():
                    prefs, mem = settings(), runtime()
                    if (ident not in mem['ids'] or not prefs['notify'] or mem['suspended']
                            or mem['volumeUntil'] > time.time()):
                        break
                    apply(prefs, mem, marker_visible=bool(step % 2))
                if step < 5:
                    time.sleep(0.2)
            result = dict(ok=True)
        else:
            result = dispatch(sys.argv[1:])
    except Exception as e:
        print(f'WLED: {type(e).__name__}: {e}', file=sys.stderr)
        try:
            prefs = settings()
        except Exception:
            prefs = DEFAULTS.copy()
        error = str(e) if isinstance(e, ValueError) else tr("Could not contact WLED or execute the command")
        print(json.dumps(dict(ok=False, error=error, settings=prefs), ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

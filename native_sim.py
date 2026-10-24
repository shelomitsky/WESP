"""Software bench for the actual firmware C++ core; never opens a device."""
import ctypes as C
import json
from pathlib import Path
import subprocess
import tempfile
import threading

import effects_config

ROOT=Path(__file__).resolve().parent
_LOCK=threading.Lock()
_LIBRARY=None


class Section(C.Structure):
    _fields_=[('start',C.c_uint16),('count',C.c_uint16),('reverse',C.c_uint8)]


class Preset(C.Structure):
    _fields_=[('id',C.c_char*17),('style',C.c_uint8),('sensitivity',C.c_uint16),
              ('gate',C.c_uint16),('attackMs',C.c_uint16),('decayMs',C.c_uint16),
              ('repeatMs',C.c_uint16),('colors',(C.c_uint8*3)*10)]


class Config(C.Structure):
    _fields_=[('magic',C.c_uint32),('revision',C.c_char*17),('sectionCount',C.c_uint16),
              ('sections',Section*128),('presetCount',C.c_uint8),('active',C.c_uint8),
              ('presets',Preset*8),('wallpaperTimeout',C.c_uint32),('wallpaperFade',C.c_uint32),
              ('notifyMs',C.c_uint16),('notifyStyle',C.c_uint8),('notifyStrength',C.c_uint8),
              ('notifyColor',C.c_uint8*3)]


def library():
    global _LIBRARY
    with _LOCK:
        if _LIBRARY is not None:return _LIBRARY
        # A private temporary build avoids trusting a shared precompiled .so.
        directory=tempfile.TemporaryDirectory(prefix='wesp-native-sim-')
        target=Path(directory.name)/'sim.so'
        try:
            subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-O2','-shared','-fPIC',
                '-I',str(ROOT/'receiver/include'),str(ROOT/'receiver/tests/simulator.cpp'),'-o',str(target)],
                check=True,capture_output=True,text=True,timeout=60)
            lib=C.CDLL(str(target))
            lib.wesp_sim_create.argtypes=[C.c_uint];lib.wesp_sim_create.restype=C.c_void_p
            lib.wesp_sim_destroy.argtypes=[C.c_void_p]
            lib.wesp_sim_config_size.restype=C.c_uint
            if lib.wesp_sim_config_size()!=C.sizeof(Config):raise RuntimeError('Native simulator ABI mismatch')
            lib.wesp_sim_config.argtypes=[C.c_void_p,C.POINTER(Config)];lib.wesp_sim_config.restype=C.c_bool
            lib.wesp_sim_power.argtypes=[C.c_void_p,C.c_bool]
            lib.wesp_sim_audio.argtypes=[C.c_void_p,C.c_float,C.c_float,C.c_uint32];lib.wesp_sim_audio.restype=C.c_bool
            lib.wesp_sim_solid.argtypes=[C.c_void_p,C.POINTER(C.c_uint8),C.c_uint32];lib.wesp_sim_solid.restype=C.c_bool
            lib.wesp_sim_event.argtypes=[C.c_void_p,C.c_int,C.c_char_p,C.c_float,C.c_uint32];lib.wesp_sim_event.restype=C.c_bool
            lib.wesp_sim_heartbeat.argtypes=[C.c_void_p,C.c_uint32];lib.wesp_sim_heartbeat.restype=C.c_bool
            lib.wesp_sim_frame.argtypes=[C.c_void_p,C.c_uint32];lib.wesp_sim_frame.restype=C.POINTER(C.c_uint8)
            lib._build_directory=directory
            _LIBRARY=lib
            return lib
        except Exception:
            directory.cleanup();raise


def config_struct(document,count):
    d=effects_config.validate(document,count);c=Config();c.magic=0x57534601;c.revision=d['revision'].encode()
    c.sectionCount=len(d['sections'])
    for i,(start,length,reverse) in enumerate(d['sections']):c.sections[i]=Section(start,length,reverse)
    c.presetCount=len(d['presets']);c.active=[p['id'] for p in d['presets']].index(d['active'])
    for i,preset in enumerate(d['presets']):
        p=c.presets[i];p.id=preset['id'].encode();p.style=['meter','pulse'].index(preset['style'])
        for field,key in [('sensitivity','sensitivity'),('gate','gate'),('attackMs','attack_ms'),('decayMs','decay_ms'),('repeatMs','repeat_ms')]:setattr(p,field,preset[key])
        for j,rgb in enumerate(preset['colors']):p.colors[j][:]=rgb
    c.wallpaperTimeout=d['wallpaper_timeout_ms'];c.wallpaperFade=d['wallpaper_fade_ms']
    event=d['notification'];c.notifyMs=event['duration_ms'];c.notifyStyle=['flash','pulse','tint','pixel'].index(event['style'])
    c.notifyStrength=event['strength'];c.notifyColor[:]=event['color']
    return c


class Simulator:
    def __init__(self,count):
        effects_config.integer(count,1,1024)
        self.count=count;self.lib=library();self.handle=self.lib.wesp_sim_create(count)
        if not self.handle:raise RuntimeError('Could not create native simulator')

    def close(self):
        if self.handle:self.lib.wesp_sim_destroy(self.handle);self.handle=None

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def configure(self,document):
        value=config_struct(document,self.count);return self.lib.wesp_sim_config(self.handle,C.byref(value))
    def power(self,on):self.lib.wesp_sim_power(self.handle,bool(on))
    def audio(self,rms,bass,at):return self.lib.wesp_sim_audio(self.handle,rms,bass,at)
    def event(self,kind,ref,value,at):return self.lib.wesp_sim_event(self.handle,['notification','volume','clear','clear_volume'].index(kind),ref.encode(),value,at)
    def solid(self,color,at):
        effects_config.colors([color]*10)
        return self.lib.wesp_sim_solid(self.handle,(C.c_uint8*3)(*color),at)
    def heartbeat(self,at):return self.lib.wesp_sim_heartbeat(self.handle,at)
    def frame(self,at):
        data=self.lib.wesp_sim_frame(self.handle,at)
        return [[data[i*3+j] for j in range(3)] for i in range(self.count)]


if __name__=='__main__':
    import argparse,sys
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--count',type=int,default=20)
    options=parser.parse_args()
    with Simulator(options.count) as sim:
        for line in sys.stdin:
            try:
                request=json.loads(line);op=request['op'];at=effects_config.integer(request.get('at',0),0,0xffffffff)
                if op=='configure':result=sim.configure(request['effects'])
                elif op=='power':sim.power(request['on']);result=True
                elif op=='audio':result=sim.audio(request['rms'],request['bass'],at)
                elif op=='event':result=sim.event(request['kind'],request['ref'],request.get('value',0),at)
                elif op=='solid':result=sim.solid(request['color'],at)
                elif op=='heartbeat':result=sim.heartbeat(at)
                elif op=='frame':result=sim.frame(at)
                else:raise ValueError('Unknown simulator command')
                print(json.dumps({'ok':True,'result':result}),flush=True)
            except (ValueError,KeyError,TypeError):print(json.dumps({'ok':False,'error':'Invalid simulator request'}),flush=True)

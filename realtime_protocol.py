"""Fixed-size authenticated audio. No queues, floats or ACKs on the wire."""
import hashlib
import hmac
import math
import re
import struct
import time

WIRE=struct.Struct('!4s8sIIHH')
LOCAL=struct.Struct('!4s6sHQHH')
PACKET_SIZE=40
MAX_AGE_NS=120_000_000


def now_ns():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def level(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
        raise ValueError('Invalid audio level')
    return round(value*65535)


def u16(value):
    if type(value) is not int or not 0<=value<=65535:raise ValueError('Invalid fixed-point level')
    return value


def pack_audio(key,sid,sequence,stamp_ms,rms,bass):
    if len(key)!=32 or len(sid)!=8 or type(sequence) is not int or not 1<=sequence<=0x7fffffff:
        raise ValueError('Invalid audio stream')
    if type(stamp_ms) is not int or not 0<=stamp_ms<=0xffffffff:raise ValueError('Invalid audio clock')
    header=WIRE.pack(b'WSA1',sid,sequence,stamp_ms,u16(rms),u16(bass))
    return header+hmac.new(key,header,hashlib.sha256).digest()[:16]


def unpack_audio(packet,key,sid):
    if len(packet)!=PACKET_SIZE or len(key)!=32 or len(sid)!=8:raise ValueError('Invalid audio packet')
    header,tag=packet[:24],packet[24:]
    if not hmac.compare_digest(tag,hmac.new(key,header,hashlib.sha256).digest()[:16]):
        raise ValueError('Invalid audio authentication')
    magic,actual,sequence,stamp,rms,bass=WIRE.unpack(header)
    if magic!=b'WSA1' or actual!=sid or not 1<=sequence<=0x7fffffff:raise ValueError('Invalid audio stream')
    return sequence,stamp,rms,bass


def pack_local(mac,count,captured_ns,rms,bass):
    if not isinstance(mac,str) or not re.fullmatch('[0-9a-f]{12}',mac) or type(count) is not int or not 1<=count<=1024:
        raise ValueError('Invalid local audio target')
    if type(captured_ns) is not int or not 0<captured_ns<=0xffffffffffffffff:raise ValueError('Invalid capture clock')
    return LOCAL.pack(b'WSL1',bytes.fromhex(mac),count,captured_ns,u16(rms),u16(bass))


def unpack_local(packet):
    if len(packet)!=LOCAL.size:raise ValueError('Invalid local audio packet')
    magic,mac,count,captured,rms,bass=LOCAL.unpack(packet)
    if magic!=b'WSL1' or not 1<=count<=1024 or not captured:raise ValueError('Invalid local audio target')
    return mac.hex(),count,captured,rms,bass


class AudioClock:
    def __init__(self):
        self.anchor_ns=None
        self.received_ns=0
        self.server_ms=0

    def sync(self,sent_ns,received_ns,server_ms):
        if not 0<=received_ns-sent_ns<=80_000_000 or type(server_ms) is not int or not 0<=server_ms<=0xffffffff:
            return False
        self.anchor_ns=(sent_ns+received_ns)//2
        self.received_ns=received_ns
        self.server_ms=server_ms
        return True

    def valid(self,now):
        return self.anchor_ns is not None and 0<=now-self.received_ns<=10_000_000_000

    def stamp(self,captured_ns,now):
        if not self.valid(now) or not 0<=now-captured_ns<=MAX_AGE_NS:
            raise ValueError('Expired audio sample or clock')
        return (self.server_ms+(captured_ns-self.anchor_ns)//1_000_000)&0xffffffff


class DeltaPolicy:
    def __init__(self):
        self.previous=None
        self.last_ns=0

    def eligible(self,rms,bass,now):
        if self.previous is None:return True
        elapsed=now-self.last_ns
        if elapsed<10_000_000:return False
        if elapsed>=400_000_000:return True
        return any(abs(a-b)>=max(64,max(a,b)//32) for a,b in zip((rms,bass),self.previous))

    def sent(self,rms,bass,now):
        self.previous=(rms,bass)
        self.last_ns=now

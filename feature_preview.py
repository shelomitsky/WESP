"""Private latest-only feature mirror. No audio samples, device commands or queues."""
import logging
import mmap
import os
from pathlib import Path
import stat
import struct
import tempfile

import realtime_protocol as rt

LOG=logging.getLogger('wesp.preview')
SIZE=64
COUNTER=struct.Struct('<Q')


class Writer:
    def __init__(self,runtime):
        self.path=Path(runtime)/'audio-preview.bin';self.mapping=None;self.identity=None;self.sequence=0
        temporary=None
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd,name=tempfile.mkstemp(prefix='.audio-preview-',dir=self.path.parent);temporary=Path(name)
            try:
                os.ftruncate(fd,SIZE)
                self.mapping=mmap.mmap(fd,SIZE)
                self.mapping[:]=bytes(SIZE) # Fault in the page before entering the producer loop.
                info=os.fstat(fd);self.identity=(info.st_dev,info.st_ino)
                os.replace(temporary,self.path)
            finally:os.close(fd)
        except OSError:
            if self.mapping is not None:self.mapping.close();self.mapping=None
            LOG.debug('Feature preview unavailable',exc_info=True)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)

    def publish(self,packet):
        if self.mapping is None:return False
        rt.unpack_local(packet)
        self.sequence=(self.sequence+2)&0xfffffffffffffffe or 2
        self.mapping[:8]=COUNTER.pack(self.sequence-1)
        self.mapping[8:32]=packet
        self.mapping[:8]=COUNTER.pack(self.sequence)
        return True

    def close(self):
        if self.mapping is not None:self.mapping.close();self.mapping=None
        try:
            info=self.path.stat()
            if (info.st_dev,info.st_ino)==self.identity:self.path.unlink()
        except OSError:pass


class Reader:
    def __init__(self,runtime):
        self.path=Path(runtime)/'audio-preview.bin';self.mapping=None;self.identity=None

    def read(self,mac,count,now=None):
        try:
            info=self.path.stat(follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size!=SIZE):
                self.close();return None
            identity=(info.st_dev,info.st_ino)
            if self.mapping is None or identity!=self.identity:
                self.close();fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
                try:
                    opened=os.fstat(fd)
                    if (opened.st_dev,opened.st_ino)!=identity:return None
                    self.mapping=mmap.mmap(fd,SIZE,access=mmap.ACCESS_READ);self.identity=identity
                finally:os.close(fd)
            first=COUNTER.unpack(self.mapping[:8])[0]
            if not first or first&1:return None
            packet=self.mapping[8:32]
            if first!=COUNTER.unpack(self.mapping[:8])[0]:return None
            sample=rt.unpack_local(packet)
            if sample[:2]!=(mac,count) or not 0<=(rt.now_ns() if now is None else now)-sample[2]<=rt.MAX_AGE_NS:return None
            return sample
        except (OSError,ValueError,struct.error):self.close();return None

    def close(self):
        if self.mapping is not None:self.mapping.close();self.mapping=None
        self.identity=None

#pragma once
#include "receiver_core.h"
namespace wesp {
struct OtaTransfer {
  bool active=false;
  uint32_t size=0,written=0,updated=0;
  Transport transport=Transport::None;
  char session[17]{};
  bool owned(Transport kind,const char *owner) const { return active && kind==transport && owner && !strcmp(owner,session); }
  bool begin(uint32_t bytes,uint32_t capacity,Transport kind,const char *owner,uint32_t now) {
    if (active || bytes<256 || bytes>capacity || kind==Transport::None || !validSession(owner)) return false;
    active=true;size=bytes;written=0;updated=now;transport=kind;memcpy(session,owner,17);return true;
  }
  bool chunk(uint32_t offset,size_t length,Transport kind,const char *owner) const {
    return owned(kind,owner) && offset==written && length && length<=1024 && length<=size-written;
  }
  void commitChunk(size_t length,uint32_t now) { written+=length;updated=now; }
  bool complete() const { return active && written==size; }
  bool expired(uint32_t now) const { return active && uint32_t(now-updated)>=10000; }
  void abort() { active=false;size=written=0;transport=Transport::None;session[0]=0; }
};
}

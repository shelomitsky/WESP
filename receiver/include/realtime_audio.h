#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace wesp {
constexpr size_t AudioPacketSize=40;
struct AudioSample { uint32_t sequence=0,stamp=0;uint16_t rms=0,bass=0; };
inline uint32_t audioU32(const uint8_t *p) {
  return (uint32_t(p[0])<<24)|(uint32_t(p[1])<<16)|(uint32_t(p[2])<<8)|p[3];
}
class FastAudioPolicy {
  uint8_t stream[8]{};
  uint32_t last=0;
public:
  bool active=false;
  uint32_t accepted=0,rejected=0,stale=0,reordered=0;
  int32_t lastAge=0;
  void revoke() { active=false;last=0;memset(stream,0,sizeof(stream)); }
  void open(const uint8_t *sid) { memcpy(stream,sid,8);last=0;active=true; }
  bool matches(const uint8_t *packet,size_t length) const {
    return active && length==AudioPacketSize && !memcmp(packet,"WSA1",4) && !memcmp(packet+4,stream,8);
  }
  bool accept(const uint8_t *packet,size_t length,uint32_t now,bool authenticated,AudioSample &sample) {
    if (!matches(packet,length) || !authenticated) { ++rejected;return false; }
    uint32_t sequence=audioU32(packet+12),stamp=audioU32(packet+16);
    if (!sequence || sequence>0x7fffffff || sequence<=last) { ++reordered;return false; }
    int32_t age=int32_t(now-stamp);
    if (age < -40 || age>80) { ++stale;return false; }
    sample.sequence=sequence;sample.stamp=stamp;
    sample.rms=(uint16_t(packet[20])<<8)|packet[21];
    sample.bass=(uint16_t(packet[22])<<8)|packet[23];
    last=sequence;lastAge=age;++accepted;return true;
  }
};
}

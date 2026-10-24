#include "realtime_audio.h"
#include <assert.h>
#include <string.h>
using namespace wesp;
static void u32(uint8_t *p,uint32_t v) { for (int i=3;i>=0;--i) { p[i]=v&255;v>>=8; } }
int main() {
  uint8_t sid[8]={1,2,3,4,5,6,7,8},packet[40]{};
  memcpy(packet,"WSA1",4);memcpy(packet+4,sid,8);u32(packet+12,1);u32(packet+16,1000);
  packet[20]=0x30;packet[21]=0x39;packet[22]=0xfd;packet[23]=0xe8;
  FastAudioPolicy policy;AudioSample out{};
  assert(!policy.accept(packet,40,1001,true,out));
  policy.open(sid);
  assert(!policy.accept(packet,39,1001,true,out));
  assert(!policy.accept(packet,40,1001,false,out));
  assert(policy.accept(packet,40,1001,true,out));assert(out.rms==12345 && out.bass==65000);
  assert(!policy.accept(packet,40,1002,true,out)); // duplicate
  u32(packet+12,2);assert(!policy.accept(packet,40,1081,true,out)); // stale
  assert(policy.accept(packet,40,1080,true,out)); // bad packet did not poison sequence
  u32(packet+12,3);u32(packet+16,2000);assert(!policy.accept(packet,40,1959,true,out));
  assert(policy.accept(packet,40,1960,true,out)); // clock uncertainty bound
  u32(packet+12,2);u32(packet+16,2001);assert(!policy.accept(packet,40,2002,true,out));
  packet[4]^=1;u32(packet+12,4);assert(!policy.accept(packet,40,2002,true,out));packet[4]^=1;
  u32(packet+16,0xfffffff0);assert(policy.accept(packet,40,5,true,out)); // millis wrap
  policy.revoke();u32(packet+12,5);assert(!policy.accept(packet,40,5,true,out));
  return 0;
}

#include "ota_policy.h"
#include <cassert>
using namespace wesp;
int main() {
  OtaTransfer ota;
  assert(!ota.begin(2000,1000,Transport::TCP,"0123456789abcdef",0));
  assert(ota.begin(2048,4096,Transport::TCP,"0123456789abcdef",0));
  assert(!ota.chunk(0,1024,Transport::USB,"0123456789abcdef"));
  assert(!ota.chunk(0,1024,Transport::TCP,"1123456789abcdef"));
  assert(!ota.chunk(1,1024,Transport::TCP,"0123456789abcdef"));
  assert(!ota.chunk(0,1025,Transport::TCP,"0123456789abcdef"));
  assert(ota.chunk(0,1024,Transport::TCP,"0123456789abcdef"));ota.commitChunk(1024,1);
  assert(!ota.complete());
  assert(!ota.chunk(0,1024,Transport::TCP,"0123456789abcdef"));
  assert(ota.chunk(1024,1024,Transport::TCP,"0123456789abcdef"));ota.commitChunk(1024,2);
  assert(ota.complete());assert(!ota.expired(10001));assert(ota.expired(10002));
  ota.abort();assert(!ota.complete());assert(!ota.active);
  assert(ota.begin(1024,4096,Transport::TCP,"0123456789abcdef",UINT32_MAX-500));
  assert(!ota.expired(9498));assert(ota.expired(9499));
}

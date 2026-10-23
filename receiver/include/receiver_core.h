#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace wesp {
constexpr size_t MaxPixels = 1024;
constexpr size_t MaxLine = 8192;
constexpr uint32_t WatchdogMs = 1200;
constexpr uint32_t PublishedWatchdogMs = 1500;
enum class Transport { None, USB, TCP };
inline const char *authorizeIdentity(Transport transport,bool hello,const char *mac,const char *requestedMac,const char *token,const char *requestedToken) {
  if ((transport==Transport::TCP || !hello) && (!requestedMac || strcmp(mac,requestedMac))) return "wrong_mac";
  if (transport==Transport::TCP) {
    if (!requestedToken || strlen(requestedToken)!=64) return "unauthorized";
    uint8_t diff=0;
    for (size_t i=0;i<64;++i) diff|=uint8_t(requestedToken[i]^token[i]);
    if (diff) return "unauthorized";
  }
  return nullptr;
}
struct Output { uint8_t gpio; uint16_t count; char order[4]; };
inline bool validPin(unsigned p) {
  return p <= 33 && p != 0 && p != 1 && p != 3 && !(p >= 6 && p <= 12) && p != 20 && p != 24 && !(p >= 28 && p <= 31);
}
inline bool validOrder(const char *s) {
  return s[3]==0 && (!strncmp(s,"RGB",3) || !strncmp(s,"RBG",3) || !strncmp(s,"GRB",3) || !strncmp(s,"GBR",3) || !strncmp(s,"BRG",3) || !strncmp(s,"BGR",3));
}
inline bool validOutputs(const Output *out, size_t n, uint32_t ma) {
  if (!n || n > 8 || ma < 100 || ma > 5000) return false;
  size_t total = 0;
  for (size_t i=0; i<n; ++i) {
    if (!validPin(out[i].gpio) || !out[i].count || !validOrder(out[i].order)) return false;
    for (size_t j=0; j<i; ++j) if (out[i].gpio == out[j].gpio) return false;
    total += out[i].count;
  }
  return total <= MaxPixels;
}
struct Sequence {
  int32_t last = 0;
  bool ready = false;
  bool accept(int32_t id, bool hello) {
    if (id <= last || id <= 0 || (!ready && !hello)) return false;
    last=id; ready=true; return true;
  }
};
inline bool validSession(const char *s) {
  if (!s || strlen(s)!=16) return false;
  for (size_t i=0;i<16;++i) if (!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f'))) return false;
  return true;
}
struct Session {
  Sequence sequence;
  char value[17]{};
  bool accept(const char *s, int32_t id, bool hello, bool usb) {
    if (!validSession(s)) return false;
    if (strcmp(value,s)) {
      if (!hello || (value[0] && !usb) || id<=0) return false;
      sequence=Sequence{};
      memcpy(value,s,17);
    }
    return sequence.accept(id,hello);
  }
};
enum class LineEvent { None, Ready, Discarded };
class LineReader {
  char buf[MaxLine+1]{};
  size_t length=0;
  uint32_t started=0;
  bool discard=false;
public:
  bool expire(uint32_t now) {
    if (length && uint32_t(now-started)>=250 && !discard) { length=0; discard=true; return true; }
    return false;
  }
  LineEvent push(char c, uint32_t now) {
    expire(now);
    if (c=='\n') {
      if (discard) { reset(); return LineEvent::Discarded; }
      buf[length]='\0'; length=0; return LineEvent::Ready;
    }
    if (discard) return LineEvent::None;
    started=now;
    if (length==MaxLine || c=='\0') { discard=true; length=0; return LineEvent::None; }
    buf[length++]=c; return LineEvent::None;
  }
  void reset() { length=0; discard=false; started=0; }
  const char *data() const { return buf; }
};
inline int b64(char c) {
  if (c>='A' && c<='Z') return c-'A';
  if (c>='a' && c<='z') return c-'a'+26;
  if (c>='0' && c<='9') return c-'0'+52;
  if (c=='+') return 62;
  if (c=='/') return 63;
  return -1;
}
class Core {
  uint8_t raw[MaxPixels*3]{};
  uint8_t rendered[MaxPixels*3]{};
  bool hasFrame=false;
  char ownerSession[17]{};
public:
  Output outputs[8]{};
  size_t outputCount=0, count=0;
  uint32_t maxMilliamps=500, lastFrame=0;
  Transport owner=Transport::None;
  bool on=false;
  uint8_t brightness=255;
  void dark() { memset(raw,0,sizeof(raw)); hasFrame=false; owner=Transport::None; ownerSession[0]=0; }
  void off() { on=false; dark(); }
  bool configure(const Output *out, size_t n, uint32_t ma) {
    if (!validOutputs(out,n,ma)) return false;
    off(); outputCount=n; count=0; maxMilliamps=ma;
    for (size_t i=0;i<n;++i) { outputs[i]=out[i]; count+=out[i].count; }
    return true;
  }
  bool tick(uint32_t now) {
    if (owner!=Transport::None && uint32_t(now-lastFrame)>=WatchdogMs) { dark(); return true; }
    return false;
  }
  void disconnect(Transport transport, const char *session="") { if (owner==transport && !strcmp(ownerSession,session)) dark(); }
  bool frame(const char *encoded, size_t n, Transport transport, uint32_t now, const char *session="") {
    if (!count || n!=count || strlen(encoded)!=count*4) return false;
    // RGB lengths are a multiple of three: padding and whitespace are invalid.
    for (size_t i=0; i<count*4; ++i) if (b64(encoded[i])<0) return false;
    if (!on) return true; // Explicit off discards data without acquiring a lease.
    tick(now);
    if (owner!=Transport::None && (owner!=transport || strcmp(ownerSession,session))) return false;
    for (size_t i=0; i<count; ++i) {
      const char *s=encoded+i*4;
      uint32_t word=(uint32_t(b64(s[0]))<<18)|(uint32_t(b64(s[1]))<<12)|(uint32_t(b64(s[2]))<<6)|uint32_t(b64(s[3]));
      raw[3*i]=word>>16; raw[3*i+1]=word>>8; raw[3*i+2]=word;
    }
    lastFrame=now; owner=transport; hasFrame=on;
    strncpy(ownerSession,session,16); ownerSession[16]=0;
    return true;
  }
  const uint8_t *render() {
    memset(rendered,0,sizeof(rendered));
    if (!on || !hasFrame) return rendered;
    uint64_t sum=0;
    for (size_t i=0; i<count*3; ++i) { rendered[i]=(uint16_t(raw[i])*brightness)/255; sum+=rendered[i]; }
    // 20mA per full channel. Integer floor never exceeds the configured budget.
    uint64_t budget=uint64_t(maxMilliamps)*255;
    if (sum*20 > budget) for (size_t i=0; i<count*3; ++i) rendered[i]=uint64_t(rendered[i])*budget/(sum*20);
    return rendered;
  }
};
// Socket presence is independent of WiFiClient::operator bool (connected()).
// Close the old generation before accepting a replacement, even after FIN.
struct TcpConnection {
  bool present=false, authenticated=false;
  Session session;
  bool attach() {
    if (present) return false;
    present=true; authenticated=false; session=Session{}; return true;
  }
  bool poll(bool alive,Core &core) {
    if (!present || alive) return false;
    if (authenticated) core.disconnect(Transport::TCP,session.value);
    present=false; authenticated=false; session=Session{}; return true;
  }
};
}

#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "effects_engine.h"

namespace wesp {
constexpr size_t MaxPixels = 1024;
constexpr size_t MaxLine = 8192;
constexpr uint32_t WatchdogMs = 1200;
constexpr uint32_t PublishedWatchdogMs = 1500;
enum class Transport { None, USB, TCP };
// Called only after identity/session authentication. Network settings must not
// disconnect the sole Wi-Fi management path before an acknowledgement.
inline const char *authorizeConfiguration(Transport transport,bool changesWifi) {
  if (transport==Transport::USB || (transport==Transport::TCP && !changesWifi)) return nullptr;
  return "usb_only";
}
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
  bool accept(const char *s, int32_t id, bool hello, bool usb, bool *fresh=nullptr) {
    if (fresh) *fresh=false;
    if (!validSession(s)) return false;
    bool changed=strcmp(value,s)!=0;
    if (changed) {
      if (!hello || (value[0] && !usb) || id<=0) return false;
      sequence=Sequence{};
      memcpy(value,s,17);
    }
    if (!sequence.accept(id,hello)) return false;
    if (fresh) *fresh=changed;
    return true;
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
enum class StatusCue { None, Boot, Connected };
class Core {
  uint8_t raw[MaxPixels*3]{};
  uint8_t rendered[MaxPixels*3]{};
  bool hasFrame=false;
  char ownerSession[17]{};
  StatusCue statusCue=StatusCue::None;
  bool queuedConnection=false;
  uint32_t statusStarted=0,lastStatusPaint=0;
  uint32_t lastEffectPaint=0;
  bool effectsReady=false;
  bool nativeActive() const { return effects.mode!=FxMode::None; }
  uint32_t leaseMs() const { return nativeActive() && effects.mode!=FxMode::Music?effects.config.wallpaperTimeout:WatchdogMs; }
  bool sameOwner(Transport transport,const char *session) const { return owner==transport && !strcmp(ownerSession,session); }
  bool claim(Transport transport,uint32_t now,const char *session) {
    tick(now);
    if (!on || !validSession(session)) return false;
    if (owner!=Transport::None && !sameOwner(transport,session) && uint32_t(now-lastFrame)<leaseMs()) return false;
    owner=transport;memcpy(ownerSession,session,17);lastFrame=now;clearStatus();return true;
  }
  void clearStatus() { statusCue=StatusCue::None; queuedConnection=false; }
  void advanceStatus(uint32_t now) {
    if (statusCue==StatusCue::None || uint32_t(now-statusStarted)<700) return;
    if (statusCue==StatusCue::Boot && queuedConnection) {
      statusCue=StatusCue::Connected; queuedConnection=false; statusStarted+=700;
      if (uint32_t(now-statusStarted)<700) return;
    }
    clearStatus();
  }
public:
  EffectsEngine effects;
  Output outputs[8]{};
  size_t outputCount=0, count=0;
  uint32_t maxMilliamps=500, lastFrame=0;
  Transport owner=Transport::None;
  bool on=false;
  uint8_t brightness=255;
  void dark() { memset(raw,0,sizeof(raw)); hasFrame=false;owner=Transport::None;ownerSession[0]=0;clearStatus();effects.reset(); }
  void off() { on=false; dark(); }
  bool configure(const Output *out, size_t n, uint32_t ma) {
    if (!validOutputs(out,n,ma)) return false;
    off(); outputCount=n; count=0; maxMilliamps=ma;
    for (size_t i=0;i<n;++i) { outputs[i]=out[i]; count+=out[i].count; }
    effectsReady=validEffects(effects.config,count);
    return true;
  }
  bool configureEffects(const EffectsConfig &next) {
    if (!validEffects(next,count)) return false;
    // CFG changes parameters, never frame ownership, input time or power.
    effects.config=next;memcpy(effects.palette,next.presets[next.active].colors,sizeof(effects.palette));
    effectsReady=true;return true;
  }
  bool effectRevision(const char *revision) const { return effectsReady && revision && !strcmp(revision,effects.config.revision); }
  bool canAudio(Transport transport,uint32_t now,const char *session,const char *revision) const {
    return on && validSession(session) && effectRevision(revision) &&
      (owner==Transport::None || sameOwner(transport,session) || uint32_t(now-lastFrame)>=leaseMs());
  }
  bool audio(float rms,float bass,Transport transport,uint32_t now,const char *session,const char *revision) {
    if (!effectRevision(revision) || !isfinite(rms) || !isfinite(bass) || rms<0 || rms>1 || bass<0 || bass>1 || !claim(transport,now,session)) return false;
    hasFrame=false;effects.audio(rms,bass,now);return true;
  }
  bool startEffect(FxMode mode,const uint8_t *color,Transport transport,uint32_t now,const char *session,const char *revision) {
    if ((mode!=FxMode::Solid && mode!=FxMode::Runner) || !color || !effectRevision(revision) || !claim(transport,now,session)) return false;
    hasFrame=false;effects.start(mode,color,now);return true;
  }
  bool keepalive(Transport transport,uint32_t now,const char *session,const char *revision) {
    if (!on || !nativeActive() || effects.mode==FxMode::Music || !effectRevision(revision) || !sameOwner(transport,session) || uint32_t(now-lastFrame)>=leaseMs()) return false;
    lastFrame=now;effects.fade=1;return true;
  }
  bool event(FxEvent kind,const char *ref,float value,Transport transport,uint32_t now,const char *session,const char *revision) {
    if (!on || !nativeActive() || !effectRevision(revision) || !sameOwner(transport,session) || !isfinite(value) || value<0 || value>1 || uint32_t(now-lastFrame)>=leaseMs()) return false;
    return effects.event(kind,ref,value,now); // Events never renew the base lease.
  }
  bool setPalette(const uint8_t colors[10][3],Transport transport,const char *session,const char *revision) {
    if (!on || !nativeActive() || !sameOwner(transport,session) || !effectRevision(revision)) return false;
    memcpy(effects.palette,colors,sizeof(effects.palette));return true;
  }
  bool announceBoot(uint32_t now,bool outputsReady) {
    advanceStatus(now);
    if (!outputsReady || !count || owner!=Transport::None || nativeActive() || statusCue!=StatusCue::None) return false;
    statusCue=StatusCue::Boot; statusStarted=now; lastStatusPaint=now-20;
    return true;
  }
  bool announceConnected(uint32_t now,bool outputsReady) {
    advanceStatus(now);
    // A new handshake must not obscure an already active stream/owner.
    if (!outputsReady || !count || owner!=Transport::None || nativeActive() || statusCue==StatusCue::Connected) return false;
    if (statusCue==StatusCue::Boot) {
      if (queuedConnection) return false;
      queuedConnection=true; return true;
    }
    statusCue=StatusCue::Connected; statusStarted=now; lastStatusPaint=now-20;
    return true;
  }
  bool statusTick(uint32_t now) {
    bool active=statusCue!=StatusCue::None;
    advanceStatus(now);
    if (statusCue==StatusCue::None) return active;
    if (uint32_t(now-lastStatusPaint)<20) return false;
    lastStatusPaint=now; return true;
  }
  bool tick(uint32_t now) {
    if (owner!=Transport::None || nativeActive()) {
      uint32_t age=uint32_t(now-lastFrame),deadline=leaseMs();
      if (age>=deadline) {
        if (nativeActive() && effects.mode!=FxMode::Music && effects.config.wallpaperFade && age-deadline<effects.config.wallpaperFade)
          effects.fade=1-float(age-deadline)/effects.config.wallpaperFade;
        else { dark();return true; }
      }
      if (nativeActive() && uint32_t(now-lastEffectPaint)>=10) { lastEffectPaint=now;return true; }
    }
    return false;
  }
  void disconnect(Transport transport, const char *session="") {
    if (!sameOwner(transport,session)) return;
    if (nativeActive() && effects.mode!=FxMode::Music) { owner=Transport::None;ownerSession[0]=0; }
    else dark();
  }
  bool frame(const char *encoded, size_t n, Transport transport, uint32_t now, const char *session="") {
    if (!count || n!=count || strlen(encoded)!=count*4) return false;
    // RGB lengths are a multiple of three: padding and whitespace are invalid.
    for (size_t i=0; i<count*4; ++i) if (b64(encoded[i])<0) return false;
    if (!on) return true; // Explicit off discards data without acquiring a lease.
    tick(now);
    if (owner!=Transport::None && (owner!=transport || strcmp(ownerSession,session))) return false;
    effects.reset();
    for (size_t i=0; i<count; ++i) {
      const char *s=encoded+i*4;
      uint32_t word=(uint32_t(b64(s[0]))<<18)|(uint32_t(b64(s[1]))<<12)|(uint32_t(b64(s[2]))<<6)|uint32_t(b64(s[3]));
      raw[3*i]=word>>16; raw[3*i+1]=word>>8; raw[3*i+2]=word;
    }
    lastFrame=now; owner=transport; hasFrame=on;
    strncpy(ownerSession,session,16); ownerSession[16]=0;
    return true;
  }
  const uint8_t *render(uint32_t now=0) {
    advanceStatus(now);
    memset(rendered,0,sizeof(rendered));
    if (statusCue!=StatusCue::None) {
      const uint8_t amber[3]={255,96,0},green[3]={0,255,48};
      const uint8_t *color=statusCue==StatusCue::Boot?amber:green;
      size_t start=0;
      for (size_t i=0;i<outputCount;++i) {
        size_t head=uint32_t(now-statusStarted)*outputs[i].count/700;
        for (size_t tail=0;tail<3 && tail<=head;++tail) {
          for (size_t channel=0;channel<3;++channel)
            rendered[(start+head-tail)*3+channel]=uint16_t(color[channel])*(20>>tail)/255;
        }
        start+=outputs[i].count;
      }
    } else if (on && nativeActive()) {
      effects.render(rendered,count,now);
      for (size_t i=0;i<count*3;++i) rendered[i]=uint16_t(rendered[i])*brightness/255;
    } else if (on && hasFrame) {
      for (size_t i=0;i<count*3;++i) rendered[i]=(uint16_t(raw[i])*brightness)/255;
    }
    uint64_t sum=0;
    for (size_t i=0;i<count*3;++i) sum+=rendered[i];
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

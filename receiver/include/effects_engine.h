#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>

namespace wesp {
constexpr size_t MaxFxSections=128,MaxFxPresets=8;
constexpr uint32_t EffectsMagic=0x57534601;
struct FxSection { uint16_t start,count; uint8_t reverse; };
struct FxPreset {
  char id[17]{};
  uint8_t style=0; // meter, pulse
  uint16_t sensitivity=100,gate=6,attackMs=0,decayMs=250,repeatMs=1000;
  uint8_t colors[10][3]{};
};
struct EffectsConfig {
  uint32_t magic=EffectsMagic;
  char revision[17]{};
  uint16_t sectionCount=0;
  FxSection sections[MaxFxSections]{};
  uint8_t presetCount=0,active=0;
  FxPreset presets[MaxFxPresets]{};
  uint32_t wallpaperTimeout=8000,wallpaperFade=1000;
  uint16_t notifyMs=1600;
  uint8_t notifyStyle=0,notifyStrength=60,notifyColor[3]={128,0,255};
};
inline bool fxIdentity(const char *text) {
  if (!text || strnlen(text,17)!=16) return false;
  for (size_t i=0;i<16;++i) if (!((text[i]>='0'&&text[i]<='9')||(text[i]>='a'&&text[i]<='f'))) return false;
  return true;
}
inline bool validEffects(const EffectsConfig &c,size_t count) {
  if (c.magic!=EffectsMagic || !fxIdentity(c.revision) || !c.sectionCount || c.sectionCount>MaxFxSections ||
      !c.presetCount || c.presetCount>MaxFxPresets || c.active>=c.presetCount ||
      c.wallpaperTimeout<1500 || c.wallpaperTimeout>60000 || c.wallpaperFade>10000 ||
      c.notifyMs<100 || c.notifyMs>10000 || c.notifyStyle>3 || c.notifyStrength<10 || c.notifyStrength>100) return false;
  for (size_t i=0;i<c.sectionCount;++i) {
    const FxSection &s=c.sections[i];
    if (!s.count || s.reverse>1 || size_t(s.start)+s.count>count) return false;
    for (size_t j=0;j<i;++j) if (s.start<c.sections[j].start+c.sections[j].count && c.sections[j].start<s.start+s.count) return false;
  }
  for (size_t i=0;i<c.presetCount;++i) {
    const FxPreset &p=c.presets[i];
    size_t n=strnlen(p.id,sizeof(p.id));
    if (!n || n>16 || p.style>1 || p.sensitivity<50 || p.sensitivity>200 || p.gate>30 ||
        p.attackMs>300 || p.decayMs<80 || p.decayMs>600 || (p.repeatMs && (p.repeatMs<180 || p.repeatMs>5000))) return false;
    for (size_t k=0;k<n;++k) if (!((p.id[k]>='a'&&p.id[k]<='z')||(p.id[k]>='0'&&p.id[k]<='9')||p.id[k]=='-'||p.id[k]=='_')) return false;
    for (size_t j=0;j<i;++j) if (!strcmp(p.id,c.presets[j].id)) return false;
  }
  return true;
}
enum class FxMode { None,Music,Solid,Runner };
enum class FxEvent { Notification,Volume,Clear,ClearVolume };
inline float fxClamp(float n,float low=0,float high=1) { return n<low?low:n>high?high:n; }
class EffectsEngine {
  float rms=0,bass=0,reference=.1f,history=0,previous=0;
  uint32_t lastTime=0,lastInput=0,lastBeat=0,started=0,notifyStart=0,volumeStart=0;
  bool clockReady=false,beatReady=false,notification=false,volume=false;
  char notifyRef[17]{},volumeRef[17]{};
  float volumeLevel=0;
  uint8_t solid[3]{};
public:
  EffectsConfig config;
  FxMode mode=FxMode::None;
  float level=0,pulse=0;
  float fade=1;
  uint8_t palette[10][3]{};
  void reset() {
    mode=FxMode::None;level=pulse=rms=bass=history=previous=0;reference=.1f;
    clockReady=beatReady=notification=volume=false;fade=1;
  }
  void select(FxMode next,uint32_t now) {
    if (mode!=next) {
      // Scene changes discard old signal state and DSP history.
      bool keepNotification=notification,keepVolume=volume;
      reset();notification=keepNotification;volume=keepVolume;mode=next;started=now;
      memcpy(palette,config.presets[config.active].colors,sizeof(palette));
    }
    fade=1;
  }
  void advance(uint32_t now,bool repeat=true) {
    float elapsed=clockReady?uint32_t(now-lastTime)/1000.f:1.f/60;
    if (elapsed>2) { level=pulse=history=previous=0;reference=.1f;beatReady=false;elapsed=1.f/60; }
    clockReady=true;lastTime=now;
    const FxPreset &p=config.presets[config.active];
    history+=(bass-history)*(1-expf(-elapsed/.35f));
    pulse*=expf(-elapsed/.18f);
    if (repeat && mode==FxMode::Music && p.style==1 && p.repeatMs && beatReady &&
        fmaxf(bass,rms*.8f)>fmaxf(p.gate/1000.f,.003f) && uint32_t(now-lastBeat)>=p.repeatMs) {
      pulse=1;lastBeat=now;
    }
    float drive=fmaxf(bass,rms*.8f),gate=p.gate/1000.f,target=0;
    if (drive>gate) {
      float rate=drive>reference?.08f:.006f;
      reference+=(drive-reference)*(1-powf(1-rate,elapsed*60));reference=fmaxf(.02f,reference);
      target=powf(fxClamp(drive/(reference*1.4f)*p.sensitivity/100.f),1.1f);
    }
    if (target>level) {
      float amount=p.attackMs?fminf(.95f,1-powf(.1f,1000.f/(60*p.attackMs))):.95f;
      level+=(target-level)*(1-powf(1-amount,elapsed*60));
    } else level=fmaxf(target,level*powf(.1f,elapsed*1000/p.decayMs));
    if (level<.02f) level=0;
    if (pulse<.005f) pulse=0;
  }
  void audio(float nextRms,float nextBass,uint32_t now) {
    select(FxMode::Music,now);advance(now,false);
    const FxPreset &p=config.presets[config.active];
    if (uint32_t(now-lastInput)>2000) { history=previous=0;beatReady=false; }
    bool above=nextBass>fmaxf(p.gate/1000.f,.003f);
    bool onset=above && nextBass>history*1.7f && nextBass>previous*1.25f;
    bool audible=fmaxf(nextBass,nextRms*.8f)>fmaxf(p.gate/1000.f,.003f);
    bool repeat=p.style==1 && p.repeatMs && audible && (!beatReady || uint32_t(now-lastBeat)>=p.repeatMs);
    if ((onset || repeat) && (!beatReady || uint32_t(now-lastBeat)>=180)) { pulse=1;lastBeat=now;beatReady=true; }
    previous=nextBass;rms=nextRms;bass=nextBass;lastInput=now;
    // Incorporate the first sample without waiting for the first render tick.
    if (started==now) { clockReady=false;advance(now); }
  }
  void start(FxMode next,const uint8_t *color,uint32_t now) { select(next,now);memcpy(solid,color,3); }
  bool event(FxEvent kind,const char *ref,float value,uint32_t now) {
    if (kind==FxEvent::Clear) { notification=false;return true; }
    if (kind==FxEvent::ClearVolume) { volume=false;return true; }
    if (!fxIdentity(ref)) return false;
    char *previousRef=kind==FxEvent::Volume?volumeRef:notifyRef;
    if (!strcmp(ref,previousRef)) return true;
    memcpy(previousRef,ref,17);
    if (kind==FxEvent::Volume) { volume=true;volumeStart=now;volumeLevel=value; }
    else { notification=true;notifyStart=volume && uint32_t(now-volumeStart)<2000?volumeStart+2000:now; }
    return true;
  }
  void render(uint8_t *out,size_t count,uint32_t now) {
    advance(now);memset(out,0,count*3);
    float height=config.presets[config.active].style?fxClamp(level*.6f+pulse*.4f):level;
    bool volumeActive=volume && uint32_t(now-volumeStart)<2000;
    int32_t eventAge=int32_t(now-notifyStart);
    bool eventActive=notification && eventAge>=0 && uint32_t(eventAge)<config.notifyMs;
    float strength=config.notifyStrength/100.f;
    if (config.notifyStyle==0) { float phase=sinf(3.14159265f*(uint32_t(eventAge)%800)/800.f);strength*=phase*phase; }
    else if (config.notifyStyle==1) { float phase=sinf(3.14159265f*eventAge/config.notifyMs);strength*=.15f+.85f*phase*phase; }
    for (size_t s=0;s<config.sectionCount;++s) {
      const FxSection &section=config.sections[s];
      size_t head=(uint32_t(now-started)/50)%section.count;
      for (size_t logical=0;logical<section.count;++logical) {
        size_t physical=section.start+(section.reverse?section.count-1-logical:logical);
        const uint8_t *color=mode==FxMode::Music?palette[(logical*10)/section.count]:solid;
        float amount=mode==FxMode::Music?fxClamp(height*section.count-logical):mode==FxMode::Runner?(logical==head?1:0):1;
        uint8_t volColor[3]={uint8_t(volumeLevel>.5f?255:0),uint8_t(volumeLevel>.85f?0:volumeLevel>.5f?165:255),0};
        if (volumeActive) { color=volColor;amount=fxClamp(volumeLevel*section.count-logical); }
        for (size_t channel=0;channel<3;++channel) {
          float v=color[channel]*amount;
          if (!volumeActive && eventActive && (config.notifyStyle!=3 || (s==0 && logical==0))) v=v*(1-strength)+config.notifyColor[channel]*strength;
          out[physical*3+channel]=uint8_t(lroundf(fxClamp(v*fade,0,255)));
        }
      }
    }
  }
};
}

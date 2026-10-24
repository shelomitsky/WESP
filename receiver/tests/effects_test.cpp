#include "receiver_core.h"
#include <cassert>
#include <cstring>
#include <initializer_list>
using namespace wesp;
static const char *session="0123456789abcdef",*rev="1111111111111111";
static EffectsConfig config() {
  EffectsConfig c;
  strcpy(c.revision,rev);
  c.sectionCount=2;c.sections[0]={1,3,false};c.sections[1]={5,3,true};
  c.presetCount=1;c.active=0;strcpy(c.presets[0].id,"custom");
  for (int i=0;i<10;++i) { c.presets[0].colors[i][0]=0;c.presets[0].colors[i][1]=180;c.presets[0].colors[i][2]=30; }
  c.wallpaperTimeout=8000;c.wallpaperFade=1000;
  c.notifyStyle=2;c.notifyStrength=100;c.notifyMs=100;
  c.notifyColor[0]=100;c.notifyColor[1]=0;c.notifyColor[2]=0;
  return c;
}
int main() {
  Core core;Output out{2,9,"GRB"};assert(core.configure(&out,1,500));
  EffectsConfig c=config();assert(core.configureEffects(c));core.on=true;
  assert(!core.audio(.2f,.2f,Transport::TCP,0,session,"2222222222222222"));
  assert(core.audio(.2f,.2f,Transport::TCP,0,session,rev));
  const uint8_t *rgb=core.render(0);assert(rgb[1*3+1]>0 && rgb[7*3+1]>0);
  for (int i: {0,4,8})assert(rgb[i*3]==0 && rgb[i*3+1]==0 && rgb[i*3+2]==0);
  assert(core.event(FxEvent::Notification,"3333333333333333",0,Transport::TCP,10,session,rev));
  assert(core.render(20)[3]==100);
  assert(core.audio(0,0,Transport::TCP,40,session,rev));
  assert(core.audio(0,0,Transport::TCP,80,session,rev));
  assert(core.render(120)[3]==0); // finite event ends, revealing current music
  assert(core.effects.level<.9f);
  assert(core.event(FxEvent::Notification,"3333333333333333",0,Transport::TCP,130,session,rev));
  assert(core.render(130)[3]==0); // duplicate acknowledged without replay
  assert(!core.event(FxEvent::Notification,nullptr,0,Transport::TCP,131,session,rev));
  core.off();assert(!core.audio(.3f,.3f,Transport::TCP,140,session,rev));
  assert(!core.keepalive(Transport::TCP,140,session,rev));assert(core.render(140)[4]==0);
  core.on=true;
  uint8_t blue[3]={0,0,100};assert(core.startEffect(FxMode::Solid,blue,Transport::TCP,200,session,rev));
  core.tick(7200);assert(core.keepalive(Transport::TCP,7200,session,rev));
  assert(core.render(15199)[5]==100);
  core.tick(15700);assert(core.render(15700)[5]==50);
  assert(!core.keepalive(Transport::TCP,15700,session,rev));
  core.tick(16200);assert(core.render(16200)[5]==0);
  assert(core.startEffect(FxMode::Solid,blue,Transport::TCP,17000,session,rev));
  core.disconnect(Transport::TCP,session);assert(core.render(17001)[5]==100);
  core.tick(26000);assert(core.render(26000)[5]==0);
  assert(core.audio(.3f,.3f,Transport::TCP,27000,session,rev));
  assert(core.tick(28200));assert(core.render(28200)[4]==0);
  c.sections[1].start=2;assert(!core.configureEffects(c)); // overlap never commits
  c=config();c.presets[0].style=1;c.presets[0].repeatMs=500;
  assert(core.configureEffects(c));core.on=true;
  assert(core.audio(.2f,.2f,Transport::TCP,30000,session,rev));core.render(30000);
  for (uint32_t t=30050;t<=30500;t+=50) { assert(core.audio(.2f,.2f,Transport::TCP,t,session,rev));core.render(t); }
  assert(core.effects.pulse>.8f); // steady tone gets configured repeated accent
  core.off();assert(core.render(30600)[4]==0);
  Core cfgLease;assert(cfgLease.configure(&out,1,500));c=config();assert(cfgLease.configureEffects(c));cfgLease.on=true;
  assert(cfgLease.audio(.2f,.2f,Transport::TCP,100,session,rev));
  strcpy(c.revision,"2222222222222222");c.presets[0].sensitivity=110;
  assert(cfgLease.configureEffects(c));
  assert(cfgLease.effects.mode==FxMode::Music && cfgLease.lastFrame==100);
  assert(cfgLease.tick(1300));assert(cfgLease.render(1300)[4]==0);
  Core tone;assert(tone.configure(&out,1,500));c=config();c.presets[0].style=1;c.presets[0].repeatMs=500;
  assert(tone.configureEffects(c));tone.on=true;
  assert(tone.audio(.2f,0,Transport::TCP,100,session,rev));
  for (uint32_t t=150;t<=600;t+=50) { assert(tone.audio(.2f,0,Transport::TCP,t,session,rev));tone.render(t); }
  assert(tone.effects.pulse>.8f); // steady non-bass tone also repeats
  assert(!tone.audio(NAN,.2f,Transport::TCP,650,session,rev));assert(tone.lastFrame==600);
  Core localRepeat;assert(localRepeat.configure(&out,1,500));c=config();c.presets[0].style=1;c.presets[0].repeatMs=500;
  assert(localRepeat.configureEffects(c));localRepeat.on=true;
  assert(localRepeat.audio(.2f,0,Transport::TCP,100,session,rev));
  for (uint32_t t=110;t<=600;t+=10) { localRepeat.tick(t);localRepeat.render(t); }
  assert(localRepeat.effects.pulse>.9f); // repeat is clocked locally without another input packet
  assert(localRepeat.audio(0,0,Transport::TCP,1100,session,rev));localRepeat.render(1100);
  assert(localRepeat.effects.pulse<.2f); // silence at a repeat boundary does not fire an old accent
  Core fastTick;assert(fastTick.configure(&out,1,500));c=config();assert(fastTick.configureEffects(c));fastTick.on=true;
  assert(fastTick.audio(.2f,.2f,Transport::TCP,100,session,rev));assert(fastTick.tick(100));
  assert(fastTick.tick(110)); // active native effects paint at10ms rather than20ms
  assert(fastTick.canAudio(Transport::TCP,111,session,rev));
  assert(!fastTick.canAudio(Transport::USB,111,"1111111111111111",rev));
  assert(fastTick.lastFrame==100); // opening a data grant must not renew a lease
  Core dense,sparse;assert(dense.configure(&out,1,500));assert(sparse.configure(&out,1,500));
  c=config();c.presets[0].style=1;c.presets[0].repeatMs=0;
  assert(dense.configureEffects(c));assert(sparse.configureEffects(c));dense.on=sparse.on=true;
  assert(dense.audio(.2f,.2f,Transport::TCP,100,session,rev));assert(sparse.audio(.2f,.2f,Transport::TCP,100,session,rev));
  for (uint32_t t=110;t<1100;t+=10) {
    assert(dense.audio(.2f,.2f,Transport::TCP,t,session,rev));
    if (t==500 || t==900) assert(sparse.audio(.2f,.2f,Transport::TCP,t,session,rev));
    dense.render(t);sparse.render(t);
  }
  assert(dense.audio(.28f,.28f,Transport::TCP,1100,session,rev));assert(sparse.audio(.28f,.28f,Transport::TCP,1100,session,rev));
  dense.render(1100);sparse.render(1100);
  assert(fabsf(dense.effects.pulse-sparse.effects.pulse)<.01f); // packet thinning must not invent a beat
}

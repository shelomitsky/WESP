#include "receiver_core.h"
#include "realtime_audio.h"
using namespace wesp;
struct SimulatedReceiver: Core { FastAudioPolicy realtime; };
extern "C" {
void *wesp_sim_create(unsigned count) {
  if (!count || count>MaxPixels) return nullptr;
  SimulatedReceiver *core=new SimulatedReceiver();Output output{2,uint16_t(count),"GRB"};core->configure(&output,1,500);return core;
}
void wesp_sim_destroy(void *ptr) { delete static_cast<SimulatedReceiver *>(ptr); }
unsigned wesp_sim_config_size() { return sizeof(EffectsConfig); }
bool wesp_sim_config(void *ptr,const EffectsConfig *cfg) {
  SimulatedReceiver &c=*static_cast<SimulatedReceiver *>(ptr);bool changed=!c.effectRevision(cfg->revision);
  if (!c.configureEffects(*cfg)) return false;
  if (changed) c.realtime.revoke();
  return true;
}
void wesp_sim_power(void *ptr,bool on) {
  SimulatedReceiver &c=*static_cast<SimulatedReceiver *>(ptr);if (on) c.on=true;else { c.off();c.realtime.revoke(); }
}
bool wesp_sim_audio(void *ptr,float rms,float bass,uint32_t now) {
  Core &c=*static_cast<SimulatedReceiver *>(ptr);return c.audio(rms,bass,Transport::TCP,now,"0123456789abcdef",c.effects.config.revision);
}
bool wesp_sim_solid(void *ptr,const uint8_t *color,uint32_t now) {
  Core &c=*static_cast<SimulatedReceiver *>(ptr);return c.startEffect(FxMode::Solid,color,Transport::TCP,now,"0123456789abcdef",c.effects.config.revision);
}
bool wesp_sim_event(void *ptr,int kind,const char *ref,float value,uint32_t now) {
  Core &c=*static_cast<SimulatedReceiver *>(ptr);return c.event(static_cast<FxEvent>(kind),ref,value,Transport::TCP,now,"0123456789abcdef",c.effects.config.revision);
}
bool wesp_sim_heartbeat(void *ptr,uint32_t now) {
  Core &c=*static_cast<SimulatedReceiver *>(ptr);return c.keepalive(Transport::TCP,now,"0123456789abcdef",c.effects.config.revision);
}
const uint8_t *wesp_sim_frame(void *ptr,uint32_t now) {
  Core &c=*static_cast<SimulatedReceiver *>(ptr);c.tick(now);return c.render(now);
}
bool wesp_sim_stream(void *ptr,const uint8_t *sid,uint32_t now) {
  SimulatedReceiver &c=*static_cast<SimulatedReceiver *>(ptr);
  if (!c.canAudio(Transport::TCP,now,"0123456789abcdef",c.effects.config.revision)) return false;
  c.realtime.open(sid);return true;
}
bool wesp_sim_datagrams(void *ptr,const uint8_t *packets,unsigned count,const uint8_t *verified,uint32_t now) {
  SimulatedReceiver &c=*static_cast<SimulatedReceiver *>(ptr);if (!c.on || count>8) return false;
  AudioSample newest{};bool have=false;
  for (unsigned i=0;i<count;++i) if (c.realtime.accept(packets+i*AudioPacketSize,AudioPacketSize,now,verified[i],newest)) have=true;
  return have && c.audio(newest.rms/65535.f,newest.bass/65535.f,Transport::TCP,now,"0123456789abcdef",c.effects.config.revision);
}
uint32_t wesp_sim_last_frame(void *ptr) { return static_cast<SimulatedReceiver *>(ptr)->lastFrame; }
}

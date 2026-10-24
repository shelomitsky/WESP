#include "receiver_core.h"
using namespace wesp;
extern "C" {
void *wesp_sim_create(unsigned count) {
  if (!count || count>MaxPixels) return nullptr;
  Core *core=new Core();Output output{2,uint16_t(count),"GRB"};core->configure(&output,1,500);return core;
}
void wesp_sim_destroy(void *ptr) { delete static_cast<Core *>(ptr); }
unsigned wesp_sim_config_size() { return sizeof(EffectsConfig); }
bool wesp_sim_config(void *ptr,const EffectsConfig *cfg) { return static_cast<Core *>(ptr)->configureEffects(*cfg); }
void wesp_sim_power(void *ptr,bool on) { if (on) static_cast<Core *>(ptr)->on=true;else static_cast<Core *>(ptr)->off(); }
bool wesp_sim_audio(void *ptr,float rms,float bass,uint32_t now) {
  Core &c=*static_cast<Core *>(ptr);return c.audio(rms,bass,Transport::TCP,now,"0123456789abcdef",c.effects.config.revision);
}
bool wesp_sim_solid(void *ptr,const uint8_t *color,uint32_t now) {
  Core &c=*static_cast<Core *>(ptr);return c.startEffect(FxMode::Solid,color,Transport::TCP,now,"0123456789abcdef",c.effects.config.revision);
}
bool wesp_sim_event(void *ptr,int kind,const char *ref,float value,uint32_t now) {
  Core &c=*static_cast<Core *>(ptr);return c.event(static_cast<FxEvent>(kind),ref,value,Transport::TCP,now,"0123456789abcdef",c.effects.config.revision);
}
bool wesp_sim_heartbeat(void *ptr,uint32_t now) {
  Core &c=*static_cast<Core *>(ptr);return c.keepalive(Transport::TCP,now,"0123456789abcdef",c.effects.config.revision);
}
const uint8_t *wesp_sim_frame(void *ptr,uint32_t now) {
  Core &c=*static_cast<Core *>(ptr);c.tick(now);return c.render(now);
}
}

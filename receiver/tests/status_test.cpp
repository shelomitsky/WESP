#include "receiver_core.h"
#include <cassert>
using namespace wesp;

static void black(const uint8_t *pixels,size_t count) {
  for(size_t i=0;i<count*3;++i) assert(pixels[i]==0);
}

int main() {
  Core empty;
  assert(!empty.announceBoot(0,true));
  assert(!empty.announceConnected(0,true));
  black(empty.render(0),MaxPixels);

  Output outputs[]={{2,4,"GRB"},{4,2,"RGB"}};
  Core c;
  assert(c.configure(outputs,2,500));
  assert(!c.announceBoot(0,false)); // RMT install failed: stay dark
  assert(!c.announceConnected(0,false));
  black(c.render(0),6);
  assert(c.announceBoot(100,true));
  const uint8_t *p=c.render(100);
  assert(p[0]==20 && p[1]==7 && p[2]==0);
  assert(p[12]==20 && p[13]==7);
  assert(!c.on && c.owner==Transport::None && c.lastFrame==0);
  assert(c.statusTick(100));
  assert(!c.statusTick(101));
  assert(c.statusTick(120));
  p=c.render(450);
  assert(p[6]==20 && p[3]==10 && p[0]==5); // head and fading tail
  assert(p[15]==20 && p[12]==10); // shorter output finishes at same time
  assert(c.statusTick(800));
  black(c.render(800),6);
  assert(c.announceConnected(900,true));
  p=c.render(900);
  assert(p[0]==0 && p[1]==20 && p[2]==3);
  black(c.render(1600),6);

  assert(c.announceBoot(2000,true));
  assert(c.announceConnected(2100,true));
  assert(!c.announceConnected(2200,true)); // at most one queued green pass
  assert(c.render(2699)[9]==20);
  p=c.render(2700);
  assert(p[0]==0 && p[1]==20);
  black(c.render(3400),6);
  black(c.render(5000),6);
  assert(c.announceBoot(6000,true));
  assert(c.announceConnected(6100,true));
  c.off();
  black(c.render(6200),6);
  black(c.render(6800),6); // Off cancels queued green too
  assert(c.announceConnected(7000,true));
  c.off();
  black(c.render(7100),6);

  c.on=true;c.brightness=9;
  assert(c.announceConnected(8000,true));
  assert(c.frame("////////////////////////",6,Transport::USB,8100));
  assert(c.render(8200)[4]==20); // moving head; frames accepted during cue
  p=c.render(8700);
  for(size_t i=0;i<18;++i) assert(p[i]==9); // latest frame survives cue
  assert(!c.announceConnected(8800,true)); // don't overlay another live owner
  assert(c.lastFrame==8100 && c.owner==Transport::USB);
  c.off();
  assert(c.announceBoot(9000,true));
  assert(c.announceConnected(9010,true));
  c.on=true;
  assert(c.frame("////////////////////////",6,Transport::USB,9100));
  assert(!c.tick(10299));
  assert(c.tick(10300));
  black(c.render(10300),6); // watchdog wins over the pending/active cue
  black(c.render(10400),6);

  Core wrap;
  assert(wrap.configure(outputs,2,500));
  assert(wrap.announceBoot(UINT32_MAX-300,true));
  assert(wrap.render(49)[6]==20);
  black(wrap.render(399),6);

  Output many[]={{2,1,"GRB"},{4,1,"GRB"},{5,1,"GRB"},{13,1,"GRB"},
                 {14,1,"GRB"},{15,1,"GRB"},{16,1,"GRB"},{17,1,"GRB"}};
  Core limited;
  assert(limited.configure(many,8,100));
  assert(limited.announceBoot(0,true));
  p=limited.render(0);
  uint32_t total=0;
  for(size_t i=0;i<24;++i) { assert(p[i]<=20);total+=p[i]; }
  assert(total*20<=100*255);

  Session session;
  bool fresh=false;
  assert(session.accept("0123456789abcdef",1,true,true,&fresh) && fresh);
  fresh=true;
  assert(session.accept("0123456789abcdef",2,true,true,&fresh) && !fresh);
  fresh=true;
  assert(!session.accept("0123456789abcdef",2,true,true,&fresh) && !fresh);
  assert(session.accept("1123456789abcdef",1,true,true,&fresh) && fresh);
}

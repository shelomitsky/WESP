#include "receiver_core.h"
#include <cassert>
#include <string>
using namespace wesp;
int main() {
  const char *mac="680947485628";
  const char *token="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
  assert(!authorizeIdentity(Transport::USB,true,mac,nullptr,token,nullptr));
  assert(authorizeIdentity(Transport::USB,false,mac,"a0b7652d2050",token,nullptr));
  assert(!authorizeIdentity(Transport::USB,false,mac,mac,token,nullptr));
  assert(authorizeIdentity(Transport::TCP,true,mac,mac,token,nullptr));
  assert(authorizeIdentity(Transport::TCP,true,mac,"a0b7652d2050",token,token));
  assert(authorizeIdentity(Transport::TCP,true,mac,mac,token,"bad"));
  assert(!authorizeIdentity(Transport::TCP,true,mac,mac,token,token));
  Core c;
  assert(c.count == 0 && !c.on);
  Output o{2, 2, "GRB"};
  assert(c.configure(&o, 1, 100));
  c.on = true;
  assert(!c.frame("////", 2, Transport::USB, 1));
  assert(!c.frame("////////", 1, Transport::USB, 1));
  assert(!c.frame("///////!", 2, Transport::USB, 1));
  assert(c.frame("////////", 2, Transport::USB, 1));
  assert(c.render()[0] == 212); // two white pixels share a 100mA budget
  assert(!c.frame("AAAAAAA!",2,Transport::USB,1199));
  assert(c.render()[0] == 212); // malformed tail cannot partially replace RGB
  assert(!c.frame("AAAAAAAA", 2, Transport::TCP, 100));
  assert(!c.tick(1200));
  assert(c.tick(1201));
  assert(c.render()[0] == 0);
  assert(c.frame("////////", 2, Transport::TCP, 1202));
  c.off();
  assert(c.render()[0] == 0 && !c.on);
  assert(c.frame("////////", 2, Transport::TCP, 1503));
  assert(c.render()[0] == 0 && c.owner == Transport::None);
  c.on = true;
  assert(c.render()[0] == 0); // on alone cannot revive a cached frame
  assert(c.frame("////////", 2, Transport::TCP, 1504));
  c.disconnect(Transport::TCP);
  assert(c.render()[0] == 0);
  Output bad{0, 2, "GRB"};
  assert(!c.configure(&bad, 1, 60));
  Output dup[] = {{2, 1, "GRB"}, {2, 1, "RGB"}};
  assert(!c.configure(dup, 2, 60));
  assert(!c.configure(&o,1,99));
  assert(!c.configure(&o,1,5001));
  Output huge{2,1025,"GRB"};
  assert(!c.configure(&huge,1,500));
  Sequence seq;
  assert(!seq.accept(2, false));
  assert(seq.accept(1, true));
  assert(!seq.accept(1, false));
  assert(seq.accept(2, false));
  assert(!seq.accept(1, true));
  assert(!seq.accept(-1,false));
  Session session;
  assert(session.accept("0123456789abcdef",1,true,true));
  assert(session.accept("0123456789abcdef",2,false,true));
  assert(!session.accept("0123456789abcdef",1,true,true));
  assert(session.accept("1123456789abcdef",1,true,true));
  assert(!session.accept("0123456789abcdef",3,false,true));
  assert(c.frame("////////",2,Transport::USB,2000,"0123456789abcdef"));
  c.disconnect(Transport::TCP,"0123456789abcdef");
  c.disconnect(Transport::USB,"1123456789abcdef");
  assert(c.render()[0] == 212);
  Core wrapping;
  assert(wrapping.configure(&o,1,100)); wrapping.on=true;
  assert(wrapping.frame("////////",2,Transport::USB,UINT32_MAX-500));
  assert(!wrapping.tick(698));
  assert(wrapping.tick(699));
  assert(!c.frame("////////",2,Transport::USB,2001,"1123456789abcdef"));
  TcpConnection connection;
  assert(connection.attach());
  assert(!connection.attach()); // no replacement until old generation closes
  assert(connection.session.accept("1123456789abcdef",1,true,false));
  assert(connection.poll(false,c)); // unauthenticated closed socket cannot darken USB
  assert(c.render()[0] == 212);
  assert(connection.attach());
  assert(connection.session.accept("1123456789abcdef",1,true,false));
  connection.authenticated=true;
  assert(c.tick(3500));
  assert(c.frame("////////",2,Transport::TCP,3501,connection.session.value));
  // Arduino's bool operator is false after FIN; explicit presence still closes.
  assert(connection.poll(false,c));
  assert(c.render()[0] == 0 && c.owner==Transport::None);
  assert(connection.attach());
  assert(connection.session.accept("2123456789abcdef",1,true,false));
  connection.authenticated=true;
  assert(c.frame("////////",2,Transport::USB,3502,"3123456789abcdef"));
  assert(connection.poll(false,c));
  assert(c.render()[0] == 212);
  LineReader line;
  assert(line.push('x', 1) == LineEvent::None);
  assert(line.expire(251));
  assert(line.push('\n', 252) == LineEvent::Discarded);
  for (int i = 0; i < 8193; ++i) line.push('x', 300);
  assert(line.push('\n', 301) == LineEvent::Discarded);
  assert(line.push('{', 302) == LineEvent::None);
  assert(line.push('}', 302) == LineEvent::None);
  assert(line.push('\n', 302) == LineEvent::Ready);
  assert(std::string(line.data()) == "{}");
  for (int i=0;i<1000;++i) assert(line.push('x',400+i*10) == LineEvent::None);
  assert(line.push('\n',10400) == LineEvent::Ready);
  for (int i=0;i<8192;++i) line.push('x',10500);
  assert(line.push('\n',10501)==LineEvent::Ready);
  assert(strlen(line.data())==8192);
}

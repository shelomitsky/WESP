#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <esp_system.h>
#include <driver/rmt.h>
#include <cJSON.h>
#include <lwip/sockets.h>
#include <math.h>
#include "receiver_core.h"
#include "effects_protocol.h"
#include "ota_receiver.h"
#include "realtime_receiver.h"

using namespace wesp;
namespace {
Core core;
OtaReceiver ota;
RealtimeReceiver realtime;
EffectsConfig savedEffects{};
bool haveEffects=false;
Preferences preferences;
WiFiServer server(19447);
WiFiClient client;
Session usbSession;
TcpConnection tcp;
LineReader usbLine, tcpLine;
char mac[13]{};
char token[65]{};
char hostname[12]{}, wifiHost[18]{};
bool nvsReady=false, wifiStarted=false;
bool outputsReady=false;
bool mdnsStarted=false, mdnsAttempted=false;
uint32_t mdnsAttemptAt=0;
uint32_t tcpAcceptedAt=0;
uint8_t color[3]={255,255,255};
size_t installedOutputs=0;
rmt_item32_t *rmtItems=nullptr;
bool queueUsbReply(const char *reply);
bool peerAlive() {
  if (!tcp.present || client.fd()<0) return false;
  uint8_t byte;
  int n=::recv(client.fd(),&byte,1,MSG_PEEK|MSG_DONTWAIT);
  return n>0 || (n<0 && (errno==EWOULDBLOCK || errno==EAGAIN || errno==EINTR));
}
struct Config {
  uint32_t magic;
  uint32_t maxMilliamps;
  uint8_t outputCount;
  Output outputs[8];
  char ssid[33];
  char password[64];
  uint8_t secret[32];
};
Config config{};
constexpr uint32_t ConfigMagic=0x57535001;

void paint() {
  if (!rmtItems) return;
  const uint8_t *rgb=core.render(millis());
  size_t start=0;
  for (size_t i=0; i<installedOutputs; ++i) {
    const Output &out=core.outputs[i];
    size_t item=0;
    for (size_t p=0;p<out.count;++p) for (size_t channel=0;channel<3;++channel) {
      char order=out.order[channel];
      uint8_t value=rgb[(start+p)*3+(order=='R'?0:order=='G'?1:2)];
      for (int bit=7;bit>=0;--bit) {
        bool high=value & (1<<bit);
        rmtItems[item].level0=1; rmtItems[item].duration0=high?32:16;
        rmtItems[item].level1=0; rmtItems[item].duration1=high?18:34;
        ++item;
      }
    }
    rmt_write_items(static_cast<rmt_channel_t>(i),rmtItems,item,true);
    start+=out.count;
  }
  delayMicroseconds(80);
  realtime.painted(millis());
}
void darkness() { core.dark(); paint(); }
bool installOutputs() {
  outputsReady=false;
  if (!rmtItems) return false;
  for (size_t i=0;i<installedOutputs;++i) {
    rmt_driver_uninstall(static_cast<rmt_channel_t>(i));
  }
  installedOutputs=0;
  for (size_t i=0;i<core.outputCount;++i) {
    rmt_config_t rmt{};
    rmt.rmt_mode=RMT_MODE_TX;
    rmt.channel=static_cast<rmt_channel_t>(i);
    rmt.gpio_num=static_cast<gpio_num_t>(core.outputs[i].gpio);
    rmt.mem_block_num=1;
    rmt.clk_div=2; // 40MHz, WS281x 800kHz
    rmt.tx_config.loop_en=false;
    rmt.tx_config.carrier_en=false;
    rmt.tx_config.idle_output_en=true;
    rmt.tx_config.idle_level=RMT_IDLE_LEVEL_LOW;
    if (rmt_config(&rmt)!=ESP_OK || rmt_driver_install(rmt.channel,0,0)!=ESP_OK) {
      core.off(); paint();
      return false;
    }
    ++installedOutputs;
  }
  paint();
  outputsReady=true;
  return true;
}
bool persist(const Config &next) {
  return nvsReady && preferences.putBytes("config",&next,sizeof(next))==sizeof(next);
}
void hexToken() {
  for (size_t i=0;i<32;++i) snprintf(token+i*2,3,"%02x",config.secret[i]);
}
const cJSON *field(const cJSON *object,const char *key) { return cJSON_GetObjectItemCaseSensitive(object,key); }
const char *stringField(const cJSON *object,const char *key) {
  const cJSON *v=field(object,key);
  return cJSON_IsString(v)?v->valuestring:nullptr;
}
bool integer(const cJSON *v,int min,int max,int &out) {
  if (!cJSON_IsNumber(v) || !isfinite(v->valuedouble) || floor(v->valuedouble)!=v->valuedouble || v->valuedouble<min || v->valuedouble>max) return false;
  out=static_cast<int>(v->valuedouble); return true;
}
// Bound parser recursion before cJSON allocation; reject duplicate object keys.
bool shallowJson(const char *s) {
  int depth=0; bool quoted=false,escaped=false;
  for (;*s;++s) {
    if (quoted) { if (escaped) escaped=false; else if (*s=='\\') escaped=true; else if (*s=='"') quoted=false; }
    else if (*s=='"') quoted=true;
    else if (*s=='{' || *s=='[') { if (++depth>8) return false; }
    else if (*s=='}' || *s==']') { if (--depth<0) return false; }
  }
  return !quoted && depth==0;
}
bool uniqueKeys(const cJSON *node) {
  for (const cJSON *a=node->child;a;a=a->next) {
    if (cJSON_IsObject(node)) for (const cJSON *b=a->next;b;b=b->next) if (a->string && b->string && !strcmp(a->string,b->string)) return false;
    if ((cJSON_IsObject(a)||cJSON_IsArray(a)) && !uniqueKeys(a)) return false;
  }
  return true;
}
void addStatus(cJSON *reply,bool detailed) {
  cJSON_AddNumberToObject(reply,"count",core.count);
  cJSON_AddBoolToObject(reply,"on",core.on);
  cJSON_AddNumberToObject(reply,"bri",core.brightness);
  if (!detailed) return;
  cJSON_AddStringToObject(reply,"firmware","WESP");
  cJSON_AddStringToObject(reply,"version","0.2.1");
  cJSON *capabilities=cJSON_AddObjectToObject(reply,"capabilities");
  cJSON_AddBoolToObject(capabilities,"wifi_configure",true);
  cJSON_AddBoolToObject(capabilities,"native_effects",true);
  cJSON_AddBoolToObject(capabilities,"realtime_audio",true);
  realtime.stats(reply);
  cJSON_AddBoolToObject(capabilities,"ota",true);
  cJSON_AddBoolToObject(capabilities,"preview",true);
  cJSON_AddNumberToObject(capabilities,"max_presets",MaxFxPresets);
  cJSON_AddBoolToObject(reply,"ota_trial",ota.trial);
  const esp_partition_t *running=esp_ota_get_running_partition();
  if (running) cJSON_AddStringToObject(reply,"boot_slot",running->label);
  esp_app_desc_t description{};
  if (running && esp_ota_get_partition_description(running,&description)==ESP_OK) {
    char build[65]{};for (size_t i=0;i<32;++i) snprintf(build+i*2,3,"%02x",description.app_elf_sha256[i]);
    cJSON_AddStringToObject(reply,"build_sha256",build);
  }
  if (haveEffects && validEffects(savedEffects,core.count)) cJSON_AddItemToObject(reply,"effects",effectsJson(savedEffects));
  cJSON_AddNumberToObject(reply,"max_milliamps",core.maxMilliamps);
  cJSON_AddNumberToObject(reply,"watchdog_ms",PublishedWatchdogMs);
  cJSON_AddItemToObject(reply,"color",fxJsonRgb(color));
  cJSON *outputs=cJSON_AddArrayToObject(reply,"outputs");
  for (size_t i=0;i<core.outputCount;++i) {
    cJSON *output=cJSON_CreateObject();
    cJSON_AddNumberToObject(output,"gpio",core.outputs[i].gpio);
    cJSON_AddNumberToObject(output,"count",core.outputs[i].count);
    cJSON_AddStringToObject(output,"order",core.outputs[i].order);
    cJSON_AddItemToArray(outputs,output);
  }
  cJSON *wifi=cJSON_AddObjectToObject(reply,"wifi");
  cJSON_AddBoolToObject(wifi,"configured",config.ssid[0]!=0);
  bool connected=WiFi.status()==WL_CONNECTED;
  cJSON_AddBoolToObject(wifi,"connected",connected);
  cJSON_AddStringToObject(wifi,"ip",connected?WiFi.localIP().toString().c_str():"");
  cJSON_AddStringToObject(wifi,"host",wifiHost);
}
void sendReply(Transport transport,int id,const char *error=nullptr,bool detailed=false,bool pair=false,bool preview=false,bool grant=false,bool clock=false) {
  cJSON *reply=cJSON_CreateObject();
  if (!reply) return;
  cJSON_AddBoolToObject(reply,"ok",error==nullptr);
  cJSON_AddNumberToObject(reply,"id",id);
  cJSON_AddStringToObject(reply,"mac",mac);
  cJSON_AddNumberToObject(reply,"proto",1);
  if (error) cJSON_AddStringToObject(reply,"error",error);
  else {
    addStatus(reply,detailed);
    if (grant) realtime.grant(reply);
    if (clock) cJSON_AddNumberToObject(reply,"audio_clock_ms",millis());
    if (pair) cJSON_AddStringToObject(reply,"token",token);
    if (preview && core.count) {
      char *pixels=static_cast<char *>(malloc(core.count*4+1));size_t length=0;
      if (pixels && !mbedtls_base64_encode(reinterpret_cast<unsigned char *>(pixels),core.count*4+1,&length,core.render(millis()),core.count*3))
        cJSON_AddStringToObject(reply,"pixels",pixels);
      free(pixels);
    }
  }
  char *serialized=cJSON_PrintUnformatted(reply);
  if (serialized) {
    size_t length=strlen(serialized);
    if (transport==Transport::USB) {
      // Never wait for a host which stopped reading. It can retry with a new id.
      if (Serial.availableForWrite()>=int(length+1)) { Serial.write(reinterpret_cast<uint8_t *>(serialized),length); Serial.write('\n'); }
      else {
        // HardwareSerial queues UART bytes; one status reply is bounded to <1KiB.
        // Drain in loop(), so an unread serial endpoint cannot stall watchdog.
        queueUsbReply(serialized);
      }
    } else if (tcp.present) {
      // WiFiClient::write can retry for seconds, and its inherited
      // availableForWrite() returns zero. One nonblocking socket send is bounded.
      char *packet=length+1<MaxLine?static_cast<char *>(malloc(length+1)):nullptr;
      if (packet) { memcpy(packet,serialized,length);packet[length]='\n'; }
      int sent=packet?::send(client.fd(),packet,length+1,MSG_DONTWAIT):-1;
      free(packet);
      if (sent!=int(length+1)) { client.stop(); core.disconnect(Transport::TCP,tcp.session.value); paint(); }
    }
    cJSON_free(serialized);
  }
  cJSON_Delete(reply);
}
char usbPending[MaxLine+1]{};
size_t usbPendingLength=0, usbPendingOffset=0;
bool queueUsbReply(const char *reply) {
  size_t length=strlen(reply);
  if (usbPendingLength || length+1>=sizeof(usbPending)) return false;
  memcpy(usbPending,reply,length); usbPending[length]='\n';
  usbPendingLength=length+1; usbPendingOffset=0; return true;
}
void flushUsb() {
  if (!usbPendingLength) return;
  size_t capacity=Serial.availableForWrite();
  size_t left=usbPendingLength-usbPendingOffset;
  size_t amount=capacity<left?capacity:left;
  if (amount) usbPendingOffset+=Serial.write(reinterpret_cast<uint8_t *>(usbPending)+usbPendingOffset,amount);
  if (usbPendingOffset==usbPendingLength) usbPendingLength=usbPendingOffset=0;
}
void joinWifi() {
  if (mdnsStarted) { MDNS.end(); mdnsStarted=false; }
  mdnsAttempted=false;
  if (!config.ssid[0]) { WiFi.disconnect(); wifiStarted=false; return; }
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(hostname);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);
  WiFi.begin(config.ssid,config.password);
  wifiStarted=true;
}
const char *configure(const cJSON *request) {
  Config next=config;
  const cJSON *outputs=field(request,"outputs");
  int n=cJSON_GetArraySize(outputs);
  if (!cJSON_IsArray(outputs) || n<1 || n>8) return "invalid_outputs";
  memset(next.outputs,0,sizeof(next.outputs));
  for (int i=0;i<n;++i) {
    const cJSON *entry=cJSON_GetArrayItem(outputs,i);
    int gpio=0,count=0; const char *order=stringField(entry,"order");
    if (!cJSON_IsObject(entry) || !integer(field(entry,"gpio"),0,39,gpio) || !integer(field(entry,"count"),1,1024,count) || !order || strlen(order)!=3) return "invalid_outputs";
    next.outputs[i].gpio=gpio; next.outputs[i].count=count;
    memcpy(next.outputs[i].order,order,4);
  }
  int ma=0;
  if (!integer(field(request,"max_milliamps"),100,5000,ma) || !validOutputs(next.outputs,n,ma)) return "invalid_outputs";
  next.outputCount=n; next.maxMilliamps=ma;
  const cJSON *wifi=field(request,"wifi");
  if (wifi) {
    const char *ssid=stringField(wifi,"ssid"), *password=stringField(wifi,"password");
    if (!cJSON_IsObject(wifi) || !ssid || !password || !strlen(ssid) || strlen(ssid)>32 || (strlen(password)!=0 && (strlen(password)<8 || strlen(password)>63))) return "invalid_wifi";
    memset(next.ssid,0,sizeof(next.ssid)); memset(next.password,0,sizeof(next.password));
    memcpy(next.ssid,ssid,strlen(ssid)); memcpy(next.password,password,strlen(password));
  }
  // Validate before darkening. Initialize outputs before committing the NVS
  // blob, so a rejected hardware configuration is not installed on next boot.
  realtime.revoke();
  core.off(); paint();
  core.configure(next.outputs,next.outputCount,next.maxMilliamps);
  bool installed=installOutputs();
  if (!installed || !persist(next)) {
    core.off(); paint();
    if (config.outputCount) core.configure(config.outputs,config.outputCount,config.maxMilliamps);
    else { core.outputCount=0; core.count=0; core.maxMilliamps=config.maxMilliamps; }
    installOutputs(); // Restore the previous configuration, remaining dark.
    return installed?"storage_error":"output_error";
  }
  config=next;
  if (wifi) joinWifi();
  return nullptr;
}
void process(const char *line,Transport transport) {
  if (!shallowJson(line)) { sendReply(transport,0,"invalid_json"); return; }
  cJSON *request=cJSON_ParseWithOpts(line,nullptr,true);
  if (!request || !cJSON_IsObject(request) || !uniqueKeys(request)) { cJSON_Delete(request); sendReply(transport,0,"invalid_json"); return; }
  int id=0;
  const char *error=nullptr;
  const char *op=stringField(request,"op");
  bool hello=op && !strcmp(op,"hello");
  bool freshSession=false;
  Session &session=transport==Transport::USB?usbSession:tcp.session;
  const char *requestedSession=stringField(request,"session");
  const char *requestedMac=stringField(request,"mac");
  if (!integer(field(request,"id"),1,INT32_MAX,id) || !op) error="invalid_request";
  else if ((error=authorizeIdentity(transport,hello,mac,requestedMac,token,stringField(request,"token")))) { /* No session mutation on failed authentication. */ }
  else if (!session.accept(requestedSession,id,hello,transport==Transport::USB,&freshSession)) error="invalid_session_or_id";
  else {
    if (transport==Transport::TCP) tcp.authenticated=true;
    if (hello) {
      // Only the first authenticated hello, never polls or failed handshakes.
      // The bounded status cue does not grant or refresh a frame lease.
      if (freshSession) core.announceConnected(millis(),outputsReady);
    }
    else if (!strncmp(op,"ota_",4)) {
      if (!strcmp(op,"ota_begin")) { realtime.revoke();core.off();paint(); }
      if (!strcmp(op,"ota_confirm") && (!nvsReady || !outputsReady)) error="ota_self_test_failed";
      else error=ota.process(op,request,transport,requestedSession,core);
    }
    else if (ota.active() && strcmp(op,"state")) error="ota_busy";
    else if (!strcmp(op,"preview")) { /* A read never renews the lease. */ }
    else if (!strcmp(op,"audio_open")) {
      if (transport!=Transport::TCP || !realtime.open(core,requestedSession,stringField(request,"revision"),client.remoteIP())) error="audio_unavailable";
    }
    else if (!strcmp(op,"audio_clock")) {
      if (transport!=Transport::TCP) error="tcp_only";
    }
    else if (!strcmp(op,"effects_configure")) {
      EffectsConfig next{};
      if (!parseEffects(field(request,"effects"),next,core.count)) error="invalid_effects";
      else if (ota.trial) error="confirm_ota_before_configure";
      else {
        bool changed=!haveEffects || memcmp(&savedEffects,&next,sizeof(next));
        if (changed && (!nvsReady || preferences.putBytes("effects",&next,sizeof(next))!=sizeof(next))) error="storage_error";
        else {
          if (changed) realtime.revoke();
          if (changed || !core.effectRevision(next.revision)) core.configureEffects(next);
          savedEffects=next;haveEffects=true;
        }
      }
    }
    else if (!strcmp(op,"audio")) {
      const cJSON *rms=field(request,"rms"),*bass=field(request,"bass");
      if (!cJSON_IsNumber(rms) || !cJSON_IsNumber(bass) || !core.audio(rms->valuedouble,bass->valuedouble,transport,millis(),requestedSession,stringField(request,"revision"))) error="invalid_audio_or_busy";
      else realtime.revoke();
    }
    else if (!strcmp(op,"effect")) {
      const char *mode=stringField(request,"mode");uint8_t rgb[3]{};
      if (!mode || (strcmp(mode,"solid") && strcmp(mode,"runner")) || !fxRgb(field(request,"color"),rgb) ||
          !core.startEffect(!strcmp(mode,"solid")?FxMode::Solid:FxMode::Runner,rgb,transport,millis(),requestedSession,stringField(request,"revision"))) error="invalid_effect_or_busy";
      else { realtime.revoke();memcpy(color,rgb,3); }
    }
    else if (!strcmp(op,"heartbeat")) {
      if (!core.keepalive(transport,millis(),requestedSession,stringField(request,"revision"))) error="invalid_heartbeat";
    }
    else if (!strcmp(op,"event")) {
      const char *kind=stringField(request,"kind");const char *const kinds[]={"notification","volume","clear","clear_volume"};int k=fxChoice(kind,kinds,4);
      const cJSON *value=field(request,"value");float amount=cJSON_IsNumber(value)?value->valuedouble:0;
      if (k<0 || (value && !cJSON_IsNumber(value)) || !core.event(static_cast<FxEvent>(k),stringField(request,"ref"),amount,transport,millis(),requestedSession,stringField(request,"revision"))) error="invalid_event";
    }
    else if (!strcmp(op,"palette")) {
      const cJSON *colors=field(request,"colors");uint8_t next[10][3]{};bool valid=cJSON_IsArray(colors) && cJSON_GetArraySize(colors)==10;
      for (int i=0;valid && i<10;++i) valid=fxRgb(cJSON_GetArrayItem(colors,i),next[i]);
      if (!valid || !(realtime.palette(core,requestedSession,stringField(request,"revision"),next) ||
          core.setPalette(next,transport,requestedSession,stringField(request,"revision")))) error="invalid_palette";
    }
    else if (!strcmp(op,"pair")) {
      if (transport!=Transport::USB) error="usb_only";
      else if (!nvsReady) error="storage_error";
    } else if (!strcmp(op,"configure")) {
      error=authorizeConfiguration(transport,field(request,"wifi")!=nullptr);
      if (!error) error=configure(request);
    } else if (!strcmp(op,"state")) {
      const cJSON *on=field(request,"on"), *bri=field(request,"bri"), *rgb=field(request,"color");
      int brightness=core.brightness, components[3]={color[0],color[1],color[2]};
      if ((on && !cJSON_IsBool(on)) || (bri && !integer(bri,0,255,brightness)) || (ota.active() && on && cJSON_IsTrue(on))) error="invalid_state";
      if (rgb) {
        if (!cJSON_IsArray(rgb) || cJSON_GetArraySize(rgb)!=3) error="invalid_state";
        else for (size_t i=0;i<3;++i) if (!integer(cJSON_GetArrayItem(rgb,i),0,255,components[i])) error="invalid_state";
      }
      if (!error) {
        if (on) { if (cJSON_IsTrue(on)) core.on=true; else { realtime.revoke();core.off(); } }
        core.brightness=brightness;
        for (size_t i=0;i<3;++i) color[i]=components[i];
        core.tick(millis()); paint();
      }
    } else if (!strcmp(op,"frame")) {
      int count=0; const char *pixels=stringField(request,"pixels");
      if (!integer(field(request,"count"),1,MaxPixels,count) || !pixels || !core.frame(pixels,count,transport,millis(),session.value)) error="invalid_frame_or_busy";
      else { realtime.revoke();paint(); }
    } else error="unsupported_op";
  }
  sendReply(transport,id,error,hello || (op && (!strcmp(op,"configure") || !strcmp(op,"effects_configure"))),op && !strcmp(op,"pair") && !error,op && !strcmp(op,"preview"),op && !strcmp(op,"audio_open") && !error,op && !strcmp(op,"audio_clock") && !error);
  cJSON_Delete(request);
}
void input(Stream &stream,LineReader &reader,Transport transport) {
  // Fair scheduling: at most 512 bytes per loop; watchdog runs between chunks.
  for (size_t n=0;n<512 && stream.available();++n) {
    LineEvent event=reader.push(char(stream.read()),millis());
    if (event==LineEvent::Ready) process(reader.data(),transport);
    else if (event==LineEvent::Discarded) sendReply(transport,0,"invalid_line");
  }
  reader.expire(millis());
}
}
extern "C" bool verifyRollbackLater(void) { return true; }
void setup() {
  Serial.setRxBufferSize(16384);
  Serial.begin(921600);
  rmtItems=static_cast<rmt_item32_t *>(malloc(sizeof(rmt_item32_t)*MaxPixels*24));
  WiFi.mode(WIFI_STA);
  uint8_t bytes[6]; WiFi.macAddress(bytes);
  for (size_t i=0;i<6;++i) snprintf(mac+i*2,3,"%02x",bytes[i]);
  snprintf(hostname,sizeof(hostname),"wesp-%s",mac+6);
  snprintf(wifiHost,sizeof(wifiHost),"%s.local",hostname);
  nvsReady=preferences.begin("wesp",false);
  bool loaded=nvsReady && preferences.getBytesLength("config")==sizeof(config) && preferences.getBytes("config",&config,sizeof(config))==sizeof(config);
  loaded=loaded && config.magic==ConfigMagic && config.ssid[32]==0 && config.password[63]==0 && (config.outputCount==0 || validOutputs(config.outputs,config.outputCount,config.maxMilliamps));
  if (!loaded) {
    memset(&config,0,sizeof(config)); config.magic=ConfigMagic; config.maxMilliamps=500;
    esp_fill_random(config.secret,sizeof(config.secret));
    nvsReady=persist(config);
  }
  hexToken();
  if (config.outputCount) { core.configure(config.outputs,config.outputCount,config.maxMilliamps); installOutputs(); }
  if (nvsReady && preferences.getBytesLength("effects")==sizeof(savedEffects) && preferences.getBytes("effects",&savedEffects,sizeof(savedEffects))==sizeof(savedEffects) && validEffects(savedEffects,core.count)) {
    haveEffects=true;core.configureEffects(savedEffects);
  }
  ota.boot();
  core.off(); core.announceBoot(millis(),outputsReady); paint();
  joinWifi();
  server.begin(); server.setNoDelay(true);
}
void loop() {
  ota.tick();
  if (core.tick(millis())) paint();
  flushUsb();
  input(Serial,usbLine,Transport::USB);
  if (tcp.poll(peerAlive(),core)) {
    paint(); client.stop(); tcpLine.reset();
  }
  if (server.hasClient()) {
    WiFiClient next=server.available();
    if (!tcp.attach()) next.stop();
    else { client=next; client.setNoDelay(true); client.setTimeout(0); tcpLine.reset(); tcpAcceptedAt=millis(); }
  }
  if (tcp.present) input(client,tcpLine,Transport::TCP);
  if (wifiStarted && WiFi.status()==WL_CONNECTED) realtime.start();
  realtime.poll(core,tcp.present && tcp.authenticated,tcp.session.value,client.remoteIP(),ota.active());
  if (tcp.present && !tcp.authenticated && uint32_t(millis()-tcpAcceptedAt)>=2000) client.stop();
  if (wifiStarted && WiFi.status()!=WL_CONNECTED && core.owner==Transport::TCP) { core.disconnect(Transport::TCP,tcp.session.value);paint(); }
  if (core.tick(millis())) paint();
  if (wifiStarted && WiFi.status()==WL_CONNECTED && !mdnsStarted && (!mdnsAttempted || uint32_t(millis()-mdnsAttemptAt)>=5000)) {
    mdnsAttemptAt=millis(); mdnsAttempted=true;
    // Register once after join; never wait for Wi-Fi or for a DNS client.
    mdnsStarted=MDNS.begin(hostname);
    if (mdnsStarted) MDNS.addService("wesp","tcp",19447);
  } else if (mdnsStarted && WiFi.status()!=WL_CONNECTED) {
    MDNS.end(); mdnsStarted=false; mdnsAttempted=false;
  }
  if (core.tick(millis())) paint();
  if (core.statusTick(millis())) paint();
  delay(1);
}

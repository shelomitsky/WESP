#pragma once
#include <WiFiUdp.h>
#include <esp_system.h>
#include <mbedtls/md.h>
#include <cJSON.h>
#include "receiver_core.h"
#include "realtime_audio.h"

namespace wesp {
class RealtimeReceiver {
  WiFiUDP udp;
  bool started=false,authReady=false,pendingPaint=false;
  uint8_t key[32]{},sid[8]{};
  char session[17]{},revision[17]{};
  IPAddress peer;
  mbedtls_md_context_t auth;
  uint32_t appliedAt=0,sampleStamp=0;
public:
  FastAudioPolicy policy;
  uint32_t received=0,paintDelayMax=0,authUsMax=0;
  int32_t renderAge=0;
  RealtimeReceiver() { mbedtls_md_init(&auth); }
  void start() { if (!started) started=udp.begin(19448); }
  void revoke() {
    policy.revoke();pendingPaint=false;
    memset(key,0,sizeof(key));memset(sid,0,sizeof(sid));session[0]=revision[0]=0;
    if (authReady) { mbedtls_md_free(&auth);mbedtls_md_init(&auth);authReady=false; }
  }
  bool open(Core &core,const char *owner,const char *rev,IPAddress address) {
    if (!started || !core.on || !validSession(owner) || !core.effectRevision(rev)) return false;
    revoke();esp_fill_random(key,sizeof(key));esp_fill_random(sid,sizeof(sid));
    const mbedtls_md_info_t *md=mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (!md || mbedtls_md_setup(&auth,md,1)) return false;
    authReady=true;
    if (mbedtls_md_hmac_starts(&auth,key,sizeof(key))) { revoke();return false; }
    memcpy(session,owner,17);memcpy(revision,rev,17);peer=address;policy.open(sid);return true;
  }
  void grant(cJSON *reply) const {
    if (!policy.active) return;
    char id[17]{},secret[65]{};
    for (size_t i=0;i<8;++i) snprintf(id+i*2,3,"%02x",sid[i]);
    for (size_t i=0;i<32;++i) snprintf(secret+i*2,3,"%02x",key[i]);
    cJSON *value=cJSON_AddObjectToObject(reply,"audio_stream");
    cJSON_AddStringToObject(value,"id",id);cJSON_AddStringToObject(value,"key",secret);
    cJSON_AddNumberToObject(value,"port",19448);cJSON_AddNumberToObject(value,"clock_ms",millis());
  }
  void stats(cJSON *reply) const {
    cJSON *value=cJSON_AddObjectToObject(reply,"audio_stats");
    cJSON_AddNumberToObject(value,"received",received);cJSON_AddNumberToObject(value,"accepted",policy.accepted);
    cJSON_AddNumberToObject(value,"rejected",policy.rejected);cJSON_AddNumberToObject(value,"stale",policy.stale);
    cJSON_AddNumberToObject(value,"reordered",policy.reordered);cJSON_AddNumberToObject(value,"age_ms",policy.lastAge);
    cJSON_AddNumberToObject(value,"paint_delay_max_ms",paintDelayMax);cJSON_AddNumberToObject(value,"render_age_ms",renderAge);
    cJSON_AddNumberToObject(value,"auth_us_max",authUsMax);
  }
  void painted(uint32_t now) {
    if (!pendingPaint) return;
    uint32_t delay=now-appliedAt;if (delay>paintDelayMax) paintDelayMax=delay;
    renderAge=int32_t(now-sampleStamp);pendingPaint=false;
  }
  void poll(Core &core,bool authenticated,const char *owner,IPAddress address,bool updating) {
    if (policy.active && (!authenticated || updating || !core.on || strcmp(owner,session) ||
        address!=peer || !core.effectRevision(revision))) revoke();
    AudioSample newest{};bool have=false;
    for (size_t i=0;i<8;++i) {
      int length=udp.parsePacket();if (length<=0) break;
      ++received;uint8_t packet[AudioPacketSize]{};
      if (length!=int(AudioPacketSize) || udp.remoteIP()!=peer || !policy.active) {
        udp.flush();++policy.rejected;continue;
      }
      if (udp.read(packet,sizeof(packet))!=int(sizeof(packet))) { ++policy.rejected;continue; }
      bool verified=false;
      if (authReady && policy.matches(packet,sizeof(packet))) {
        uint8_t digest[32]{};uint32_t before=micros();
        bool ok=!mbedtls_md_hmac_reset(&auth) && !mbedtls_md_hmac_update(&auth,packet,24) && !mbedtls_md_hmac_finish(&auth,digest);
        uint32_t elapsed=micros()-before;if (elapsed>authUsMax) authUsMax=elapsed;
        uint8_t diff=0;for (size_t n=0;n<16;++n) diff|=digest[n]^packet[24+n];
        verified=ok && !diff;
      }
      AudioSample candidate{};
      if (policy.accept(packet,sizeof(packet),millis(),verified,candidate)) { newest=candidate;have=true; }
    }
    if (have) {
      uint32_t now=millis();
      if (!core.audio(newest.rms/65535.f,newest.bass/65535.f,Transport::TCP,now,session,revision)) { revoke();return; }
      appliedAt=now;sampleStamp=newest.stamp;pendingPaint=true;
    }
  }
};
}

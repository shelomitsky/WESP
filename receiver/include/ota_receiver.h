#pragma once
#include <esp_ota_ops.h>
#include <mbedtls/sha256.h>
#include <mbedtls/base64.h>
#include "ota_policy.h"
#include "effects_protocol.h"
namespace wesp {
class OtaReceiver {
  OtaTransfer transfer;
  esp_ota_handle_t handle=0;
  const esp_partition_t *target=nullptr;
  mbedtls_sha256_context sha{};
  char expected[65]{};
  bool digestReady=false;
public:
  uint32_t rebootAt=0,trialStarted=0;
  bool rebootPending=false,trial=false;
  bool active() const { return transfer.active; }
  uint32_t offset() const { return transfer.written; }
  void abort() {
    if (transfer.active && handle) esp_ota_abort(handle);
    if (digestReady) mbedtls_sha256_free(&sha);
    handle=0;digestReady=false;transfer.abort();
  }
  void boot() {
    esp_ota_img_states_t state;
    trial=esp_ota_get_state_partition(esp_ota_get_running_partition(),&state)==ESP_OK && state==ESP_OTA_IMG_PENDING_VERIFY;
    trialStarted=millis();
  }
  const char *process(const char *op,const cJSON *request,Transport transport,const char *session,Core &core) {
    if (!strcmp(op,"ota_confirm")) {
      if (trial) {
        if (esp_ota_mark_app_valid_cancel_rollback()!=ESP_OK) return "ota_confirm_failed";
        trial=false;
      }
      return nullptr;
    }
    if (!strcmp(op,"ota_begin")) {
      const char *digest=fxString(request,"sha256");int size=0;
      target=esp_ota_get_next_update_partition(nullptr);
      if (trial || !target || transfer.active || !digest || strlen(digest)!=64 || !fxInteger(fxField(request,"size"),256,target->size,size)) return "invalid_ota";
      for (size_t i=0;i<64;++i) if (!((digest[i]>='0'&&digest[i]<='9')||(digest[i]>='a'&&digest[i]<='f'))) return "invalid_ota";
      if (!transfer.begin(size,target->size,transport,session,millis())) return "invalid_ota";
      core.off();
      // No LEDs remain lit while flash erase/write may briefly stall the loop.
      memcpy(expected,digest,65);
      if (esp_ota_begin(target,size,&handle)!=ESP_OK) { abort();return "ota_begin_failed"; }
      mbedtls_sha256_init(&sha);mbedtls_sha256_starts_ret(&sha,0);digestReady=true;
      return nullptr;
    }
    if (!transfer.owned(transport,session)) return "ota_owner_mismatch";
    if (!strcmp(op,"ota_abort")) { abort();return nullptr; }
    if (!strcmp(op,"ota_chunk")) {
      const char *data=fxString(request,"data");int offset=0;uint8_t bytes[1024];size_t length=0;
      if (!data || strlen(data)>1368 || !fxInteger(fxField(request,"offset"),0,target->size,offset) ||
          mbedtls_base64_decode(bytes,sizeof(bytes),&length,reinterpret_cast<const uint8_t *>(data),strlen(data)) ||
          !transfer.chunk(offset,length,transport,session)) return "invalid_ota_chunk";
      if (esp_ota_write(handle,bytes,length)!=ESP_OK) { abort();return "ota_write_failed"; }
      mbedtls_sha256_update_ret(&sha,bytes,length);transfer.commitChunk(length,millis());return nullptr;
    }
    if (!strcmp(op,"ota_finish")) {
      if (!transfer.complete()) return "ota_incomplete";
      uint8_t digest[32];char hex[65]{};mbedtls_sha256_finish_ret(&sha,digest);
      for (size_t i=0;i<32;++i) snprintf(hex+i*2,3,"%02x",digest[i]);
      if (strcmp(expected,hex)) { abort();return "ota_hash_mismatch"; }
      esp_err_t result=esp_ota_end(handle);handle=0;
      if (result!=ESP_OK || esp_ota_set_boot_partition(target)!=ESP_OK) { abort();return "ota_image_invalid"; }
      mbedtls_sha256_free(&sha);digestReady=false;transfer.abort();
      rebootAt=millis();rebootPending=true;return nullptr;
    }
    return "unsupported_ota";
  }
  void tick() {
    if (transfer.expired(millis())) abort();
    if (rebootPending && uint32_t(millis()-rebootAt)>=500) esp_restart();
    if (trial && uint32_t(millis()-trialStarted)>=60000) {
      // An unconfirmed image returns to the previous slot on the next boot.
      esp_ota_mark_app_invalid_rollback_and_reboot();
      esp_restart();
    }
  }
};
}

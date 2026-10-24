#pragma once
#include <cJSON.h>
#include "effects_engine.h"
namespace wesp {
inline const cJSON *fxField(const cJSON *o,const char *key) { return cJSON_GetObjectItemCaseSensitive(o,key); }
inline const char *fxString(const cJSON *o,const char *key) { const cJSON *v=fxField(o,key);return cJSON_IsString(v)?v->valuestring:nullptr; }
inline bool fxInteger(const cJSON *v,int low,int high,int &out) {
  if (!cJSON_IsNumber(v) || !isfinite(v->valuedouble) || floor(v->valuedouble)!=v->valuedouble || v->valuedouble<low || v->valuedouble>high) return false;
  out=int(v->valuedouble);return true;
}
inline int fxChoice(const char *value,const char *const *choices,size_t count) {
  if (value) for (size_t i=0;i<count;++i) if (!strcmp(value,choices[i])) return i;
  return -1;
}
inline bool fxRgb(const cJSON *value,uint8_t *out) {
  if (!cJSON_IsArray(value) || cJSON_GetArraySize(value)!=3) return false;
  for (size_t i=0;i<3;++i) { int channel=0;if (!fxInteger(cJSON_GetArrayItem(value,i),0,255,channel)) return false;out[i]=channel; }
  return true;
}
inline bool parseEffects(const cJSON *value,EffectsConfig &out,size_t count) {
  if (!cJSON_IsObject(value) || cJSON_GetArraySize(value)!=8) return false;
  EffectsConfig next{};int number=0;
  const char *revision=fxString(value,"revision"),*active=fxString(value,"active");
  if (!fxInteger(fxField(value,"schema"),1,1,number) || !revision || strlen(revision)!=16 || !active) return false;
  memcpy(next.revision,revision,17);
  if (!fxInteger(fxField(value,"wallpaper_timeout_ms"),1500,60000,number)) return false;next.wallpaperTimeout=number;
  if (!fxInteger(fxField(value,"wallpaper_fade_ms"),0,10000,number)) return false;next.wallpaperFade=number;
  const cJSON *sections=fxField(value,"sections");
  int n=cJSON_GetArraySize(sections);
  if (!cJSON_IsArray(sections) || n<1 || n>int(MaxFxSections)) return false;
  next.sectionCount=n;
  for (int i=0;i<n;++i) {
    const cJSON *section=cJSON_GetArrayItem(sections,i);
    if (!cJSON_IsArray(section) || cJSON_GetArraySize(section)!=3 || !cJSON_IsBool(cJSON_GetArrayItem(section,2))) return false;
    if (!fxInteger(cJSON_GetArrayItem(section,0),0,1023,number)) return false;next.sections[i].start=number;
    if (!fxInteger(cJSON_GetArrayItem(section,1),1,1024,number)) return false;next.sections[i].count=number;
    next.sections[i].reverse=cJSON_IsTrue(cJSON_GetArrayItem(section,2));
  }
  const cJSON *presets=fxField(value,"presets");n=cJSON_GetArraySize(presets);
  if (!cJSON_IsArray(presets) || n<1 || n>int(MaxFxPresets)) return false;
  next.presetCount=n;next.active=255;
  const char *const styles[]={"meter","pulse"};
  for (int i=0;i<n;++i) {
    const cJSON *entry=cJSON_GetArrayItem(presets,i);FxPreset &p=next.presets[i];
    const char *id=fxString(entry,"id");
    if (!cJSON_IsObject(entry) || cJSON_GetArraySize(entry)!=8 || !id || !strlen(id) || strlen(id)>16) return false;
    memcpy(p.id,id,strlen(id)+1);if (!strcmp(id,active)) next.active=i;
    int style=fxChoice(fxString(entry,"style"),styles,2);if (style<0) return false;p.style=style;
    if (!fxInteger(fxField(entry,"sensitivity"),50,200,number)) return false;p.sensitivity=number;
    if (!fxInteger(fxField(entry,"gate"),0,30,number)) return false;p.gate=number;
    if (!fxInteger(fxField(entry,"attack_ms"),0,300,number)) return false;p.attackMs=number;
    if (!fxInteger(fxField(entry,"decay_ms"),80,600,number)) return false;p.decayMs=number;
    if (!fxInteger(fxField(entry,"repeat_ms"),0,5000,number)) return false;p.repeatMs=number;
    const cJSON *colors=fxField(entry,"colors");
    if (!cJSON_IsArray(colors) || cJSON_GetArraySize(colors)!=10) return false;
    for (int j=0;j<10;++j) if (!fxRgb(cJSON_GetArrayItem(colors,j),p.colors[j])) return false;
  }
  const cJSON *event=fxField(value,"notification");
  const char *const eventStyles[]={"flash","pulse","tint","pixel"};
  int style=fxChoice(fxString(event,"style"),eventStyles,4);
  if (!cJSON_IsObject(event) || cJSON_GetArraySize(event)!=4 || style<0 || !fxRgb(fxField(event,"color"),next.notifyColor)) return false;
  next.notifyStyle=style;
  if (!fxInteger(fxField(event,"strength"),10,100,number)) return false;next.notifyStrength=number;
  if (!fxInteger(fxField(event,"duration_ms"),100,10000,number)) return false;next.notifyMs=number;
  if (!validEffects(next,count)) return false;
  out=next;return true;
}
inline cJSON *fxJsonRgb(const uint8_t *rgb) {
  cJSON *out=cJSON_CreateArray();for (int i=0;i<3;++i) cJSON_AddItemToArray(out,cJSON_CreateNumber(rgb[i]));return out;
}
inline cJSON *effectsJson(const EffectsConfig &c) {
  cJSON *out=cJSON_CreateObject();if (!out) return nullptr;
  cJSON_AddNumberToObject(out,"schema",1);cJSON_AddStringToObject(out,"revision",c.revision);
  cJSON_AddStringToObject(out,"active",c.presets[c.active].id);
  cJSON_AddNumberToObject(out,"wallpaper_timeout_ms",c.wallpaperTimeout);cJSON_AddNumberToObject(out,"wallpaper_fade_ms",c.wallpaperFade);
  cJSON *sections=cJSON_AddArrayToObject(out,"sections");
  for (size_t i=0;i<c.sectionCount;++i) {
    const FxSection &s=c.sections[i];cJSON *a=cJSON_CreateArray();cJSON_AddItemToArray(a,cJSON_CreateNumber(s.start));
    cJSON_AddItemToArray(a,cJSON_CreateNumber(s.count));cJSON_AddItemToArray(a,cJSON_CreateBool(s.reverse));cJSON_AddItemToArray(sections,a);
  }
  cJSON *presets=cJSON_AddArrayToObject(out,"presets");const char *styles[]={"meter","pulse"};
  for (size_t i=0;i<c.presetCount;++i) {
    const FxPreset &p=c.presets[i];cJSON *a=cJSON_CreateObject();cJSON_AddStringToObject(a,"id",p.id);cJSON_AddStringToObject(a,"style",styles[p.style]);
    cJSON_AddNumberToObject(a,"sensitivity",p.sensitivity);cJSON_AddNumberToObject(a,"gate",p.gate);
    cJSON_AddNumberToObject(a,"attack_ms",p.attackMs);cJSON_AddNumberToObject(a,"decay_ms",p.decayMs);cJSON_AddNumberToObject(a,"repeat_ms",p.repeatMs);
    cJSON *colors=cJSON_AddArrayToObject(a,"colors");for (int j=0;j<10;++j) cJSON_AddItemToArray(colors,fxJsonRgb(p.colors[j]));
    cJSON_AddItemToArray(presets,a);
  }
  cJSON *event=cJSON_AddObjectToObject(out,"notification");const char *eventStyles[]={"flash","pulse","tint","pixel"};
  cJSON_AddStringToObject(event,"style",eventStyles[c.notifyStyle]);cJSON_AddItemToObject(event,"color",fxJsonRgb(c.notifyColor));
  cJSON_AddNumberToObject(event,"strength",c.notifyStrength);cJSON_AddNumberToObject(event,"duration_ms",c.notifyMs);
  return out;
}
}

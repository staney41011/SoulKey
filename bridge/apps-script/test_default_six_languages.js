"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const root=path.resolve(__dirname,"../..");
const read=relative=>fs.readFileSync(path.join(root,relative),"utf8");
const chosen=["en","es","id","km","vi","th"];
const translated=chosen.filter(x=>x!=="en");
const all=["en","es","id","km","vi","th","ja","ko","ta","hi","bn","ne","lo","my","it","pt"];

// The UI order may be returned in an arbitrary order by the central settings sheet.
const app=read("studio/app-20260923-48.js");
const sortSrc=app.slice(app.indexOf("function orderedLanguageSettings_(items){"),
  app.indexOf("\nlet languageSettings",app.indexOf("function orderedLanguageSettings_(items){")));
const ctx={LANGUAGE_DISPLAY_ORDER:all,LANGUAGE_DEFAULT_AUDIO_CODES:chosen,
  languageSettings:all.map(code=>({code,name:code}))};
vm.createContext(ctx);
vm.runInContext(sortSrc,ctx);
const unsorted=["th","hi","en","ko","es","km","vi","id","ja"];
const sorted=vm.runInContext("orderedLanguageSettings_(items)",Object.assign(ctx,{
  items:unsorted.map(code=>({code,name:code}))
}));
assert.deepEqual(Array.from(sorted).map(x=>x.code).slice(0,6),chosen);
const normalizer=app.slice(app.indexOf("function normalizedLanguagePlan(task){"),
  app.indexOf("\nconst LANGUAGE_ZH_NAMES",app.indexOf("function normalizedLanguagePlan(task){")));
vm.runInContext(normalizer,ctx);
const newPlan=Array.from(vm.runInContext("normalizedLanguagePlan({languagePlan:[]})",ctx));
assert.deepEqual(newPlan.filter(x=>x.audio_enabled).map(x=>x.language_code),chosen);
assert.deepEqual(newPlan.filter(x=>x.transcript_enabled&&x.language_code!=="en")
  .map(x=>x.language_code),translated);
ctx.saved=[{language_code:"en",audio_enabled:false,transcript_enabled:true},
  {language_code:"ja",audio_enabled:true,transcript_enabled:true,transcript_source:"ai"}];
const oldPlan=Array.from(vm.runInContext("normalizedLanguagePlan({languagePlan:saved})",ctx));
assert.deepEqual(oldPlan.filter(x=>x.audio_enabled).map(x=>x.language_code),["ja"]);
assert.equal(oldPlan.find(x=>x.language_code==="en").transcript_enabled,true);
console.log("PASS: Studio defaults to exactly six, preserving saved lesson choices");

// Backend must not burn all 15 translation slots when a new lesson has no plan.
const native=read("bridge/apps-script/NativeNext.gs");
const backend={saved:[],readLanguagePlan_:()=>backend.saved};
vm.createContext(backend);
vm.runInContext(native,backend);
const select=kind=>Array.from(vm.runInContext(
  'soulkeyNextSelectedCodes_("P262-L01","'+kind+'")',backend));
assert.deepEqual(select("audio"),chosen);
assert.deepEqual(select("translation"),translated);
backend.saved=[{language_code:"en",audio_enabled:true,audio_source:"tts"},
  {language_code:"ja",transcript_enabled:true,transcript_source:"ai",
   audio_enabled:true,audio_source:"tts"}];
assert.deepEqual(select("audio"),["en","ja"]);
assert.deepEqual(select("translation"),["ja"]);
backend.saved=[{language_code:"en",audio_enabled:false,audio_source:"tts"}];
assert.deepEqual(select("audio"),[]);
assert.deepEqual(select("translation"),[]);
console.log("PASS: native translation and TTS fallback are six / five; manual plans respected");

// The secondary quick-review flow also starts with the same six checked.
const review=read("studio/review.html");
const labels=[...review.matchAll(/<label class="card output-row" data-output-lang="([a-z]{2})">([\s\S]*?)<\/label>/g)];
assert.equal(labels.length,16);
assert.deepEqual(labels.slice(0,6).map(x=>x[1]),chosen);
assert.deepEqual(labels.filter(x=>/data-output-enabled checked/.test(x[2])).map(x=>x[1]),chosen);
const index=read("studio/index.html");
assert.match(index,/app-20260923-48\.js\?v=20261120-native-current-share/);
assert.ok(review.includes("review-editor.js?v=20261115-default-six"));
const bridge=read("bridge/apps-script/Code.gs");
const first=bridge.indexOf("function soulkeyAutoSheetsInitialAudioReconcile_()");
const last=bridge.indexOf("\nfunction ",first+10);
const section=bridge.slice(first,last<0?undefined:last);
assert.ok(section.includes('soulkeyNextSelectedCodes_(task.id,"audio")'));
assert.ok(section.includes('return lang!=="en";'));
assert.ok(section.includes("const missing=langs.filter"));
console.log("PASS: quick-review defaults, cache-bust, and production reconcile selection");

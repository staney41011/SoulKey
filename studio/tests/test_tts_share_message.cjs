"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {LANGUAGES,build,canonicalMp3Code,canonicalDriveUrl}=require("../tts-share-message.js");
const codes=["en","es","th","id","km","vi"];
assert.deepEqual(LANGUAGES.map(x=>x.code),codes,"only six approved public-share languages");
const uid=n=>"1ExampleSoulKeyDriveAudioId_"+n;
const make=(code,n,extra={})=>({
  id:uid(n),name:code+".mp3",canonical_name:code+".mp3",
  url:"https://drive.google.com/file/d/"+uid(n)+"/view",
  size:12000000,...extra
});
const payload=files=>({ok:true,groups:[{key:"audio",files}]});
const task=()=>({
  id:"P257-L01",period:257,lesson:"第1堂",
  title:"心念的力量229 | 中和老師 | 打開心靈的鎖匙257期",
  languagePlan:LANGUAGES.map(l=>({code:l.code,audio_enabled:true,audio_source:"tts"})),
  remoteStages:{tts:{status:"done"}}
});
const files=[make("en",0),make("es",1),make("th",2),make("km",3),make("vi",4)];
const result=build(task(),payload(files));
assert.equal(result.eligible,true);
assert.equal(result.readyCount,5);
assert.equal(result.pendingCount,1);
assert.equal(result.expectedCount,6);
assert.equal(result.allReady,false);
assert.deepEqual(result.languages,codes);
assert.match(result.message,/心念的力量229/);
assert.match(result.message,/中和老師/);
assert.match(result.message,/Bahasa Indonesia/);
assert.match(result.message,/Audio pending verification/);
for(const f of files) assert.ok(result.message.includes(f.id),f.name);
assert.ok(!result.message.includes("தமிழ்"));
assert.ok(!result.message.includes("Português"));
const all=build(task(),payload([...files,make("id",5)]));
assert.equal(all.readyCount,6);
assert.equal(all.pendingCount,0);
assert.equal(all.allReady,true);
const noAudio=build({...task(),remoteStages:{}},payload([]));
assert.equal(noAudio.hasLinks,false);
assert.equal(noAudio.eligible,false);
const badFiles=[
  make("en",20,{canonical_name:"en.preview.mp3",name:"en.preview.mp3"}),
  make("en",21,{canonical_name:"youtube.en.mp3",name:"youtube.en.mp3"}),
  make("en",22,{url:"https://untrusted.example/file/d/"+uid(22)+"/view"}),
  make("en",23,{size:0})
];
for(const file of badFiles){
  assert.equal(build(task(),payload([file])).readyCount,0);
}
const realTitle=make("en",30,{canonical_name:"",
 name:"第257期_第1堂課_心念的力量229_中和老師_英文TTS音檔.mp3"});
assert.equal(canonicalMp3Code(realTitle),"en");
assert.equal(build(task(),payload([realTitle])).readyCount,1);
const stage=task();
stage.remoteStages.tts={status:"error"};
stage.remoteStages["tts:en"]={status:"done"};
stage.remoteStages["tts:id"]={status:"error"};
const partial=build(stage,payload([make("en",31),make("id",32)]));
assert.equal(partial.readyCount,1);
assert.equal(partial.pendingCount,5);
assert.ok(!partial.message.includes(uid(32)));
stage.remoteStages["tts:en"]={status:"running"};
assert.equal(build(stage,payload([make("en",31)])).readyCount,0);
// Lesson 3 Spanish long natural narration is shareable as a clearly
// non-synchronized listening file, never presented as aligned audio.
const spanishPreview=make("es",41,{
  canonical_name:"es.preview.mp3",name:"es.preview.mp3",
  needs_timing_review:true,audio_kind:"standalone_preview"
});
const lesson3=task();
lesson3.id="P257-L03";
lesson3.lesson="第3堂";
lesson3.remoteStages.tts={status:"needs_review"};
lesson3.remoteStages["tts:es"]={status:"needs_review"};
const availablePreview=build(lesson3,payload([spanishPreview]));
assert.equal(availablePreview.readyCount,1);
assert.equal(availablePreview.reviewCount,1);
assert.equal(availablePreview.pendingCount,5);
assert.equal(availablePreview.hasLinks,true);
assert.equal(availablePreview.allReady,false);
assert.ok(availablePreview.message.includes(spanishPreview.id));
assert.match(availablePreview.message,/未對時自然朗讀版/);
assert.match(availablePreview.message,/尚未與原影片同步/);
const fakePreview=make("es",42,{
  canonical_name:"es.preview.mp3",name:"es.preview.mp3",
  needs_timing_review:true
});
assert.equal(build(lesson3,payload([fakePreview])).readyCount,0,
  "previews are allowed only when backend explicitly validates audio kind");
assert.equal(build(lesson3,payload([make("es",43,{
  canonical_name:"es.preview.mp3",name:"es.preview.mp3"
})])).readyCount,0);
assert.equal(build(task(),payload([make("en",0)])).reviewCount,0);
const app=fs.readFileSync(path.join(__dirname,"..","app-20260923-48.js"),"utf8");
assert.ok(app.includes("function requestTtsShareLinks(taskId,force=false)"));
assert.ok(app.includes('action:"tts_share_links"'));
assert.ok(app.includes('action==="tts_share_links"?20000'));
assert.ok(!/if\(!courseFilesCollapsed\(\)\) requestCourseFiles\(task\.id\);/.test(app),
  "Opening lessons must not start large Drive folder scan");
const backend=fs.readFileSync(path.join(__dirname,"..","..","bridge","apps-script","Code.gs"),"utf8");
assert.ok(backend.includes('if (action === "tts_share_links")'));
assert.ok(backend.includes('function ttsShareLinks_(taskId)'));
assert.ok(backend.includes('"tts_share_links"\n  ];') || backend.includes('"tts_share_links"\r\n  ];'),
  "New audio action must be JSONP-whitelisted");
console.log("SOULKEY_SIX_LANGUAGE_SHARE_OK",JSON.stringify({languages:codes,available:result.readyCount,pending:result.pendingCount}));

"use strict";

const assert=require("node:assert/strict");
const {LANGUAGES,build,canonicalMp3Code,canonicalDriveUrl}=require("../tts-share-message.js");
const pathId="1M0SQbkknK8RgpXwnxHun3rxfYdA6HVRE";
const anotherId="1gBOKc6txHWjiK-KDlwo7cMRxDN87lXAH";
const audio=(code,id,{name=code+".mp3",canonical_name=code+".mp3",url, size=102400}={})=>
  ({name,canonical_name,id,url:url||"https://drive.google.com/file/d/"+id+"/view",size});
const data=files=>({groups:[{key:"audio",files}]});
const task=(plan=LANGUAGES.map(l=>l.code))=>({
  id:"P256-L01",period:256,lesson:"第1堂",
  title:"心念的力量228丨中和老師丨打開心靈的鎖匙256期",
  lecturer:"白陽文化",
  languagePlan:plan.map(code=>({code,audio_enabled:true,audio_source:"tts"})),
  remoteStages:{tts:{status:"done"}}
});
const en=audio("en",pathId),th=audio("th",anotherId);
const partial=build(task(["en","th","hi","ta"]),data([en,th]));
assert.equal(partial.eligible,true);
assert.equal(partial.readyCount,2);
assert.equal(partial.pendingCount,2);
assert.equal(partial.allReady,false);
assert.match(partial.message,/🌏 第256期｜第1堂課程音檔\nSession 256 – Lesson 01/);
assert.match(partial.message,/📖 心念的力量228/);
assert.match(partial.message,/🎤 講師：中和老師/);
assert.doesNotMatch(partial.message,/講師：白陽文化/);
assert.match(partial.message,/🇬🇧 English 英文\nhttps:\/\/drive.google.com\/file\/d\/1M0SQbkknK8RgpXwnxHun3rxfYdA6HVRE\/view/);
assert.match(partial.message,/🇹🇭 ภาษาไทย 泰文/);
assert.match(partial.message,/🇮🇳 हिन्दी 印地文\n音檔待確認 \/ Audio pending verification/);
assert.match(partial.message,/🇮🇳 தமிழ் 泰米爾文\n音檔待確認/);
assert.doesNotMatch(partial.message,/\.preview\.mp3/);

const finished=build(task(["en","th"]),data([en,th]));
assert.equal(finished.readyCount,2);
assert.equal(finished.pendingCount,0);
assert.equal(finished.allReady,true);
assert.equal(finished.expectedCount,2);
assert.doesNotMatch(finished.message,/🇮🇳 हिन्दी/);

const allIds=LANGUAGES.map((l,i)=>audio(l.code,"12345678901234"+String(i).padStart(2,"0")));
const all=build(task(),data(allIds));
assert.equal(all.readyCount,16);
assert.equal(all.pendingCount,0);
assert.equal(all.languages.length,16);
assert.match(all.message,/🇧🇷 Português 葡萄牙文/);

const metadataTitle=task(["en"]);
metadataTitle.english_title="The Power of Thoughts";
assert.match(build(metadataTitle,data([en])).message,/The Power of Thoughts/);
assert.doesNotMatch(finished.message,/The Power of Thoughts/);

const wrongUrl=audio("en",pathId,{url:"https://untrusted.example/file/d/"+pathId+"/view"});
const wrongId=audio("en",pathId,{url:"https://drive.google.com/file/d/another1234567890123/view"});
const video=audio("en",pathId,{name:"youtube.en.mp3",canonical_name:"youtube.en.mp3"});
const preview=audio("en",pathId,{name:"en.preview.mp3",canonical_name:"en.preview.mp3"});
for(const bad of [wrongUrl,wrongId,video,preview]){
  assert.equal(canonicalDriveUrl(bad)==="" || canonicalMp3Code(bad)==="",true);
  assert.equal(build(task(["en"]),data([bad])).readyCount,0);
}

const formalAudio=audio("en",pathId,{
  canonical_name:"",
  name:"第257期_第1堂課_心念的力量229_中和老師_英文TTS音檔.mp3"
});
assert.equal(canonicalMp3Code(formalAudio),"en");
assert.equal(build(task(["en"]),data([formalAudio])).readyCount,1,
  "legacy formal official audio filename must be shareable");
for(const suffix of ["英文自然試聽版.mp3","英文YouTube原聲.mp3"]){
  assert.equal(canonicalMp3Code({...formalAudio,name:"第257期_第1堂課_"+suffix}),"",
    "preview / source audio must never be offered as full TTS");
}
const statusTask=task(["en","th"]);
statusTask.remoteStages["tts:en"]={status:"done"};
statusTask.remoteStages["tts:th"]={status:"needs_review"};
const review=build(statusTask,data([en,th]));
assert.equal(review.readyCount,1);
assert.match(review.message,/🇹🇭 ภาษาไทย 泰文\n音檔待驗收 \/ Audio pending review/);
assert.doesNotMatch(review.message,new RegExp(anotherId));
for(const status of ["stale","error","queued","running","delayed"]){
  statusTask.remoteStages["tts:en"]={status};
  assert.equal(build(statusTask,data([en,th])).readyCount,0,
    "cannot share stale/failed/in-progress audio "+status);
}
statusTask.remoteStages["tts:en"]={status:"done"};
statusTask.remoteStages.tts={status:"error"};
assert.equal(build(statusTask,data([en,th])).readyCount,1,
  "partial aggregate failure must preserve independently completed en");
statusTask.remoteStages.tts={status:"stale"};
assert.equal(build(statusTask,data([en,th])).readyCount,1,
  "independently finished language with real Drive MP3 survives aggregate stale");

const notReady=task([]);
notReady.remoteStages={};
assert.equal(build(notReady,data([])).eligible,false);
const noFile=task(["en"]);
assert.equal(build(noFile,data([])).eligible,true);
assert.equal(build(noFile,data([])).hasLinks,false);
assert.equal(build(noFile,data([])).pendingCount,1);

const noPlan=task([]);
noPlan.remoteStages["tts:en"]={status:"done"};
assert.deepEqual(build(noPlan,data([en])).languages,["en"]);
console.log("TTS_SHARE_MESSAGE_TEST_OK",JSON.stringify({partial:partial.readyCount,complete:all.readyCount,pending:review.pendingCount}));

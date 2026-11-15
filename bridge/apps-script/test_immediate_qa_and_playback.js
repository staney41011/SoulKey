"use strict";
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const source=name=>fs.readFileSync(__dirname+"/"+name+".gs","utf8");
function section(code,start,end){
  const a=code.indexOf("function "+start+"("),b=code.indexOf("\nfunction "+end+"(",a);
  assert(a>=0&&b>a,start+" missing");return code.slice(a,b);
}
const next=source("NativeNext");
const quality=source("NativeQuality");
const audio=source("NativeAudio");
// Translation writes full DRAFT, releases the script lock, then starts exactly
// that changed language's Gemma 4 review, without waking old drafts.
let locked=false, qaCalls=[],exportsChanged=true;
const mockTab={
 getLastRow:()=>1,
 getDataRange:()=>({getValues:()=>[]}),
 getRange:()=>({getValues:()=>[]})
};
const tickCtx={
 PropertiesService:{getScriptProperties:()=>({getProperty:()=> "yes"})},
 LockService:{getScriptLock:()=>({
   tryLock:()=>{assert.equal(locked,false);locked=true;return true;},
   releaseLock:()=>{assert.equal(locked,true);locked=false;}
 })},
 soulkeyNextSources_:()=>[{task:"P262-L01",segments:[]}],
 soulkeyNextEnsureRows_:()=>0,
 soulkeyNextQuota_:()=>({used:0,props:{setProperty:()=>{}}}),
 soulkeyNextSelectedCodes_:()=>["es"],
 SK_NEXT_PRIORITY_LANGS:["es"],SK_NEXT_LANGS:["es"],
 SK_NEXT_LIMIT_PER_TICK:85,SK_NEXT_DAILY_LIMIT:4500,SK_NEXT_MAX_MS:190000,
 SpreadsheetApp:{openById:()=>({getSheetByName:()=>mockTab}),flush:()=>{}},
 SK_NEXT_SHEET_ID:"test",SK_NEXT_TAB:"test",Logger:{log:()=>{}},
 soulkeyNextExport_:()=>[{task:"P262-L01",lang:"es",complete:true,
                            qa_new_complete:exportsChanged}],
 soulkeyNextUpdateJobs_:()=>{},
 soulkeyNextQAOneBatch_:(task,lang)=>{
   assert.equal(locked,false,"must release translation lock before QA");
   qaCalls.push([task,lang]);return {ok:true,reviewed:6};
 }
};
vm.createContext(tickCtx);
vm.runInContext(section(next,"soulkeyNextTick","soulkeyNextInstall"),tickCtx);
let result=tickCtx.soulkeyNextTick();
assert.deepEqual(qaCalls,[["P262-L01","es"]]);
assert.equal(result.immediate_qa[0].reviewed,6);
assert.equal(result.immediate_qa_deferred,0);
exportsChanged=false;
result=tickCtx.soulkeyNextTick();
assert.equal(qaCalls.length,1,"unchanged complete DRAFT must not re-review");
assert.deepEqual(Array.from(result.immediate_qa),[]);
// Independent QA worker obeys specific lesson + language, and uses same
// revision and persistent report as its ordinary scheduled 15-minute pass.
const qaRecords=[];
const lessons=["P262-L02","P262-L01"].map(task=>({
 task,folder:{},source_file_id:"src",period:262,
 segments:[{id:1,start:0,end:80,text:"Hello",source_hash:"hash"}]
}));
const qaCtx={
 PropertiesService:{getScriptProperties:()=>({getProperty:()=> "yes"})},
 LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})},
 soulkeyNextSources_:()=>lessons,
 skNQTerms_:()=>[],SK_NEXT_PRIORITY_LANGS:["id","es"],
 soulkeyNextSelectedCodes_:()=>["es","id"],
 skNQDraft_:()=>({id:"draft",draft:{segments:[{id:1,text:"Hola"}]}}),
 skNQRisks_:()=>[{id:1,selected_for_ai:true,hard_errors:[],risk_flags:[],glossary:[]}],
 soulkeyNextSha_:()=> "revision",
 readJsonFile_:()=>null,
 skNQCall_:(lang,items)=>{qaRecords.push({lang,items});return [{id:1,grade:"A"}]},
 skNQSummary_:()=>({state:"approved_risk_based",review_scope:"risk_based",
   model_reviewed_pass:1,model_review_required:1}),
 writeTextFile_:(folder,name,content)=>qaRecords.push({name,content}),
 soulkeyNextNow_:()=> "2026-11-15 13:00",
 Logger:{log:()=>{}},
};
vm.createContext(qaCtx);
vm.runInContext(section(quality,"soulkeyNextQAOneBatch_","soulkeyNextQATick"),qaCtx);
const focused=qaCtx.soulkeyNextQAOneBatch_("P262-L01","es");
assert.equal(focused.task,"P262-L01");
assert.equal(focused.lang,"es");
assert.equal(qaRecords.filter(x=>x.lang).length,1);
assert.equal(qaRecords[1].name,"sheets.qa.native.es.json");
assert.equal(JSON.parse(qaRecords[1].content).state,"approved_risk_based");
// Playback repair: 12 stale, ALREADY copied files may not consume the entire
// copying budget; the missing destination remains eligible on this tick.
const ids=Array.from({length:13},(_,i)=>"P261-L"+String(i+1).padStart(2,"0"));
const srcs=ids.map(id=>({task:id,period:261,segments:[]}));
const copied=[];
const playbackCtx={
 PropertiesService:{getScriptProperties:()=>({getProperty:()=> "yes"})},
 LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})},
 soulkeyNextSources_:()=>srcs,skNQTerms_:()=>[],
 readTasks_:()=>ids.map(id=>({id,title:"Title",lecturer:"Teacher"})),
 SK_AUDIO_LANGUAGES:["en"],soulkeyNextSelectedCodes_:()=>["en"],
 skAudioPayload_:()=>({tag:"tag",sha:"abcdef0123456789",review:"approved_english_final"}),
 skAudioSaveSource_:()=>{},
 skAudioReceipt_:()=>({release_tag:"tag",status:"done",mp3_drive_id:"id",
                        source_sha256:"abcdef0123456789"}),
 DriveApp:{getFileById:()=>({
   getName:()=> "P261-L01-en-abcdef0123456789.mp3",
   getSize:()=>10,isTrashed:()=>false
 })},
 skPlaybackReceipt_:lesson=>lesson.task===ids[12]?null:({
   status:"copied",sha:"abcdef0123456789",release_tag:"tag",
   source_status:"done",review:"approved_english_final",tier:"formal",
   source_mp3_id:"id",last_verified_at:"2026-10-01T00:00:00Z"
 }),
 skPlaybackEnsure_:(lesson)=>{copied.push(lesson.task);return {ok:true}},
 Logger:{log:()=>{}}
};
// Source names must match each lesson; adjust Drive mock dynamically.
let currentTask="";
playbackCtx.skAudioPayload_=lesson=>{currentTask=lesson.task;return {
 tag:"tag",sha:"abcdef0123456789",review:"approved_english_final"}};
playbackCtx.DriveApp.getFileById=()=>({
 getName:()=>currentTask+"-en-abcdef0123456789.mp3",
 getSize:()=>10,isTrashed:()=>false
});
vm.createContext(playbackCtx);
vm.runInContext(audio.slice(audio.indexOf("function soulkeyNextAudioTick(){")),playbackCtx);
const summary=playbackCtx.soulkeyNextAudioTick();
assert.equal(summary.ok,true);
assert.equal(copied.includes(ids[12]),true,"missing classroom copy must not be starved");
assert.equal(copied.length,2,"one periodic validation plus the missing copy");
console.log("PASS: immediate per-language QA after lock + revision guard + missing playback prioritized");

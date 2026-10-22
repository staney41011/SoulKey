"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const bridge=fs.readFileSync(path.resolve(root,"../bridge/apps-script/Code.gs"),"utf8");
const app=fs.readFileSync(path.resolve(root,"app-20260923-48.js"),"utf8");
function fn(source,name){
  const from=source.indexOf("function "+name+"(");
  assert(from>=0,"Function missing: "+name);
  const next=source.indexOf("\nfunction ",from+10);
  return source.slice(from,next<0?undefined:next);
}

function draft(){
  return {task_id:"P258-L03",segments:[
    {id:63,en_text:"Original 63",en_confirmed:false,source_en:""},
    {id:64,en_text:"Original 64",en_confirmed:false,source_en:""},
    {id:65,en_text:"Original 65",en_confirmed:false,source_en:""},
  ]};
}
let stored=null;
let receipt="";
let locks=0,releases=0,uploads=0;
const props={setProperty:(k,v)=>{if(k.includes("_RECEIPT_"))receipt=v;}};
const context={
  LockService:{getScriptLock:()=>({waitLock:()=>locks++,releaseLock:()=>releases++})},
  PropertiesService:{getScriptProperties:()=>props},
  lessonFolders_:()=>({translation:"fake-folder"}),
  readJsonFile_:()=>stored,
  loadReview_:()=>({ok:true,segments:draft().segments.map(row=>({
    id:row.id,start:0,end:5,time:"00:00:00",
    original:"中文",en:row.en_text,en_confirmed:row.en_confirmed,
    pre_aligned:true,ids:[row.id]
  }))}),
  writeTextFile_:(f,n,body)=>{assert.equal(n,"en.review.draft.json");stored=JSON.parse(body);uploads++;},
  normalizedReviewSharePayload_:(taskId,body)=>({ok:true,payload:{...JSON.parse(body),task_id:taskId}}),
  taskInfo_:()=>({}),
  scheduleChineseCacheRepair_:()=>true,
};
vm.createContext(context);
vm.runInContext(fn(bridge,"mergeEnglishConfirmedDraft_")+"\n"+fn(bridge,"reviewEnglishDraftSave_"),context);
const alpha=draft();alpha.segments[0].en_text="Human editor A: new 63";alpha.segments[0].en_confirmed=true;
alpha.confirmed_segment_ids=[63];alpha.save_request_id="alpha";
alpha.segments=[alpha.segments[0]];
const ra=context.reviewEnglishDraftSave_("P258-L03",JSON.stringify(alpha));
assert.equal(ra.ok,true);
assert.equal(JSON.parse(receipt).request_id,"alpha");
const beta=draft();beta.segments[1].en_text="Human editor B: new 64";beta.segments[1].en_confirmed=true;
beta.confirmed_segment_ids=[64];beta.save_request_id="beta";
beta.segments=[beta.segments[1]];
const rb=context.reviewEnglishDraftSave_("P258-L03",JSON.stringify(beta));
assert.equal(rb.ok,true);
assert.equal(stored.segments[0].en_text,"Human editor A: new 63","Second device must preserve first editor");
assert.equal(stored.segments[1].en_text,"Human editor B: new 64");
assert.equal(stored.segments[0].en_confirmed,true);
assert.equal(stored.segments[1].en_confirmed,true);
assert.equal(stored.segments[2].en_confirmed,false);
assert.equal(uploads,2);
assert.equal(locks,2);
assert.equal(releases,2);
const stale=draft();stale.segments[0].en_text="BAD old browser";stale.segments[0].en_confirmed=true;
assert.equal(context.reviewEnglishDraftSave_("P258-L03",JSON.stringify(stale)).error,"client_upgrade_required");
assert.equal(uploads,2,"Old clients must not overwrite cloud with untracked full manuscript");
const conflicting=draft();conflicting.segments.pop();conflicting.confirmed_segment_ids=[65];conflicting.save_request_id="conflict";
assert.equal(context.reviewEnglishDraftSave_("P258-L03",JSON.stringify(conflicting)).ok,false);
assert.equal(locks,3);assert.equal(releases,3);
assert.equal(stored.segments[0].en_text,"Human editor A: new 63");

assert.ok(/requestReviewData\(taskId,"en",0\);\s*return;/.test(app),
  "After showing a GitHub cache, always verify latest Drive manuscript");
assert.ok(app.includes("englishReviewDirtyIds.add(Number(item.id))"));
assert.ok(app.includes("ENGLISH_UNCONFIRMED_BACKUP_PREFIX+selectedTaskId"));
assert.ok(app.includes("const dirty=new Map(currentEnglishReview"));
assert.ok(app.includes("englishDraftSavedSnapshot.confirmed_segment_ids=ids"));
assert.ok(app.includes("showEnglishDraftRecovery(taskId)"));
assert.ok(app.includes('mode:"no-cors"'),"Use small cross-origin POST, not hidden iframe");
assert.ok(app.includes('segments:englishDraftSavedSnapshot.segments.filter('),
  "Send one confirmed sentence, not whole lesson");
const displayContext={};
vm.createContext(displayContext);
vm.runInContext(fn(app,"englishReviewDisplayChinese"),displayContext);
const zh="因為你不知道。誰會藉著你的善良，走出了絕望。";
assert.equal(displayContext.englishReviewDisplayChinese(zh+zh),zh,
  "Only exact repeated whole paragraphs fold in presentation");
assert.equal(displayContext.englishReviewDisplayChinese(zh+"但是故事還沒講完。"),
  zh+"但是故事還沒講完。",
  "Do not truncate genuine original teaching");

console.log("SOULKEY_ENGLISH_DRIVE_AUTHORITY_AND_CONCURRENT_EDIT_MERGE_OK");

"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const source=fs.readFileSync(path.join(__dirname,"../../bridge/apps-script/Code.gs"),"utf8");
const props=new Map([["GITHUB_TOKEN","token"]]);
let fileMap={
  "transcript/segments.json":{segments:[
    {id:0,start:0,end:1,text:"raw0"},
    {id:1,start:1,end:2,text:"raw1"},
    {id:2,start:2,end:3,text:"raw2"}
  ]},
  "transcript/polish_report.json":{segments:[
    {id:0,start:0,end:1,text:"polish0"},
    {id:1,start:1,end:2,text:"polish1"},
    {id:2,start:2,end:3,text:"polish2"}
  ]}
};
let published=[];
let failures=0;
let triggers=[];
const context={
  PropertiesService:{getScriptProperties:()=>({
    getProperty:key=>props.get(key)||"",
    setProperty:(key,value)=>props.set(key,String(value)),
    deleteProperty:key=>props.delete(key),
    getProperties:()=>Object.fromEntries(props)
  })},
  ScriptApp:{
    getProjectTriggers:()=>triggers,
    newTrigger:name=>({timeBased(){return this},
      everyMinutes(n){assert.equal(n,15);return this},
      create(){triggers.push({getHandlerFunction:()=>name})}})
  },
  Utilities:{
    Charset:{UTF_8:"UTF8"},
    base64Encode:t=>Buffer.from(t).toString("base64"),
    sleep:()=>{}
  },
  Logger:{log:()=>{}}
};
vm.createContext(context);
vm.runInContext(source,context);
context.lessonFolders_=()=>({transcript:"transcript",source:"source",translation:"translation"});
context.readJsonFile_=(folder,name)=>fileMap[folder+"/"+name]||null;
context.githubUpsertBase64_=(_token,name,b64)=>{
  const obj=JSON.parse(Buffer.from(b64,"base64").toString("utf8"));
  published.push({name,data:obj});
  if(failures-->0)return {ok:false,error:"simulated_503",github_status:503};
  return {ok:true,path:name};
};
let result=context.seedReviewCache_("P257-L04","token");
assert.equal(result.ok,true);
assert.equal(published.at(-1).data.segments[0].text,"polish0");
console.log("PASS: AI polish publishes initial GitHub zh.json");

fileMap["transcript/zh-TW.final.json"]={
  finalized_at:"2026-10-09T12:51:00+08:00",
  segments:[
    {id:0,start:0,end:1.5,text:"human0"},
    {id:2,start:1.5,end:3,text:"human2"}
  ]
};
failures=1;
result=context.seedReviewCache_("P257-L04","token");
assert.equal(result.ok,false);
assert.equal(published.at(-1).data.segments.length,2);
assert.equal(published.at(-1).data.segments[0].text,"human0");
assert.equal(published.at(-1).data.segments[1].text,"human2");
assert.equal(context.chineseReviewCacheRevisionState_("P257-L04").stale,true);
assert.equal(triggers.length,1);
console.log("PASS: failed GitHub publication leaves durable retry and detects stale revision");

result=context.repairPendingChineseReviewCaches_();
assert.equal(result.checked,1);
assert.equal(context.chineseReviewCacheRevisionState_("P257-L04").stale,false);
assert.equal(context.chineseReviewCacheRevisionState_("P257-L04").published,
  "2026-10-09T12:51:00+08:00");
assert.equal(published.at(-1).data.segments.length,2);
assert.equal(published.at(-1).data.segments[0].start,0);
console.log("PASS: scheduled retry publishes EXACT Final segmentation and clears pending");

let requestedEnglish=0;
context.seedEnglishReviewCache_=()=>{requestedEnglish++;return {ok:true}};
context.writeTextFile_=(folder,name,contents)=>{
  if(name.endsWith(".json"))fileMap[folder+"/"+name]=JSON.parse(contents);
};
context.nowText_=()=>"2026-10-09 12:51:00";
context.taskInfo_=()=>({row:4});
context.getSheetByName_=()=>({getRange:()=>({setValue:()=>{}})});
context.appendExecutionStatus_=()=>{};
context.invalidateDownstreamAfterHumanFinal_=()=>{};
const finalized=context.saveReview_("P257-L04","zh",[
  {id:0,start:0,end:1.5,text:"Newest final human"},
  {id:2,start:1.5,end:3,text:"Updated human"}
],[]);
assert.equal(finalized.ok,true);
assert.equal(finalized.zh_cache_ready,true);
assert.equal(context.chineseReviewCacheRevisionState_("P257-L04").stale,false);
assert.equal(published.at(-1).data.segments[0].text,"Newest final human");
assert.equal(published.at(-1).data.zh_finalized_at,finalized.finalized_at);
assert.equal(requestedEnglish,1);
console.log("PASS: saving Chinese Final publishes matching revision and queues English alignment");

context.getRuntimeJob_=()=>({task_id:"P257-L04"});
published=[];
context.workerReviewPublish_("nonce","P257-L04","this is an obsolete AI draft");
assert.equal(published.at(-1).data.segments[0].text,"Newest final human");
console.log("PASS: rerun of AI polish can NEVER overwrite an existing human Final");

context.normalizedReviewSharePayload_=()=>({ok:true,payload:{
  segments:[
    {id:0,start:0,end:1.5,text:"OLDER local copy",en_text:"English"},
    {id:2,start:1.5,end:3,text:"OLDER local copy 2"}
  ],zh_finalized_at:""
}});
let quickPayload=null;
context.publishReviewSharePayload_=(_id,data)=>{
  quickPayload=data;return {ok:true};
};
let draft=context.reviewShareDraftSave_("P257-L04","{}");
assert.equal(draft.ok,true);
assert.equal(quickPayload.segments[0].text,"Newest final human");
assert.equal(quickPayload.segments[0].en_text,"English");
assert.equal(quickPayload.zh_finalized_at,finalized.finalized_at);
console.log("PASS: old browser draft cannot roll back Chinese Final; English stays editable");
context.normalizedReviewSharePayload_=()=>({ok:true,payload:{
  segments:[{id:0,text:"one"}],zh_finalized_at:""
}});
quickPayload=null;
draft=context.reviewShareDraftSave_("P257-L04","{}");
assert.equal(draft.ok,false);
assert.equal(draft.error,"final_segment_layout_mismatch");
assert.equal(quickPayload,null);
console.log("PASS: incompatible stale browser segmentation is rejected");

// A new AI polish finishing after an already-saved human draft cannot
// overwrite that editor's latest GitHub text, even before Final exists.
const officialFinal=fileMap["transcript/zh-TW.final.json"];
delete fileMap["transcript/zh-TW.final.json"];
published=[];
const protectedPublish=context.workerReviewPublish_(
  "nonce","P257-L04","obsolete-polish-content"
);
assert.equal(protectedPublish.ok,true);
assert.equal(protectedPublish.skipped,true);
assert.equal(published.length,0);
fileMap["transcript/zh-TW.final.json"]=officialFinal;
console.log("PASS: late AI polish does not overwrite a human Chinese draft");

const ui=fs.readFileSync(path.join(__dirname,"../../studio/app-20260923-48.js"),"utf8");
const quick=fs.readFileSync(path.join(__dirname,"../../studio/review-editor.js"),"utf8");
assert.ok(ui.includes('action:"review_cache_status"'));
assert.ok(quick.includes('action:"review_cache_status"'));
assert.ok(!ui.includes('Seed/rebuild in the background whenever'));
console.log("PASS: both editors validate cache revision without unconditional re-seeding");

const originalOnce=context.githubUpsertBase64Once_;
const begin=source.indexOf("function githubUpsertBase64_(");
const finish=source.indexOf("\nfunction githubUpsertBase64Once_(",begin);
context.githubUpsertBase64_=vm.runInContext("("+source.slice(begin,finish)+")",context);
let calls=0;
context.githubUpsertBase64Once_=()=>{
  calls++;
  return calls<3?{ok:false,github_status:409}:{ok:true};
};
result=context.githubUpsertBase64_("token","path","Zm9v","test");
assert.equal(result.ok,true);
assert.equal(calls,3);
context.githubUpsertBase64Once_=originalOnce;
console.log("PASS: GitHub 409 conflict retries resolve without a second AI run");

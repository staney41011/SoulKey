"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const root=path.resolve(__dirname,"../..");
const app=fs.readFileSync(path.join(root,"studio/app-20260923-48.js"),"utf8");
const bridge=fs.readFileSync(path.join(root,"bridge/apps-script/Code.gs"),"utf8");
const between=(s,a,b)=>{
 const i=s.indexOf(a),j=s.indexOf(b,i+1);
 assert(i>=0&&j>i,"markers missing "+a+" "+b);
 return s.slice(i,j);
};
const store=new Map();
const props={
 setProperty:(k,v)=>store.set(k,v),
 getProperty:k=>store.get(k),
 deleteProperty:k=>store.delete(k),
 getProperties:()=>Object.fromEntries(store)
};
const backend={
 JSON,Number,String,Array,Object,Math,Date,RegExp,
 PropertiesService:{getScriptProperties:()=>props},
 formatPlainTime_:()=> "00:00:00",
 readJsonFile_:(_dir,name)=>store.get("DRIVE:"+name),
 taskInfo_:()=>({}),
 lessonFolders_:()=>({translation:"translation"}),
 writeTextFile_:(_dir,name,text)=>store.set("DRIVE:"+name,JSON.parse(text)),
 publishEnglishReviewCachePayload_:()=>({ok:false,error:"github_unavailable"}),
 scheduleChineseCacheRepair_:()=>true
};
vm.createContext(backend);
vm.runInContext(
 between(bridge,"function normalizedReviewSharePayload_","function publishReviewSharePayload_")+
 between(bridge,"function reviewEnglishDraftSave_","function reviewShareFinalize_")+
 between(bridge,"function repairPendingEnglishReviewCaches_","function repairPendingChineseReviewCaches_"),
 backend
);
const source=[
 {id:0,start:0,end:9,text:"一",en_text:"Dear family, peace be with you all.",en_confirmed:true,pre_aligned:true,zh_ids:[0,1,2]},
 {id:4,start:9,end:12,text:"二",en_text:"Thank you.",en_confirmed:false,pre_aligned:true,zh_ids:[4]}
];
const example={version:6,task_id:"P257-L02",alignment_method:"english_sentence_chinese_time_v1",segments:source};
let result=backend.reviewEnglishDraftSave_("P257-L02",JSON.stringify(example));
assert.equal(result.ok,true);
assert.equal(result.github_synced,false);
assert.deepEqual(Array.from(store.get("DRIVE:en.review.draft.json").segments[0].zh_ids),[0,1,2]);
assert.equal(store.get("DRIVE:en.review.draft.json").segments[0].en_confirmed,true);
assert(store.has("SOULKEY_EN_CACHE_PENDING_P257-L02"));
backend.publishEnglishReviewCachePayload_=()=>({ok:true});
assert.equal(backend.repairPendingEnglishReviewCaches_().checked,1);
assert(!store.has("SOULKEY_EN_CACHE_PENDING_P257-L02"));
backend.writeTextFile_=()=>{throw new Error("Drive offline")};
result=backend.reviewEnglishDraftSave_("P257-L02",JSON.stringify(example));
assert.equal(result.ok,false);
backend.lessonFolders_=()=>({translation:"translation",transcript:"transcript",source:"source"});
backend.readJsonFile_=(_dir,name)=>{
 if(name==="zh-TW.final.json")return {segments:[{id:0,start:0,end:9,text:"一"}]};
 return store.get("DRIVE:"+name)||null;
};
let seeded=null;
backend.publishEnglishReviewCachePayload_=(id,rows)=>{
 seeded=JSON.parse(JSON.stringify(rows));return {ok:true};
};
vm.runInContext(between(bridge,"function seedEnglishReviewCache_","// Fast metadata comparison"),backend);
const seedResult=backend.seedEnglishReviewCache_("P257-L02");
assert.equal(seedResult.ok,true);
assert.equal(seeded.segments[0].pre_aligned,true,
 "Cache seed must preserve confirmed human paragraph boundaries");
assert.deepEqual(seeded.segments[0].zh_ids,[0,1,2]);
assert.equal(seeded.segments[0].en_confirmed,true);
console.log("PASS: English cache seeding never erases saved paragraph pairing or confirmations");

console.log("PASS: Drive is authoritative; GitHub failure queues repair; original alignment retained; true Drive failure rejected");

const uiStore=new Map();
const rows=new Map([0,4].map(id=>[
 id,{button:{textContent:"儲存中…",disabled:true,classList:{toggle(){}}},
 row:{classList:{toggle(){}},querySelector(){return rows.get(id).button;}}}
]));
let requests=[],callbacks=[],cache;
const ui={
 JSON,Number,String,Array,Object,Math,Date,
 ENGLISH_DRIVE_ACK_PREFIX:"soulkey_en_drive_ack:",
 selectedTaskId:"P257-L02",
 currentEnglishReview:source.map(x=>({
  id:x.id,ids:x.zh_ids,pre_aligned:true,
  start:x.start,end:x.end,original:x.text,
  en:x.en_text,source_en:x.en_text,en_confirmed:x.en_confirmed
 })),
 tasks:[{id:"P257-L02",url:"https://youtu.be/test"}],
 englishDraftSavePendingId:null,englishDraftSaveQueuedId:null,
 englishDraftSaveWatchdog:null,englishDraftSavedSnapshot:null,
 document:{
  getElementById:()=>({textContent:""}),
  querySelector:q=>{
   const match=/data-en-segment="(\d+)"/.exec(q);
   return match?rows.get(Number(match[1]))?.row:null;
  }
 },
 window:{
  setTimeout:cb=>{callbacks.push(cb);return callbacks.length;},
  clearTimeout:()=>{}
 },
 localStorage:{
  setItem:(k,v)=>uiStore.set(k,v),
  removeItem:k=>uiStore.delete(k),
  getItem:k=>uiStore.get(k)
 },
 youtubeVideoIdFromUrl:()=> "test",
 formatClock:()=> "00:00:00",
 submitBridgePost:p=>{requests.push(p);return true},
 writeReviewCache:x=>cache=x
};
vm.createContext(ui);
vm.runInContext(
 between(app,"function englishReviewDraftPayload()","function renderEnglishReview(items)")+
 "function response(data){"+
 between(app,'  if(data.type==="english_review_draft_saved"){','  if(data.type==="review_saved"){')+
 "}\n",ui
);
ui.currentEnglishReview[0].en_confirmed=true;
assert.equal(ui.saveEnglishReviewDraft(0),true);
assert.equal(requests.length,1);
assert.equal(JSON.parse(requests[0].payload_json).segments[0].pre_aligned,true);
ui.currentEnglishReview[1].en_confirmed=true;
assert.equal(ui.saveEnglishReviewDraft(4),true);
assert.equal(requests.length,1,"Second click queues");
ui.response({type:"english_review_draft_saved",task_id:"P257-L02",ok:true,github_synced:false,saved_at:"2026-10-13T05:00:00Z"});
assert.equal(rows.get(0).button.textContent,"✓ 已確認");
assert(uiStore.has("soulkey_en_drive_ack:P257-L02"));
const ack=JSON.parse(uiStore.get("soulkey_en_drive_ack:P257-L02"));
assert.equal(ack.segments[1].en_confirmed,false,"Unsaved later edit must not count as acknowledged");
callbacks.pop()();
assert.equal(requests.length,2);
ui.response({type:"english_review_draft_saved",task_id:"P257-L02",ok:true,github_synced:true,saved_at:"2026-10-13T05:00:05Z"});
assert.equal(rows.get(4).button.textContent,"✓ 已確認");
assert.equal(cache.segments[1].en_confirmed,true);
console.log("PASS: Serialized confirmation callbacks, no button rollback, no phantom ACK, last click committed");

"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const bridge=fs.readFileSync(path.resolve(root,"../bridge/apps-script/Code.gs"),"utf8");
const client=fs.readFileSync(path.resolve(root,"app-20260923-48.js"),"utf8");
function func(text,name){
 const from=text.indexOf("function "+name+"(");
 assert(from>=0,name+" missing");
 const next=text.indexOf("\nfunction ",from+10);
 return text.slice(from,next<0?undefined:next);
}
const props=new Map([["BRIDGE_KEY","test-bridge-only"]]);
const files={};
let failure=false,readbackCorrupt=false,writes=0,locks=0,unlocks=0;
const fakeProps={
 getProperty:(k)=>props.get(k)||"",
 setProperty:(k,v)=>props.set(k,v)
};
const context={
 PropertiesService:{getScriptProperties:()=>fakeProps},
 LockService:{getScriptLock:()=>({waitLock:()=>locks++,releaseLock:()=>unlocks++})},
 taskInfo_:()=>({id:"P258-L04"}),
 lessonFolders_:()=>({translation:"simulated-folder"}),
 readJsonFile_:(folder,name)=>{
   if(name!=="en.review.edits.json")throw Error("Unexpected dependency on "+name);
   const value=files[name]||null;
   return readbackCorrupt&&value?{...value,edits:{}}:value;
 },
 writeTextFile_:(folder,name,text)=>{
   assert.equal(name,"en.review.edits.json",
      "First confirmed sentence must NOT require whole draft");
   if(failure)throw Error("simulated Google Drive outage");
   files[name]=JSON.parse(text);writes++;
 },
 formatPlainTime_:()=>"",
};
vm.createContext(context);
vm.runInContext([
 func(bridge,"normalizedReviewSharePayload_"),
 func(bridge,"reviewEnglishDraftSave_"),
 func(bridge,"bridgeRequest")
].join("\n"),context);
function save(id,en,request,base=""){
 const payload={
   task_id:"P258-L04",save_request_id:request,confirmed_segment_ids:[id],
   segments:[{
     id,start:1020,end:1030,text:"原中文",source_en:"machine",
     en_text:en,en_confirmed:true,pre_aligned:true,zh_ids:[id],
     base_request_id:base
   }]
 };
 return context.reviewEnglishDraftSave_("P258-L04",JSON.stringify(payload));
}
const a=save(63,"Edited by A, remove unwanted fragment","save-63-a");
assert.equal(a.ok,true);
assert.equal(files["en.review.edits.json"].edits["63"].en_text,
  "Edited by A, remove unwanted fragment");
const b=save(64,"Edited by B at another device","save-64-b");
assert.equal(b.ok,true);
assert.equal(files["en.review.edits.json"].edits["63"].en_text,
  "Edited by A, remove unwanted fragment");
assert.equal(files["en.review.edits.json"].edits["64"].en_text,
  "Edited by B at another device");
const c=save(65,"","save-65-empty");
assert.equal(c.ok,true,"An intentionally blank segment must be saved");
assert.equal(files["en.review.edits.json"].edits["65"].en_text,"");
assert.equal(writes,3);assert.equal(locks,3);assert.equal(unlocks,3);
const stale=save(63,"Someone's stale edit","save-63-stale");
assert.equal(stale.ok,false,"Stale same-row edits must not overwrite newer review");
assert.equal(files["en.review.edits.json"].edits["63"].en_text,
  "Edited by A, remove unwanted fragment");
const repeat=save(63,"Edited by A, remove unwanted fragment","save-63-a");
assert.equal(repeat.ok,true,"A retried request is idempotent");
const updated=save(63,"New edit after reading latest","save-63-new","save-63-a");
assert.equal(updated.ok,true,"Editing an acknowledged revision is permitted");
const latest=context.bridgeRequest({
 action:"review_en_draft_status",task_id:"P258-L04",
 bridge_key:"test-bridge-only",request_id:"save-63-a",
 include_edits:"1"
});
assert.equal(latest.committed,true,"Earlier request ACK remains valid even after second editor");
assert.equal(latest.edits["64"].en_text,"Edited by B at another device");
assert.equal(latest.edits["65"].en_text,"");
const statusB=context.bridgeRequest({
 action:"review_en_draft_status",task_id:"P258-L04",
 bridge_key:"test-bridge-only",request_id:"save-64-b"
});
assert.equal(statusB.committed,true);
assert.equal(statusB.edits,undefined,"Receipt polling is light");
assert.equal(context.bridgeRequest({
 action:"review_en_draft_status",task_id:"P258-L04",
 bridge_key:"invalid",request_id:"save-63-a"
}).error,"unauthorized");

failure=true;
const failed=save(66,"Important correction","save-66-failed");
assert.equal(failed.ok,false);
assert.equal(context.bridgeRequest({
 action:"review_en_draft_status",task_id:"P258-L04",
 bridge_key:"test-bridge-only",request_id:"save-66-failed"
}).committed,false,"Failed writes never receive success ACK");
failure=false;

readbackCorrupt=true;
const corrupted=save(67,"Should never be marked successful","save-67-corrupt");
assert.equal(corrupted.ok,false,"Even write API success requires read-back");
readbackCorrupt=false;
assert.equal(context.bridgeRequest({
 action:"review_en_draft_status",task_id:"P258-L04",
 bridge_key:"test-bridge-only",request_id:"save-67-corrupt"
}).committed,false);

assert.match(client,/requestEnglishCloudOverrides\(taskId\)/);
assert.match(client,/request_id:requestId/);
assert.match(client,/data\.committed===true/);
assert.match(client,/list\.innerHTML=currentEnglishReview\.map/);
console.log("SOULKEY_EN_INDEPENDENT_DURABLE_STORE_OK");

"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),crypto=require("node:crypto");
const code=fs.readFileSync(path.join(__dirname,"../Code.gs"),"utf8");
function method(name){const a=code.indexOf("function "+name+"("),b=code.indexOf("\nfunction ",a+1);assert(a>=0);return code.slice(a,b<0?undefined:b);}
function setup(files){
  const reads=[];
  const context={Date,Utilities:{DigestAlgorithm:{SHA_256:"sha256"},
    computeDigest:(_kind,text)=>crypto.createHash("sha256").update(text).digest(),
    base64EncodeWebSafe:bytes=>Buffer.from(bytes).toString("base64url")},
    lessonFolders_:()=>({transcript:"zh",translation:"en",source:"source"}),
    readJsonFile_:(folder,name)=>{reads.push(folder+"/"+name);return files[folder+"/"+name]||null;},
    getSheetByName_:()=>({getDataRange:()=>({getDisplayValues:()=>[["zh","","","en"]]})}),
    formatPlainTime_:seconds=>String(seconds),reads};
  vm.createContext(context);
  for(const name of ["loadChineseFinalReviewChunk_","loadZhReviewChunk_","chineseFinalForEnglishTimeRange_","loadReview_"])
    vm.runInContext(method(name),context);
  return context;
}
const final={task_id:"P259-L01",central_finalized_at:"2026-10-29T10:00:00Z",segments:Array.from({length:449},(_,id)=>({id,start:id,end:id+1,text:"Human Final "+id}))};
const before=JSON.stringify(final),ctx=setup({"zh/zh-TW.final.json":final});
let all=[];let revision;
for(let i=0;i<3;i++){
  const data=ctx.loadZhReviewChunk_({transcript:"zh"},"P259-L01",i,Date.now());
  assert(data.ok);assert(data.is_final);assert.equal(data.review_source,"zh-TW.final.json");
  assert.equal(data.zh_finalized_at,final.central_finalized_at);
  if(revision)assert.equal(data.review_revision,revision);else revision=data.review_revision;
  assert.equal(data.has_more,i<2);all.push(...data.segments);
}
assert.equal(all.length,449);assert.equal(new Set(all.map(x=>x.id)).size,449);
all.forEach((x,i)=>{assert.equal(x.text,final.segments[i].text);assert.equal(x.confirmed,true);});
assert(ctx.reads.every(x=>x==="zh/zh-TW.final.json"),"A Final must not fall back to stale ASR/polish chunks");
assert.equal(JSON.stringify(final),before,"Reading must not mutate or re-finalize the human manuscript");
const changed=setup({"zh/zh-TW.final.json":{...final,segments:[{id:0,text:"Later human revision"}]}});
assert.notEqual(changed.loadZhReviewChunk_({transcript:"zh"},"P259-L01",0,Date.now()).review_revision,revision);
const wrong=setup({"zh/zh-TW.final.json":{...final,task_id:"P259-L02"}});
assert.equal(wrong.loadZhReviewChunk_({transcript:"zh"},"P259-L01",0,Date.now()).ok,false);
const broken=setup({"zh/zh-TW.final.json":{segments:[]}});
assert.equal(broken.loadZhReviewChunk_({transcript:"zh"},"P259-L01",0,Date.now()).ok,false);
const draft=setup({"zh/zh-TW.review.manifest.json":{first_chunk:[{id:0,text:"Draft",confirmed:false}],chunk_count:1,total_segments:1}});
const draftData=draft.loadZhReviewChunk_({transcript:"zh"},"P259-L01",0,Date.now());
assert(draftData.ok);assert.equal(draftData.is_final,undefined);assert.equal(draftData.segments[0].confirmed,false);
const english=setup({"zh/zh-TW.final.json":final,"en/en.final.json":{central_finalized_at:"2026-10-29T12:00:00Z",segments:[{id:1000,start:2,end:4,text:"Human English"}]}});
const data=english.loadReview_("P259-L01","en",0);
assert(data.ok);assert(data.is_final);assert.equal(data.finalized_at,"2026-10-29T12:00:00Z");
assert.equal(data.segments[0].original,"Human Final 2Human Final 3");
data.source="soulkey-bridge";assert.equal(data.review_source,"en.final.json","Reply source tagging must retain manuscript provenance");
const receipts=[],statusRows=[],admin={
  readTasks_:()=>[1,2,3,4].map(n=>({id:"P259-L0"+n})),
  PropertiesService:{getScriptProperties:()=>({getProperty:()=>"test-only-dispatch-secret"})},
  dispatchWorkflowIdempotently_(...args){assert.equal(args[1],"P259-L01");assert.equal(args[2],"multi");assert.equal(args[3],"central4");
    assert(args[5].startsWith("https://script.google.com/macros/s/"));return {ok:true,workflow_run_id:1234,nonce:"test-only-private-runtime"};},
  appendExecutionStatus_:(...args)=>statusRows.push(args),Logger:{log:x=>receipts.push(x)},Date};
vm.createContext(admin);vm.runInContext(method("resumeP259VerifiedWork_"),admin);
const receipt=admin.resumeP259VerifiedWork_();assert.equal(receipt.run_id,"1234");assert.equal(statusRows.length,1);
assert(!JSON.stringify(receipts).includes("test-only"));assert(!JSON.stringify(receipt).includes("nonce"));
admin.dispatchWorkflowIdempotently_=()=>({ok:true,duplicate:true});admin.resumeP259VerifiedWork_();
assert.equal(statusRows.length,1,"Duplicate recovery must not create another queued job");
admin.readTasks_=()=>[{id:"P259-L01"}];assert.throws(()=>admin.resumeP259VerifiedWork_(),/四堂課/);
console.log("PASS: authoritative Chinese Final chunks, exact revision/mutation protection, draft isolation and legacy central English Final provenance");

"use strict";
const fs=require("fs"),vm=require("vm"),assert=require("assert");
const path=require("path");
const directory=__dirname;
const scriptProperties={SOULKEY_NEXT_ENABLED:"yes"};
const props={
  getProperty:(key)=>scriptProperties[key]||null,
  setProperty:(key,value)=>{scriptProperties[key]=value;return props;}
};
const ctx=vm.createContext({
  PropertiesService:{getScriptProperties:()=>props},
  LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})},
  Utilities:{formatDate:()=>"2026-11-21 10:35:00"},
  Logger:{log:()=>{}}
});
for(const file of ["NativeNext.gs","NativeQuality.gs","NativeAudio.gs"]){
  new vm.Script(fs.readFileSync(path.join(directory,file),"utf8"),{
    filename:file
  }).runInContext(ctx);
}
assert.equal(ctx.soulkeyNextNormalizeTask_({triggerUid:"abc"}),"");
assert.equal(ctx.soulkeyNextNormalizeTask_("P263-L02"),"P263-L02");
assert.equal(ctx.soulkeyNextNormalizeTask_("P262-L03-R1"),"P262-L03-R1");
assert.equal(ctx.soulkeyNextNormalizeTask_("P263-L02;delete"),"");
const sources=[
  {task:"P261-L02",period:261,segments:[]},
  {task:"P263-L01",period:263,segments:[]},
  {task:"P263-L02",period:263,segments:[]}
];
ctx.soulkeyNextSources_=()=>sources;
let observed=[];
ctx.soulkeyNextEnsureRows_=function(selected){
  observed=Array.from(selected,x=>x.task);
  throw new Error("capture translation source scope");
};
assert.throws(()=>ctx.soulkeyNextTick({triggerUid:"timer"}),/capture translation/);
assert.deepEqual(observed,["P263-L01","P263-L02"],
  "time trigger event must NOT filter out all lessons");
assert.equal(JSON.parse(scriptProperties.SOULKEY_NEXT_HEALTH_TRANSLATION).mode,
 "scheduled");
observed=[];
assert.throws(()=>ctx.soulkeyNextTick("P263-L02"),/capture translation/);
assert.deepEqual(observed,["P263-L02"],"manual targeting must remain intact");
assert.throws(()=>ctx.soulkeyNextTick("P261-L02"),/capture translation/);
assert.deepEqual(observed,["P261-L02"],
  "abandoned old lessons remain available by explicit manual focus");
ctx.skNQTerms_=()=>{throw new Error("capture audio source scope");};
assert.throws(()=>ctx.soulkeyNextAudioTick({triggerUid:"timer"}),/capture audio/);
assert.equal(JSON.parse(scriptProperties.SOULKEY_NEXT_HEALTH_AUDIO).mode,
 "scheduled");
ctx.skNQTerms_=()=>[];
ctx.soulkeyNextSelectedCodes_=()=>["es"];
ctx.skNQDraft_=()=>({id:"draft-id",draft:{segments:[
  {id:189,text:"candidate"}]}});
ctx.skNQRisks_=()=>[{id:189,hard_errors:[],risk_flags:[],
  selected_for_ai:true}];
ctx.soulkeyNextSha_=()=>"digest";
ctx.readJsonFile_=()=>({revision_key:"digest",
  decisions:{"189":{grade:"C",reason:"needs human review"}}});
const result=ctx.soulkeyNextQAOneBatch_("P263-L02","es");
assert.equal(result.ok,true);
assert.equal(result.reason,"blocked_requires_review",
  "grade C must not be silently reported as QA complete");
assert.equal(result.blockers.length,1);
assert.equal(result.blockers[0].task,"P263-L02");
assert.equal(result.blockers[0].blocked_ids[0],189);
console.log("PASS scheduled event normalization, manual scoping, audio trigger, health checkpoint and C-grade visibility");

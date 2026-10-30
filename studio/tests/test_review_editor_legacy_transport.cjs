"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const code=fs.readFileSync(path.join(__dirname,"../review-editor.js"),"utf8");
const endpoint="https://script.google.com/macros/s/test-deployment/exec";
function section(a,b){const start=code.indexOf(a),end=code.indexOf(b,start+a.length);assert(start>=0&&end>start);return code.slice(start,end);}
async function test(){
  const forms=[];
  const document={body:{appendChild(){}},createElement:tag=>({tag,children:[],style:{},setAttribute(){},appendChild(x){this.children.push(x);},remove(){},submit(){forms.push(this);}})};
  const cfg={bridgeEndpoint:endpoint,legacyKaggleBridgeEndpoint:endpoint,mode:"legacy-kaggle"};
  const ctx={cfg,BRIDGE_ENDPOINT:endpoint,bridgeProtocolVersion:9,REQUIRED_BRIDGE_PROTOCOL:9,
    document,finishTarget:"",videoId:"video",taskId:"P259-L03",Date,Math,URLSearchParams,
    bridgeKeyValue:()=>"test-only-key",setStatus(){},setTimeout(){return 1;},
    window:{SoulKeyBridgeRoutes:require("../bridge-routing.js")},fetch(){throw Error("Legacy writes must not use CORS fetch");}};
  vm.runInNewContext(section("function submit(fields){","async function centralReviewRequest("),ctx);
  assert(ctx.submit({action:"review_share_finalize_en",task_id:"P259-L03",segments_json:"[]"}));
  assert.equal(forms[0].action,endpoint);
  assert.equal(Object.fromEntries(forms[0].children.map(x=>[x.name,x.value])).action,"review_share_finalize_en");
  assert(!forms[0].action.includes("test-only-key"));
  const listeners=new Set(),requests=[];
  const bridgeContext={BRIDGE_ENDPOINT:endpoint,cfg,taskId:"P259-L03",legacyDraftBatchRequests:0,JSON,String,Promise,setTimeout,clearTimeout,
    bridgeKeyValue:()=>"test-only-key",window:{
      SoulKeyBridgeRoutes:{readLegacy(_cfg,_key,fields,options){requests.push(fields);options.onResult({ok:true,edits:{}});return true;}},
      addEventListener(_name,fn){listeners.add(fn);},removeEventListener(_name,fn){listeners.delete(fn);}},
    submit(fields){
      requests.push(fields);
      const send=data=>{for(const fn of [...listeners])fn({data});};
      send({source:"soulkey-bridge",type:"english_review_draft_saved",task_id:"P259-L02",request_id:"request-1",ok:true});
      send({source:"soulkey-bridge",type:"english_review_draft_saved",task_id:"P259-L03",request_id:"wrong",ok:true});
      send({source:"soulkey-bridge",type:"english_review_draft_saved",task_id:"P259-L03",request_id:"request-1",ok:true});
      return true;},fetch(){throw Error("Legacy requests must not use CORS fetch");}};
  vm.runInNewContext(section("async function centralReviewRequest(","async function saveCentralEnglishDraft("),bridgeContext);
  const saved=await bridgeContext.centralReviewRequest({action:"review_en_draft_save",task_id:"P259-L03",payload_json:JSON.stringify({save_request_id:"request-1"})});
  assert(saved.ok);assert.equal(saved.request_id,"request-1");assert.equal(listeners.size,0);
  assert.equal(bridgeContext.legacyDraftBatchRequests,0);
  const ack={legacyDraftBatchRequests:1,saveInFlight:true,saveRevisionInFlight:53,lastSavedRevision:0,revision:53,
    saveQueued:false,dirty:true,$:()=>({}),setStatus(){}};
  const branch=section('  if((data.type==="review_share_draft_saved"','  if(data.type==="review_share_finalized"');
  vm.runInNewContext('function receiveBatch(data){'+branch+'}',ack);
  ack.receiveBatch({type:"english_review_draft_saved",ok:true});
  assert.equal(ack.saveInFlight,true,"An early 25-row receipt must not mark all 53 rows saved");
  ack.legacyDraftBatchRequests=0;ack.receiveBatch({type:"english_review_draft_saved",ok:true});
  assert.equal(ack.saveInFlight,false);
  await bridgeContext.centralReviewRequest({action:"review_en_draft_status",task_id:"P259-L03"});
  assert.equal(requests.at(-1).action,"review_en_draft_status");
  const sent=[],plan=[{language_code:"en",audio_enabled:true},{language_code:"ja",audio_enabled:true}];let finishSave;
  const finish={payload:{en_finalized_at:"verified"},BRIDGE_ENDPOINT:endpoint,taskId:"P259-L03",LANG_NAMES_ZH:{en:"英文",ja:"日文"},
    confirm:()=>true,collectOutputPlan:()=>plan,$:()=>({}),setStatus(){},navigator:{userAgent:"desktop"},
    centralReviewRequest:()=>new Promise(resolve=>{finishSave=resolve;}),submit:x=>{sent.push(x);return true;},
    window:{setTimeout(){}},jsonpBridgeRequest(){},finishPending:null};
  vm.runInNewContext(section("function finishWorkflow(){",'window.addEventListener("message",event=>{'),finish);
  finish.finishWorkflow();assert.equal(sent.length,0,"Must wait for language-plan readback before dispatch");
  finishSave({ok:true});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(sent[0].action,"review_finish");assert.deepEqual(JSON.parse(sent[0].plan_json),plan);
  console.log("PASS: original Final actions, secret-free URLs, matching Drive edit receipts and plan-before-dispatch without CORS/GCP");
}
test().catch(error=>{console.error(error);process.exitCode=1;});

"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync(require("node:path").join(__dirname,"../review-editor.js"),"utf8");
const a=source.indexOf("async function saveCentralEnglishDraft("),b=source.indexOf("function requestDraftSave(",a);
async function saveScenario({edits={},lostAck=false,rows=53}={}){
  const writes=[],bases={};
  const ctx={taskId:"P259-L01",englishBaseRequests:bases,Date,Math,
    centralReviewRequest:async fields=>{
      if(fields.action==="review_en_draft_status")return {ok:true,edits,committed:lostAck};
      const payload=JSON.parse(fields.payload_json);writes.push(payload);
      if(lostAck)throw Error("response disconnected after commit");
      return {ok:true};
    }};
  vm.runInNewContext(source.slice(a,b),ctx);
  const segments=Array.from({length:rows},(_,id)=>({id,en_text:"Approved "+id,en_confirmed:true}));
  const result=await ctx.saveCentralEnglishDraft({segments});
  return {result,writes,bases};
}
(async()=>{
  const saved=await saveScenario();
  assert.deepEqual(saved.writes.map(x=>x.segments.length),[25,25,3]);
  assert.equal(Object.keys(saved.bases).length,53);
  assert.equal(saved.result.storage,"google-sheet");
  for(const batch of saved.writes){
    assert(batch.save_request_id);
    assert.equal(batch.confirmed_segment_ids.length,batch.segments.length);
    assert(batch.segments.every(x=>x.base_request_id===""));
  }
  await assert.rejects(saveScenario({edits:{0:{request_id:"other-browser",en_text:"Someone else's correction"}}}),/其他裝置/);
  const recovered=await saveScenario({lostAck:true,rows:1});
  assert.equal(recovered.result.ok,true);
  assert.equal(Object.keys(recovered.bases).length,1);

  const events=[],calls=[];
  const start=source.indexOf("function submit(fields){"),end=source.indexOf("async function centralReviewRequest(",start);
  const cfg={bridgeEndpoint:"https://central.example",legacyKaggleBridgeEndpoint:"https://legacy.example"};
  const ctx={BRIDGE_ENDPOINT:cfg.bridgeEndpoint,bridgeProtocolVersion:9,REQUIRED_BRIDGE_PROTOCOL:9,
    cfg,videoId:"actual-video",taskId:"P259-L01",finishTarget:"",URLSearchParams,
    bridgeKeyValue:()=>"test-only-passcode",setStatus(){},
    window:{SoulKeyBridgeRoutes:require("../bridge-routing.js"),dispatchEvent:e=>events.push(e)},
    fetch:async(url,options)=>{calls.push({url,body:Object.fromEntries(options.body)});return {json:async()=>({source:"soulkey-bridge",type:"review_saved",ok:true,task_id:"P259-L01"})};},
    MessageEvent:class{constructor(_,{data}){this.data=data;}}
  };
  vm.runInNewContext(source.slice(start,end),ctx);
  assert.equal(ctx.submit({action:"review_share_finalize_en",task_id:"P259-L01",segments_json:"[]"}),true);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls[0].url,cfg.bridgeEndpoint);
  assert.equal(calls[0].body.action,"review_save");
  assert.equal(calls[0].body.kind,"en");
  assert.equal(calls[0].body.source_video_id,"actual-video");
  assert.equal(events[0].data.type,"review_share_en_finalized");
  console.log("PASS: 53-sentence saves, conflict rejection, lost-ACK readback, central Final POST and editor ACK");
})().catch(error=>{console.error(error);process.exitCode=1;});

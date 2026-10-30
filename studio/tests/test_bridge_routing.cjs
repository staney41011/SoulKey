"use strict";
const assert=require("node:assert/strict");
const routes=require("../bridge-routing.js");
const cfg={bridgeEndpoint:"https://central.example",legacyKaggleBridgeEndpoint:"https://legacy.example"};
for(const action of ["tasks_get","status_health","status_batch","language_plan_save","review_save"])
  assert.equal(routes.endpoint(cfg,{action}),cfg.bridgeEndpoint,action);
for(const stage of ["zh","metadata","en","multi","tts","finish","batch"])
  assert.equal(routes.endpoint(cfg,{action:"run_stage",stage}),cfg.legacyKaggleBridgeEndpoint,stage);
for(const action of ["period_reorder","task_reschedule","drive_names_migrate","review_cache_seed","review_cache_status","review_share_draft_save"])
  assert.equal(routes.endpoint(cfg,{action}),cfg.legacyKaggleBridgeEndpoint,action);
assert.equal(routes.usesLegacy({action:"run_stage",stage:"cc"}),false);
assert.equal(routes.usesLegacy({action:"run_stage",stage:"cc",lang:"multi-audio"}),true);
assert.equal(routes.usesLegacy({action:"review_en_draft_save",payload_json:'{"save_request_id":"receipt"}'}),false);
assert.equal(routes.usesLegacy({action:"review_en_draft_save",payload_json:'{"segments":[]}'}),true);
assert.equal(routes.protocol("cloud-recovery"),9);
assert.equal(routes.protocol("9"),9);
assert.equal(routes.protocol("unexpected"),0);
const pending={submittedAt:Date.parse("2026-10-30T12:00:00Z"),previousRunId:"old"};
assert.equal(routes.dispatchReceipt(pending,{run_id:"new",status:"queued",updated_at:"2026-10-30T12:00:01Z"}),true);
assert.equal(routes.dispatchReceipt(pending,{run_id:"old",status:"done",updated_at:"2026-10-30T12:00:01Z"}),false);
assert.equal(routes.dispatchReceipt(pending,{run_id:"new",status:"done",updated_at:"2026-10-29T12:00:01Z"}),false);
assert.equal(routes.dispatchReceipt(pending,{status:"queued",updated_at:"2026-10-30T12:00:01Z"}),false);
// Old GAS wall-clock values and new UTC timestamps must identify the same
// dispatch on a phone/computer in any timezone. In UTC the stale 19:50 row
// used to look eight hours newer and falsely acknowledge an unsent finish.
const savedZone=process.env.TZ;
try{
  for(const zone of ["UTC","Asia/Taipei","America/Los_Angeles"]){
    process.env.TZ=zone;
    assert.equal(routes.statusTime("2026-10-30 20:00:01"),Date.parse("2026-10-30T12:00:01Z"),zone);
    assert.equal(routes.statusTime("2026-10-30T20:00:01+08:00"),Date.parse("2026-10-30T12:00:01Z"),zone);
    assert.equal(routes.dispatchReceipt(pending,{run_id:"new",status:"queued",updated_at:"2026-10-30 20:00:01"}),true,zone);
    assert.equal(routes.dispatchReceipt({...pending,previousRunId:""},{run_id:"old",status:"done",updated_at:"2026-10-30 19:50:01"}),false,zone);
  }
}finally{
  if(savedZone===undefined)delete process.env.TZ;else process.env.TZ=savedZone;
}
assert.equal(routes.dispatchReceipt(pending,{run_id:"new",status:"queued",updated_at:"invalid"}),false);
console.log("PASS: central saves, original machine actions, and timezone-independent dispatch receipts");

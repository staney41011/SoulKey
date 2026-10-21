const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname,"..");
const code = fs.readFileSync(path.join(root,"app-20260923-48.js"),"utf8");
const bridge = fs.readFileSync(path.resolve(root,"../bridge/apps-script/Code.gs"),"utf8");
function extract(source,name){
  const start=source.indexOf("function "+name+"(");
  assert(start>=0,name);
  const boundary=source.indexOf("\nfunction ",start+10);
  return source.slice(start,boundary<0?undefined:boundary);
}
const localStore={};
const calls=[];
const timers=[];
const results={};
const rows=[
  {id:63,en:"One",en_confirmed:true},
  {id:64,en:"Two",en_confirmed:true}
];
const status={textContent:""};
const mocks={
  selectedTaskId:"P258-L03",
  currentEnglishReview:rows,
  englishSavedPayloadSnapshot:()=>({
    segments:rows.map(r=>({id:r.id,en_text:r.en,en_confirmed:r.en_confirmed}))
  }),
  document:{getElementById:()=>status},
  submitBridgePost:payload=>{calls.push(payload);return true;},
  jsonpBridgeRequest:payload=>{calls.push(payload);return true;},
  markEnglishConfirmResult:(id,confirmed)=>{results[id]=confirmed;},
  localStorage:{
    setItem:(k,v)=>localStore[k]=v,
    removeItem:k=>delete localStore[k]
  },
  window:{
    setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length;},
    clearTimeout:()=>{}
  }
};
const codeDecls=[
 'let englishDraftSavePendingId=null;',
 'const englishDraftSaveQueuedIds=new Set();',
 'const englishReviewDirtyIds=new Set();',
 'let englishDraftSavePendingIds=new Set();',
 'let englishDraftSaveRequestId="";',
 'let englishDraftSaveWatchdog=null;',
 'let englishDraftSavedSnapshot=null;',
 'const ENGLISH_DRIVE_ACK_PREFIX="ack:";',
 'const ENGLISH_UNCONFIRMED_BACKUP_PREFIX="backup:";',
 extract(code,"finishEnglishReviewDraftSave"),
 extract(code,"saveEnglishReviewDraft")
];
vm.createContext(mocks);
vm.runInContext(codeDecls.join("\n"),mocks);
assert.equal(mocks.saveEnglishReviewDraft(63),true);
assert.equal(mocks.saveEnglishReviewDraft(64),true);
assert.equal(calls.filter(x=>x.action==="review_en_draft_save").length,1);
const request=JSON.parse(calls[0].payload_json);
assert.ok(request.save_request_id);
mocks.finishEnglishReviewDraftSave({
  task_id:"P258-L03",request_id:"different",ok:true
});
assert.equal(results[63],undefined,"A stale ACK cannot confirm edits");
mocks.finishEnglishReviewDraftSave({
  task_id:"P258-L03",request_id:request.save_request_id,
  ok:true,saved_at:"test"
});
assert.equal(results[63],true);
assert.equal(results[64],undefined,"Queued segment must not be falsely acknowledged");
const flush=timers.find(x=>x.delay===0);
assert.ok(flush);
flush.fn();
const posts=calls.filter(x=>x.action==="review_en_draft_save");
assert.equal(posts.length,2);
const request2=JSON.parse(posts[1].payload_json);
mocks.finishEnglishReviewDraftSave({
  task_id:"P258-L03",request_id:request2.save_request_id,
  ok:true,saved_at:"test"
});
assert.equal(results[64],true);
assert.equal(vm.runInContext("englishDraftSavePendingId",mocks),null);
assert.ok(localStore["ack:P258-L03"]);
assert.ok(bridge.includes('if (action === "review_en_draft_status")'));
assert.ok(bridge.includes('SOULKEY_EN_DRAFT_RECEIPT_'));
const backend=extract(bridge,"reviewEnglishDraftSave_");
assert.ok(backend.indexOf("writeTextFile_(")<backend.indexOf("SOULKEY_EN_DRAFT_RECEIPT_"));
assert.ok(backend.indexOf("SOULKEY_EN_DRAFT_RECEIPT_")<backend.indexOf("scheduleChineseCacheRepair_()"));
console.log("SOULKEY_ENGLISH_SAVE_QUEUE_AND_RECEIPT_OK");

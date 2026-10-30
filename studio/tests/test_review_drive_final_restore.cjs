"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const code=fs.readFileSync(path.join(__dirname,"../review-editor.js"),"utf8");
function section(start,end){
  const a=code.indexOf(start),b=code.indexOf(end,a+start.length);
  assert(a>=0&&b>a);return code.slice(a,b);
}
function setup(){
  const elements=new Map(),buttons=Array.from({length:4},()=>({classList:{toggle(){}},disabled:false}));
  const context={
    taskId:"P259-L01",payload:{},segments:Array.from({length:449},(_,id)=>({id,text:"ASR "+id})),
    dirty:false,englishAligned:null,englishDriveLoaded:false,englishBaseRequests:{},
    finishQueued:false,requestedStepNumber:0,currentStep:1,
    $:id=>{if(!elements.has(id))elements.set(id,{disabled:true,textContent:""});return elements.get(id);},
    document:{querySelectorAll:selector=>selector===".workflow-step"?buttons:[]},
    window:{scrollTo(){}},renderZh(){},renderEn(){},setStatus(message){context.lastStatus=message;},
    centralReviewRequest:async()=>({ok:true,edits:{}}),
  };
  vm.createContext(context);
  vm.runInContext(section("function maxAllowedStep(){","function filteredZhSegments(){"),context);
  vm.runInContext(section("async function restoreEnglishDraftEdits(","async function loadAlignedEnglish("),context);
  vm.runInContext(section("function englishGroups(){","function writeEnglishGroup("),context);
  vm.runInContext("function receive(data){"+section('  if(data.type==="review_data"){','  if((data.type==="review_share_draft_saved"')+"}",context);
  context.elements=elements;context.buttons=buttons;return context;
}
const finalRows=Array.from({length:59},(_,i)=>({id:1000+i,start:i*20,end:i*20+19,original:"人工中文段落 "+i,en:"Human final "+i,en_confirmed:true}));
const finalData={type:"review_data",ok:true,task_id:"P259-L01",kind:"en",finalized_at:"2026-10-29T12:00:00Z",segments:finalRows};
async function main(){
  const final=setup();final.receive(finalData);
  assert.equal(final.currentStep,3,"Existing English Final must unlock output without re-finalizing Chinese");
  assert.equal(final.buttons[1].disabled,false);assert.equal(final.buttons[2].disabled,false);
  assert.equal(final.elements.get("finalize-zh").disabled,true);
  assert.equal(final.elements.get("finalize-en").disabled,true);
  assert.equal(final.elements.get("finish-workflow").disabled,false);
  assert.equal(final.englishGroups().length,59,"English passages must not be joined onto 449 ASR IDs");
  final.englishGroups().forEach((row,i)=>{assert.equal(row.en_text,"Human final "+i);assert.equal(row.text,"人工中文段落 "+i);});
  assert.equal(final.segments.length,449);assert.equal(final.englishDriveLoaded,true);

  const draft=setup();draft.payload.en_finalized_at="stale-cache-final";
  draft.receive({...finalData,finalized_at:"",segments:[{id:20,en:"",source_en:"Original CC",original:"中文",ids:[4,5]}]});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(draft.currentStep,2);assert.equal(draft.payload.en_finalized_at,"");
  assert.equal(draft.elements.get("finalize-en").disabled,false);
  assert.equal(draft.elements.get("finish-workflow").disabled,true);
  assert.equal(draft.englishAligned[0].en_text,"","An intentionally empty edit must not resurrect the original CC");
  assert.deepEqual(Array.from(draft.englishGroups()[0].ids),[4,5]);

  const foreign=setup();foreign.receive({...finalData,task_id:"P259-L02"});
  assert.equal(foreign.englishAligned,null);assert.equal(foreign.payload.zh_finalized_at,undefined);

  const local=setup();local.dirty=true;local.englishAligned=[{id:7,en_text:"Unsaved human edit"}];
  local.receive(finalData);assert.equal(local.englishAligned[0].en_text,"Unsaved human edit");
  assert.equal(local.payload.en_finalized_at,undefined);assert.match(local.lastStatus,/尚未儲存/);

  const edits=setup();let resolveEdits;
  edits.centralReviewRequest=()=>new Promise(resolve=>{resolveEdits=resolve;});
  edits.receive({...finalData,finalized_at:"",segments:[{id:22,en:"Drive draft",original:"中文"}]});
  resolveEdits({ok:true,edits:{22:{en_text:"Saved human edit",request_id:"receipt-22"}}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(edits.englishAligned[0].en_text,"Saved human edit");assert.equal(edits.englishBaseRequests[22],"receipt-22");

  const late=setup();let resolveLate;
  late.centralReviewRequest=()=>new Promise(resolve=>{resolveLate=resolve;});
  late.receive({...finalData,finalized_at:"",segments:[{id:22,en:"Drive draft"}]});
  late.dirty=true;late.englishAligned[0].en_text="New unsaved edit";
  resolveLate({ok:true,edits:{22:{en_text:"Older saved draft"}}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(late.englishAligned[0].en_text,"New unsaved edit");

  const race=setup();race.payload.zh_finalized_at="verified";let resolveCache;
  race.fastReviewJson=()=>new Promise(resolve=>{resolveCache=resolve;});
  vm.runInContext(section("async function loadAlignedEnglish(","async function loadReview(){"),race);
  const cacheLoad=race.loadAlignedEnglish();race.receive(finalData);
  resolveCache({segments:[{id:0,en_text:"Old cache"}],en_finalized_at:"old"});await cacheLoad;
  assert.equal(race.englishAligned[0].en_text,"Human final 0","Late GitHub cache must not replace authenticated Drive Final");
  console.log("PASS: Drive Final unlocks steps, preserves 59/449 paragraph identities, draft receipts, local edits and authority over late cache");
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});

const fs=require("fs"),vm=require("vm"),assert=require("assert");
const path=require("path");
const src=fs.readFileSync(path.join(__dirname,"NativeStudio.gs"),"utf8");
const source={task:"P261-L01",period:261,folder:{},segments:[
  {id:0,start:0,end:60,text:"Fifty temples",source_hash:"en-hash"}]};
const draft={draft:{segments:[
  {id:0,start:0,end:60,text:"Cincuenta templos",source_hash:"en-hash"}]}};
let qaState="approved_risk_based",audioStale=false;
const ctx=vm.createContext({
  JSON,Number,String,Array,Object,Math,Date,Set,encodeURIComponent,
  SK_NEXT_LANGS:["es"],
  Logger:{log:()=>{}},
  readTasks_:()=>[{id:"P261-L01",period:261}],
  soulkeyNextSelectedCodes_:(_,kind)=>kind==="audio"?["en","es"]:["es"],
  soulkeyNextSources_:()=>[source],
  getSheetByName_:name=>({
    getDataRange:()=>({getDisplayValues:()=>name==="期數設定"?
      [["期數代碼","期數名稱","狀態"],["P260","第260期","啟用"],
       ["P261","第261期","啟用"]]:[["header"]]}),
    getLastRow:()=>1
  }),
  skNQDraft_:()=>draft,
  skNQTerms_:()=>[],
  soulkeyNextSha_:()=> "revision-accepted",
  readJsonFile_:(_folder,name)=>name.includes("sheets.qa.native.")?
      {state:qaState,revision_key:"revision-accepted",
       summary:{model_reviewed_pass:1,model_review_required:1,blocked_segment_ids:[]},
       decisions:{}}:null,
  skAudioPayload_:(_lesson,lang)=>({sha:"sha-"+lang,tag:"tag-"+lang}),
  skAudioReceipt_:(_lesson,lang)=>({
    status:"done",mp3_drive_id:"fake_drive_"+lang,
    source_sha256:audioStale?"OLD":"sha-"+lang,release_tag:"tag-"+lang
  })
});
new vm.Script(src,{filename:"NativeStudio.gs"}).runInContext(ctx);
assert.equal(ctx.soulkeyStudioCurrentPeriod_().period,261);
let v=ctx.soulkeyStudioNativeStatus_("P261-L01");
assert.equal(v.can_publish,true);
assert.equal(v.qa_done,1);
assert.equal(v.audio_done,2);
assert.equal(v.semantic_review_scope,"risk_based_not_full_semantic_review");
qaState="needs_review";
v=ctx.soulkeyStudioNativeStatus_("P261-L01");
assert.equal(v.can_publish,false);
assert.equal(v.qa_done,0);
qaState="approved_risk_based";audioStale=true;
v=ctx.soulkeyStudioNativeStatus_("P261-L01");
assert.equal(v.can_publish,false);
assert.equal(v.audio_done,0);
assert(v.languages.some(x=>x.audio_state==="stale_audio"));
assert.equal(ctx.soulkeyStudioNativeStatus_("P260-L01").ok,false);
console.log("PASS P261 backend refuses stale QA, revised audio and legacy tasks");

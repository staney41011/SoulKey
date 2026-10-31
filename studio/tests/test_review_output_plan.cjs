"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const source=fs.readFileSync(path.join(__dirname,"../review-editor.js"),"utf8");
const html=fs.readFileSync(path.join(__dirname,"../review.html"),"utf8");
const codes=[...html.matchAll(/data-output-lang="([a-z]+)"/g)].map(x=>x[1]);
assert.equal(codes.length,16);assert.equal((html.match(/data-output-enabled checked/g)||[]).length,16);
function section(a,b){const start=source.indexOf(a),end=source.indexOf(b,start+a.length);assert(start>=0&&end>start);return source.slice(start,end);}
function setup(){
  const rows=codes.map(code=>({dataset:{outputLang:code},toggle:{checked:true},label:{textContent:""},
    querySelector(selector){return selector==="[data-output-enabled]"?this.toggle:this.label;}}));
  const elements=new Map();const context={Map,Set,String,taskId:"P259-L01",payload:{en_finalized_at:"human-final"},
    outputPlanReady:false,outputPlanError:"",savedOutputPlan:new Map(),outputSelectionTouched:new Set(),
    LANG_NAMES:Object.fromEntries(codes.map(x=>[x,x])),LANG_NAMES_ZH:Object.fromEntries(codes.map(x=>[x,x])),
    document:{querySelectorAll:()=>rows},$:id=>{if(!elements.has(id))elements.set(id,{disabled:true,textContent:""});return elements.get(id);},
    setStatus(message){context.lastStatus=message;},centralReviewRequest:async fields=>{assert.equal(fields.action,"language_plan");assert.equal(fields.task_id,"P259-L01");return {ok:true,task_id:"P259-L01",plan:[]};},
    confirm(){throw Error("An empty or unread plan must not reach dispatch confirmation");},alert(message){context.lastAlert=message;},rows,elements};
  vm.createContext(context);
  vm.runInContext(section("function collectOutputPlan(){","function finishWorkflow(){"),context);
  vm.runInContext(section("function finishWorkflow(){",'window.addEventListener("message",event=>{'),context);
  return context;
}
async function main(){
  const fresh=setup();await fresh.loadOutputPlan();assert.equal(fresh.outputPlanReady,true);
  assert(fresh.rows.every(x=>x.toggle.checked));assert(fresh.collectOutputPlan().every(x=>x.audio_enabled));
  assert.equal(fresh.elements.get("finish-workflow").disabled,false);

  const saved=setup();saved.centralReviewRequest=async()=>({ok:true,task_id:"P259-L01",plan:[
    {language_code:"en",transcript_enabled:true,transcript_source:"human",audio_enabled:false,audio_source:"skip"},
    {language_code:"ja",transcript_enabled:"FALSE",transcript_source:"skip",audio_enabled:"FALSE",audio_source:"skip"},
    {language_code:"ko",transcript_enabled:"TRUE",transcript_source:"ai",audio_enabled:false,audio_source:"skip"}
  ]});await saved.loadOutputPlan();
  assert.equal(saved.rows.find(x=>x.dataset.outputLang==="ja").toggle.checked,false);
  assert.equal(saved.rows.find(x=>x.dataset.outputLang==="en").toggle.checked,false);
  const plan=saved.collectOutputPlan();
  assert.equal(plan.find(x=>x.language_code==="ja").transcript_enabled,false);
  assert.equal(plan.find(x=>x.language_code==="ko").transcript_enabled,true);
  assert.equal(plan.find(x=>x.language_code==="ko").audio_enabled,false,"An untouched text-only plan must not gain audio or lose its manuscript");
  assert.equal(plan.find(x=>x.language_code==="ko").audio_source,"skip");
  const korean=saved.rows.find(x=>x.dataset.outputLang==="ko");korean.toggle.checked=true;saved.outputSelectionTouched.add("ko");
  assert.equal(saved.collectOutputPlan().find(x=>x.language_code==="ko").audio_enabled,true);

  const race=setup();let resolve;
  race.centralReviewRequest=()=>new Promise(done=>{resolve=done;});const loading=race.loadOutputPlan();
  race.rows.find(x=>x.dataset.outputLang==="ja").toggle.checked=false;race.outputSelectionTouched.add("ja");
  resolve({ok:true,task_id:"P259-L01",plan:[{language_code:"ja",transcript_enabled:true,audio_enabled:true}]});await loading;
  assert.equal(race.rows.find(x=>x.dataset.outputLang==="ja").toggle.checked,false);
  assert.equal(race.collectOutputPlan().find(x=>x.language_code==="ja").audio_enabled,false);

  const failed=setup();failed.centralReviewRequest=async()=>{throw Error("read timeout");};await failed.loadOutputPlan();
  assert.equal(failed.outputPlanReady,false);assert.equal(failed.elements.get("finish-workflow").disabled,true);
  failed.finishWorkflow();assert.match(failed.lastStatus,/設定讀取失敗/);
  const foreign=setup();foreign.centralReviewRequest=async()=>({ok:true,task_id:"P259-L02",plan:[]});await foreign.loadOutputPlan();
  assert.equal(foreign.outputPlanReady,false);
  const empty=setup();await empty.loadOutputPlan();empty.rows.forEach(x=>{x.toggle.checked=false;empty.outputSelectionTouched.add(x.dataset.outputLang);});
  empty.finishWorkflow();assert.match(empty.lastAlert,/至少選擇/);
  console.log("PASS: saved output choices, default-all new plans, explicit opt-outs, text-only settings, late reads and empty/read-failed dispatch guards");
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});

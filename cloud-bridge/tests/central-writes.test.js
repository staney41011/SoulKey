"use strict";
const assert=require("node:assert/strict");
const {createCentralWrites}=require("../central-writes");
const sheets={
 "任務佇列":[["任務ID","期數","堂次"],[
  "P259-L01","259","第1堂","","https://youtu.be/YqpEMsRLzME",
  "","zh-TW","完成","完成","完成",...Array(10).fill(""),
  "SKC-000024","已排定","259","第1堂"
 ]],
 "語言任務設定":[["task_id","language_code","language_name","transcript_enabled","transcript_source","audio_enabled","audio_source","status","updated_at","note"]],
 "執行狀態":[["task_id","stage","status"],
 ["P259-L01","multi","done"],["P259-L01","tts","done"]]
};
const get=async(n,range)=>{
 const cells=sheets[n]||[];
 if(/^A1:A/.test(range))return cells.map(r=>r.slice(0,1));
 return cells.map(r=>[...r]);
};
const put=async(n,range,rows,append=false)=>{
 if(append){sheets[n].push(...rows.map(r=>[...r]));return;}
 const m=range.match(/^([A-Z])(\d+)(?::([A-Z])(\d+))?$/);
 if(!m)throw Error("unsupported range: "+range);
 const col=m[1].charCodeAt(0)-65,rowNo=Number(m[2])-1;
 const row=sheets[n][rowNo];
 if(!row)throw Error("missing row "+range);
 rows[0].forEach((value,index)=>row[col+index]=value);
};
async function run(){
 const api=createCentralWrites({get,put,now:()=>"2026-10-29T00:00:00Z"});
 await assert.rejects(()=>api.tasksUpsert({tasks_json:JSON.stringify([
  {id:"P259-L01",period:259,url:"https://youtu.be/ABCDEFGHIJK"}])}),
  /source_change_requires_explicit_reconciliation/);
 const created=await api.tasksUpsert({tasks_json:JSON.stringify([
  {id:"P260-L01",period:260,url:"https://youtu.be/abcdefghijk",note:"新一期"}])});
 assert.equal(created.ok,true);
 assert.equal(created.tasks[0].course_uid,"SKC-000025");
 assert.equal(sheets["任務佇列"].length,3);
 const again=await api.tasksUpsert({tasks_json:JSON.stringify([
  {id:"P260-L01",period:260,url:"https://youtu.be/abcdefghijk",note:"新一期"}])});
 assert.equal(again.ok,true);
 assert.equal(sheets["任務佇列"].length,3);
 const plan=await api.languagePlanSave({task_id:"P259-L01",plan_json:JSON.stringify([
  {language_code:"en",language_name:"English",transcript_enabled:true,transcript_source:"human",audio_enabled:true,audio_source:"tts"},
  {language_code:"th",language_name:"Thai",transcript_enabled:true,transcript_source:"ai",audio_enabled:true,audio_source:"tts"}
 ])});
 assert.equal(plan.ok,true);
 assert.equal(plan.plan.length,2);
 assert.equal(plan.translation_changed,true);
 assert.equal(plan.audio_changed,true);
 assert(sheets["執行狀態"].some(r=>r[1]==="multi"&&r[2]==="stale"));
 assert(sheets["執行狀態"].some(r=>r[1]==="tts"&&r[2]==="stale"));
 const againPlan=await api.languagePlanSave({task_id:"P259-L01",plan_json:JSON.stringify([
  {language_code:"en",language_name:"English",transcript_enabled:true,transcript_source:"human",audio_enabled:true,audio_source:"tts"},
  {language_code:"th",language_name:"Thai",transcript_enabled:true,transcript_source:"ai",audio_enabled:true,audio_source:"tts"}
 ])});
 assert.equal(againPlan.translation_changed,false);
 assert.equal(againPlan.audio_changed,false);
 console.log("PASS: preserved old source, idempotent new lessons, verified language plan and stale marking");
}
run().catch(e=>{console.error(e);process.exitCode=1});

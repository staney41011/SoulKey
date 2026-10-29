"use strict";
const assert=require("node:assert/strict");
const {createTranslationQueue,verifiedLanguages}=require("../translation-queue");
const REV="a".repeat(64),TASK="P259-L02";
const ids=["0","1"];
const qa=[["jobA",TASK,REV,"th","gemini",1,0,"passed","time"]];
const outputs=[
 [TASK,REV,"th","0","ดี","jobA","time"],
 [TASK,REV,"th","1","ครับ","jobA","time"],
 [TASK,REV,"es","0","hola","jobX","time"]
];
assert.equal(verifiedLanguages({task:TASK,revision:REV,languages:["th","es"],ids,outputs,receipts:qa}).has("th"),true);
assert.equal(verifiedLanguages({task:TASK,revision:REV,languages:["th","es"],ids,outputs,receipts:qa}).has("es"),false);
assert.equal(verifiedLanguages({task:TASK,revision:REV,languages:["th"],ids,outputs:[...outputs,outputs[0]],receipts:qa}).has("th"),false);
const sheets={
 "任務佇列":[["task_id"],[TASK]],"執行狀態":[["task_id","stage","status"]],
 "翻譯工作佇列":[["job_id","task_id","stage","langs","input_revision","status","created_at","claimed_at","finished_at","message"]],
 "多語翻譯結果":[["task_id","revision","language","id","text","job","time"],...outputs],
 "翻譯QA紀錄":[["job","task","revision","lang","model","count","repairs","status","time"],...qa]
};
const source={backup_id:REV,manuscript:{segments:[{id:0,start:0,end:1,text:"A"},{id:1,start:1,end:2,text:"B"}]}};
const get=async name=>sheets[name]||[];
const put=async(name,range,rows,append=false)=>{
 if(append){sheets[name].push(...rows);return;}
 const match=range.match(/^F(\d+):J\d+$/);
 if(!match)throw Error("bad range: "+range);
 const row=sheets[name][+match[1]-1];
 rows[0].forEach((x,i)=>row[i+5]=x);
};
const ensureTab=async(name,headers)=>{sheets[name]??=[headers];};
async function run(){
 const queue=createTranslationQueue({get,put,ensureTab,readFinal:async()=>source,taskExists:async()=>true});
 const x=await queue.enqueue({task_id:TASK,stage:"multi",langs:"th,es"});
 const claim=await queue.claim();
 assert.deepEqual(claim.job.qa_completed_languages,["th"]);
 const payload={job_id:x.job_id,language:"es",input_revision:REV,
  segments:JSON.stringify([{id:0,text:"hola"},{id:1,text:"amigo"}])};
 await queue.part(payload);
 await queue.quality({job_id:x.job_id,language:"es",input_revision:REV,status:"passed",
   unresolved:"0",model:"gemini-3.5-flash-lite",qa_batches:"1",repair_count:"0"});
 const finish=await queue.report({job_id:x.job_id,status:"done"});
 assert.equal(finish.status,"done");
 assert.equal(finish.segment_count,4);
 const saved=sheets["多語翻譯結果"].filter(r=>r[5]===x.job_id);
 assert.equal(saved.length,2,"approved older language is reused, not duplicated");
 const again=await queue.report({job_id:x.job_id,status:"done"});
 assert.equal(again.duplicate,true);
 console.log("PASS: verified cross-job language reuse, no false QA success");
}
run().catch(e=>{console.error(e);process.exitCode=1});

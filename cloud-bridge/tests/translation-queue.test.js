"use strict";
const assert=require("node:assert/strict");
const {createTranslationQueue,HEADER,OUT_HEADER}=require("../translation-queue");
const sheets={"任務佇列":[["task_id"],["P259-L02"]],"執行狀態":[["task_id","stage","status"]]};
const final={
 backup_id:"a".repeat(64),
 manuscript:{segments:[
  {id:0,start:0,end:1,text:"Peace be with you."},
  {id:2,start:1,end:2,text:"Welcome to this lecture."}
 ]}
};
const get=async(name)=>sheets[name]||[];
const ensureTab=async(name,headers)=>{sheets[name]??=[headers];};
const put=async(name,range,rows,append=false)=>{
 if(append){sheets[name].push(...rows);return}
 const m=range.match(/^F(\d+):J\d+$/);
 if(!m)throw Error("Unhandled range "+range);
 const row=sheets[name][Number(m[1])-1];
 if(!row)throw Error("Row missing");
 rows[0].forEach((x,i)=>row[i+5]=x);
};
(async()=>{
 const queue=createTranslationQueue({
  get,put,ensureTab,readFinal:async id=>id==="P259-L02"?final:null,
  taskExists:async id=>id==="P259-L02"
 });
 assert.throws(()=>queue.parseLanguages("en,th"),/invalid_translation_languages/);
 assert.throws(()=>queue.parseLanguages("th,evil"),/invalid_translation_languages/);
 assert.deepEqual(queue.parseLanguages("th,es,th"),["th","es"]);
 await assert.rejects(()=>queue.enqueue({task_id:"P259-L01",stage:"multi",langs:"th"}),/task_not_registered/);
 const x=await queue.enqueue({task_id:"P259-L02",stage:"multi",langs:"th,es"});
 assert.equal(x.ok,true);assert.equal(x.status,"queued");
 assert.equal(sheets["翻譯工作佇列"].length,2);
 const y=await queue.enqueue({task_id:"P259-L02",stage:"multi",langs:"th,es"});
 assert.equal(y.duplicate,true);
 assert.equal(sheets["翻譯工作佇列"].length,2);
 const claim=await queue.claim();
 assert.equal(claim.has_job,true);
 assert.deepEqual(claim.job.langs,["th","es"]);
 assert.equal(claim.job.segments[0].id,0);
 const record=sheets["翻譯工作佇列"][1];
 assert.equal(record[5],"running");assert.ok(record[6]);assert.ok(record[7]);
 const results={
  th:[{id:0,text:"สวัสดี"},{id:2,text:"ยินดีต้อนรับ"}],
  es:[{id:0,text:"La paz esté contigo."},{id:2,text:"Bienvenidos."}]
 };
 await assert.rejects(()=>queue.report({
  job_id:claim.job.id,status:"done",translations:{th:results.th}
 }),/incomplete_translation_es/);
 const receipt=await queue.report({job_id:claim.job.id,status:"done",translations:results});
 assert.equal(receipt.ok,true);assert.equal(receipt.segment_count,4);
 assert.equal(sheets["多語翻譯結果"].length,5);
 assert.equal(record[5],"done");assert.ok(record[8]);
 const again=await queue.report({job_id:claim.job.id,status:"done",translations:results});
 assert.equal(again.duplicate,true);
 assert.equal(sheets["多語翻譯結果"].length,5);
 assert.equal((await queue.claim()).has_job,false);
 assert.equal(sheets["執行狀態"].at(-1)[2],"done");
 console.log("PASS: validated multi queue, idempotent claims and SHA-bound segment readback");
})().catch(e=>{console.error(e);process.exitCode=1});

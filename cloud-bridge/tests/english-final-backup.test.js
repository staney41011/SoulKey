"use strict";
const assert=require("node:assert/strict");
const {createEnglishFinalBackup,normalizeEnglishFinal}=require("../english-final-backup");
let rows=[],tabs=0,writes=0;
const fn=createEnglishFinalBackup({
 ensureTab:async()=>{tabs++;},
 get:async()=>[["task_id","backup_id","part_index","part_count","payload_json_part","saved_at","sha256"],...rows],
 put:async(name,range,batch,append)=>{
  assert.equal(name,"英文定稿備存");
  assert.equal(append,true);
  writes++;
  rows.push(...batch);
 },
 now:()=>new Date("2026-10-29T00:00:00Z").toISOString()
});
(async()=>{
 const segments=Array.from({length:449},(_,id)=>({
  id,start:id*5,end:id*5+5,text:"Review segment "+id+"　"+("A full paragraph. ".repeat(30))
 }));
 const payload={task_id:"P259-L01",kind:"en",segments_json:JSON.stringify(segments),
  terms_json:JSON.stringify([{zh:"修道",en:"cultivation"}])};
 const first=await fn.save(payload);
 assert.equal(first.type,"review_saved");
 assert.equal(first.ok,false,"do not claim formal Drive final");
 assert.equal(first.backup_saved,true);
 assert.equal(first.pending_drive,true);
 assert.equal(first.segment_count,449);
 assert(rows.length>1,"large complete final is split into chunks");
 assert(rows.every(row=>row[4].length<=28000));
 const before=rows.length;
 const again=await fn.save(payload);
 assert.equal(again.backup_id,first.backup_id);
 assert.equal(rows.length,before,"idempotent re-submission must not duplicate rows");
 assert.equal(writes,1);
 const reconstructed=rows.sort((a,b)=>Number(a[2])-Number(b[2]))
  .map(x=>x[4]).join("");
 assert.equal(JSON.parse(reconstructed).segments.length,449);
 assert.throws(()=>normalizeEnglishFinal({...payload,kind:"zh"}),/invalid_english_final_task/);
 assert.throws(()=>normalizeEnglishFinal({...payload,segments_json:"[]"}),/invalid_segment_count/);
 assert.throws(()=>normalizeEnglishFinal({...payload,segments_json:JSON.stringify([segments[0],segments[0]])}),/invalid_english_segment/);
 console.log("PASS: full 449-segment English final has verifiable, idempotent Sheet backup without false Drive completion");
})().catch(e=>{console.error(e);process.exitCode=1});

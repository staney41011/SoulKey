"use strict";
const assert=require("node:assert/strict");
const {createTranslationQueue}=require("../translation-queue");
const sheets={
  "任務佇列":[["task_id"],["P259-L01"]],
  "執行狀態":[["task_id","stage","status"]]
};
const source={backup_id:"b".repeat(64),manuscript:{segments:[
  {id:0,text:"Be kind.",start:0,end:2},
  {id:1,text:"Be patient.",start:2,end:4},
  {id:2,text:"Help others.",start:4,end:6}
]}};
const get=async name=>sheets[name]||[];
const ensureTab=async(name,header)=>{sheets[name]??=[header];};
const put=async(name,range,rows,append=false)=>{
  if(append){sheets[name].push(...rows);return;}
  const at=range.match(/^F(\d+):J\d+$/);
  if(!at)throw Error("unexpected range "+range);
  const row=sheets[name][Number(at[1])-1];
  rows[0].forEach((value,i)=>row[5+i]=value);
};
async function run(){
  const queue=createTranslationQueue({get,put,ensureTab,
    readFinal:async()=>source,taskExists:async()=>true});
  const newJob=await queue.enqueue({task_id:"P259-L01",stage:"multi",langs:"th,es"});
  const claimed=await queue.claim();
  assert.equal(claimed.job.id,newJob.job_id);
  assert.equal(claimed.job.chunked_upload,true);
  const base={job_id:newJob.job_id,input_revision:source.backup_id};
  await assert.rejects(()=>queue.part({...base,language:"en",
    segments:JSON.stringify([{id:0,text:"test"}])}),/translation_language_not_requested/);
  await assert.rejects(()=>queue.part({...base,input_revision:"incorrect",language:"th",
    segments:JSON.stringify([{id:0,text:"test"}])}),/translation_revision_mismatch/);
  await queue.part({...base,language:"th",segments:JSON.stringify([
    {id:0,text:"เมตตา"},{id:1,text:"อดทน"}])});
  const duplicate=await queue.part({...base,language:"th",segments:JSON.stringify([
    {id:0,text:"เมตตา"},{id:1,text:"อดทน"}])});
  assert.equal(duplicate.added_count,0);
  await assert.rejects(()=>queue.part({...base,language:"th",
    segments:JSON.stringify([{id:0,text:"誤寫"}])}),/translation_chunk_conflict/);
  await assert.rejects(()=>queue.report({job_id:newJob.job_id,status:"done"}),
    /incomplete_translation_th/);
  await queue.part({...base,language:"th",segments:JSON.stringify([{id:2,text:"幫助"}])});
  await queue.part({...base,language:"es",segments:JSON.stringify([
    {id:0,text:"Sé amable"},{id:1,text:"Sé paciente"},{id:2,text:"Ayuda"}])});
  await assert.rejects(()=>queue.report({job_id:newJob.job_id,status:"done"}),
    /missing_semantic_quality_receipt_th/);
  for(const lang of ["th","es"]){
    const qa=await queue.quality({job_id:newJob.job_id,language:lang,
      input_revision:source.backup_id,model:"gemini-3.5-flash-lite",
      status:"passed",unresolved:"0",qa_batches:"1",repair_count:"0"});
    assert.equal(qa.qa_passed,true);
  }
  const done=await queue.report({job_id:newJob.job_id,status:"done"});
  assert.equal(done.status,"done");
  assert.equal(done.segment_count,6);
  assert.equal(sheets["多語翻譯結果"].length,7);
  const again=await queue.report({job_id:newJob.job_id,status:"done"});
  assert.equal(again.duplicate,true);
  assert.equal((await queue.claim()).has_job,false);
  console.log("PASS: bounded translation chunks, source revisions, conflicts, full verification");
}
run().catch(e=>{console.error(e);process.exitCode=1});

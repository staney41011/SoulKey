"use strict";
const {randomUUID}=require("node:crypto");
const TAB="翻譯工作佇列",OUTPUT="多語翻譯結果";
const HEADER=["job_id","task_id","stage","langs","input_revision","status","created_at","claimed_at","finished_at","message"];
const OUT_HEADER=["task_id","input_revision","language_code","segment_id","translated_text","job_id","saved_at"];
const LANG=new Set(["th","es","id","vi","km","hi","ta","ja","ko","bn","ne","lo","my","it","pt"]);
const JOB=/^[0-9a-f-]{36}$/;
const TASK=/^P\d+-L\d{2}(?:-R\d+)?$/;
const now=()=>new Date().toISOString();
const stageRow=(id,stage,state,runId,progress,message,revision)=>[
 id,stage,state,runId,String(progress),message,"",
 state==="done"||state==="error"?now():"",now(),"","",revision||"",revision||""
];
function parseLanguages(raw){
 const list=String(raw||"").split(",").map(x=>x.trim().toLowerCase()).filter(Boolean);
 const uniq=[...new Set(list)];
 if(!uniq.length||uniq.length>15||uniq.some(x=>!LANG.has(x)))
  throw Error("invalid_translation_languages");
 return uniq;
}
function createTranslationQueue({get,put,ensureTab,readFinal,taskExists,utcNow=now}){
 async function init(){
  await ensureTab(TAB,HEADER);await ensureTab(OUTPUT,OUT_HEADER);
 }
 async function findRows(){await init();return (await get(TAB,"A1:J5000")).slice(1);}
 async function appendStatus(id,stage,state,jobId,progress,message,revision){
  await put("執行狀態","A:M",[stageRow(id,stage,state,jobId,progress,message,revision)],true);
 }
 async function enqueue(p){
  const id=String(p.task_id||"").trim(),stage=String(p.stage||"");
  if(!TASK.test(id)||stage!=="multi")throw Error("unsupported_run_stage");
  if(!(await taskExists(id)))throw Error("task_not_registered");
  const final=await readFinal(id);
  if(!final?.backup_id||!final?.manuscript?.segments?.length)
   throw Error("english_final_not_verified");
  const languages=parseLanguages(p.langs);
  const revision=final.backup_id;
  const rows=await findRows();
  const existing=rows.find(r=>r[1]===id&&r[2]===stage&&
    r[3]===languages.join(",")&&r[4]===revision&&
    ["queued","running","done"].includes(String(r[5])));
  if(existing)return {ok:true,duplicate:true,task_id:id,stage,job_id:existing[0],
    status:existing[5],queue_mode:"scheduled-github-actions",
    message:"同一版本翻譯已在中央佇列，沒有重複派工"};
  const jobId=randomUUID(),at=utcNow();
  await put(TAB,"A:J",[[jobId,id,stage,languages.join(","),revision,
   "queued",at,"","","等待 GitHub Actions 定期領取"]],true);
  const after=await findRows();
  if(!after.some(r=>r[0]===jobId&&r[5]==="queued"))
   throw Error("translation_queue_readback_failed");
  await appendStatus(id,stage,"queued",jobId,0,
   "已寫入中央翻譯佇列；GitHub Worker 尚未開始執行",revision);
  return {ok:true,task_id:id,stage,job_id:jobId,
    queue_mode:"scheduled-github-actions",status:"queued",
    message:"工作已寫入中央佇列，等待 GitHub Actions Worker 領取"};
 }
 async function claim(){
  const rows=await findRows();
  const index=rows.findIndex(r=>r[5]==="queued");
  if(index<0)return {ok:true,has_job:false};
  const row=rows[index],id=row[0],task=row[1],revision=row[4];
  const final=await readFinal(task);
  if(!final||final.backup_id!==revision){
   await put(TAB,"F"+(index+2)+":J"+(index+2),
    [["error",row[6]||"",row[7]||"",utcNow(),"英文正式定稿版本已變更，停止舊版本翻譯"]]);
   await appendStatus(task,"multi","error",id,0,
     "英文正式定稿版本已變更，請重新送出翻譯",revision);
   return {ok:true,has_job:false,invalidated:true};
  }
  await put(TAB,"F"+(index+2)+":J"+(index+2),
   [["running",row[6]||"",utcNow(),"","GitHub Worker 已領取"]]);
  await appendStatus(task,"multi","running",id,1,
   "GitHub Worker 開始翻譯",revision);
  return {ok:true,has_job:true,job:{
    id,task_id:task,stage:"multi",langs:parseLanguages(row[3]),
    revision,segments:final.manuscript.segments.map(x=>({
      id:x.id,start:x.start,end:x.end,text:x.text
    }))
  }};
 }
 async function part(p){
  const id=String(p.job_id||""),code=String(p.language||"").toLowerCase();
  if(!JOB.test(id))throw Error("invalid_job_id");
  const rows=await findRows(),job=rows.find(r=>r[0]===id);
  if(!job||job[5]!=="running")throw Error("job_not_running");
  if(!parseLanguages(job[3]).includes(code))throw Error("translation_language_not_requested");
  const task=job[1],revision=job[4];
  if(String(p.input_revision||"")!==revision)throw Error("translation_revision_mismatch");
  const final=await readFinal(task);
  if(!final||final.backup_id!==revision)throw Error("final_changed_during_translation");
  const batch=typeof p.segments==="string"?JSON.parse(p.segments):p.segments;
  if(!Array.isArray(batch)||!batch.length||batch.length>20)
    throw Error("invalid_translation_chunk");
  const validIds=new Set(final.manuscript.segments.map(x=>String(x.id)));
  const unique=new Set(),at=utcNow();
  const pending=[];
  for(const item of batch){
    const segId=String(item?.id??""),value=String(item?.text||"").trim();
    if(!validIds.has(segId)||unique.has(segId)||!value||value.length>16000)
      throw Error("invalid_translated_segment_"+code);
    unique.add(segId);
    pending.push([task,revision,code,segId,value,id,at]);
  }
  const current=(await get(OUTPUT,"A1:G50000")).slice(1);
  const existing=new Map(current.filter(r=>r[5]===id&&r[1]===revision&&r[2]===code)
    .map(r=>[String(r[3]),String(r[4]||"")]));
  for(const row of pending){
    if(existing.has(row[3])&&existing.get(row[3])!==row[4])
      throw Error("translation_chunk_conflict_"+code+"_"+row[3]);
  }
  const missing=pending.filter(r=>!existing.has(r[3]));
  if(missing.length)await put(OUTPUT,"A:G",missing,true);
  const saved=(await get(OUTPUT,"A1:G50000")).slice(1);
  for(const row of pending){
    if(!saved.some(r=>r[5]===id&&r[1]===revision&&r[2]===code&&
      String(r[3])===row[3]&&String(r[4])===row[4]))
      throw Error("translation_chunk_readback_failed_"+code+"_"+row[3]);
  }
  return {ok:true,task_id:task,job_id:id,language:code,
    saved_count:pending.length,added_count:missing.length};
 }
 async function report(p){
  const id=String(p.job_id||"");
  if(!JOB.test(id))throw Error("invalid_job_id");
  const rows=await findRows();
  const idx=rows.findIndex(r=>r[0]===id);
  if(idx<0)throw Error("job_not_found");
  const job=rows[idx],task=job[1],revision=job[4],langs=parseLanguages(job[3]);
  if(job[5]==="done")return {ok:true,duplicate:true};
  if(job[5]!=="running")throw Error("job_not_claimed");
  const final=await readFinal(task);
  if(!final||final.backup_id!==revision)throw Error("final_changed_during_translation");
  const status=String(p.status||"");
  if(status==="error"){
   const message=String(p.message||"worker_failed").slice(0,300);
   await put(TAB,"F"+(idx+2)+":J"+(idx+2),
    [["error",job[6]||"",job[7]||"",utcNow(),message]]);
   await appendStatus(task,"multi","error",id,0,message,revision);
   return {ok:true,task_id:task,status:"error"};
  }
  if(status!=="done")throw Error("invalid_worker_status");
  const ids=final.manuscript.segments.map(x=>String(x.id));
  const results=[];
  if(p.translations){
    const translated=typeof p.translations==="string"?
      JSON.parse(p.translations):p.translations;
    if(!translated||typeof translated!=="object"||Array.isArray(translated))
      throw Error("invalid_translation_payload");
    for(const code of langs){
      const data=translated[code];
      if(!Array.isArray(data)||data.length!==ids.length)
        throw Error("incomplete_translation_"+code);
      const seen=new Map();
      for(const row of data){
        const rid=String(row?.id??""),val=String(row?.text||"").trim();
        if(!ids.includes(rid)||seen.has(rid)||!val||val.length>16000)
          throw Error("invalid_translated_segment_"+code);
        seen.set(rid,val);
      }
      for(const segId of ids){
        if(!seen.has(segId))throw Error("missing_translated_segment_"+code);
        results.push([task,revision,code,segId,seen.get(segId),id,utcNow()]);
      }
    }
  }else{
    // Workers upload bounded, readback-verified chunks instead of a giant HTTP body.
    const saved=(await get(OUTPUT,"A1:G50000")).slice(1)
      .filter(r=>r[0]===task&&r[1]===revision&&r[5]===id);
    for(const code of langs){
      const rows=saved.filter(r=>r[2]===code);
      const seen=new Map();
      for(const row of rows){
        const sid=String(row[3]),value=String(row[4]||"").trim();
        if(!ids.includes(sid)||!value||seen.has(sid))
          throw Error("invalid_saved_translation_"+code+"_"+sid);
        seen.set(sid,value);
      }
      if(seen.size!==ids.length)throw Error("incomplete_translation_"+code);
      for(const sid of ids)
        results.push([task,revision,code,sid,seen.get(sid),id,utcNow()]);
    }
  }
  const current=(await get(OUTPUT,"A1:G50000")).slice(1);
  const known=new Set(current.filter(r=>r[5]===id).map(r=>r[2]+":"+r[3]));
  const missing=results.filter(r=>!known.has(r[2]+":"+r[3]));
  if(missing.length)await put(OUTPUT,"A:G",missing,true);
  const saved=(await get(OUTPUT,"A1:G50000")).slice(1);
  const verified=new Set(saved.filter(r=>r[5]===id&&r[1]===revision)
   .map(r=>r[2]+":"+r[3]));
  if(results.some(r=>!verified.has(r[2]+":"+r[3])))
   throw Error("translation_results_readback_failed");
  await put(TAB,"F"+(idx+2)+":J"+(idx+2),
   [["done",job[6]||"",job[7]||"",utcNow(),"多語翻譯 "+langs.join(",")+" 完成"]]);
  await appendStatus(task,"multi","done",id,100,
   "中央 Google Sheet 多語翻譯已核對 "+results.length+" 段",revision);
  return {ok:true,task_id:task,status:"done",
   language_count:langs.length,segment_count:results.length};
 }
 return {enqueue,claim,part,report,parseLanguages};
}
module.exports={createTranslationQueue,parseLanguages,HEADER,OUT_HEADER};

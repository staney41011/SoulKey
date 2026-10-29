"use strict";
const {randomUUID}=require("node:crypto");
const TAB="翻譯工作佇列",OUTPUT="多語翻譯結果",QA_TAB="翻譯QA紀錄";
const QA_HEADER=["job_id","task_id","input_revision","language_code","model","qa_batches","repair_count","status","verified_at"];
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
// A previous job's language is reusable ONLY after it has a matching QA
// receipt and a complete, unique set of source-bound segment IDs.
function verifiedLanguages({task,revision,languages,ids,outputs,receipts}){
 const verified=new Map();
 const allowed=new Set(ids.map(String));
 for(const code of languages){
  const proof=receipts.filter(r=>r[1]===task && r[2]===revision &&
    r[3]===code && r[7]==="passed").reverse();
  for(const item of proof){
   const rows=outputs.filter(r=>r[0]===task && r[1]===revision &&
     r[2]===code && r[5]===item[0]);
   const seen=new Map();
   let valid=true;
   for(const row of rows){
    const sid=String(row[3]),text=String(row[4]||"").trim();
    if(!allowed.has(sid)||seen.has(sid)||!text){valid=false;break;}
    seen.set(sid,text);
   }
   if(valid && seen.size===allowed.size){
    verified.set(code,{job_id:item[0],segments:ids.map(id=>({
      id:String(id),text:seen.get(String(id))
    }))});
    break;
   }
  }
 }
 return verified;
}

function createTranslationQueue({get,put,ensureTab,readFinal,taskExists,readGlossary=async()=>[],utcNow=now}){
 async function init(){
  await ensureTab(TAB,HEADER);await ensureTab(OUTPUT,OUT_HEADER);await ensureTab(QA_TAB,QA_HEADER);
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
  // Resume only when every previously saved chunk has a passing QA receipt.
  // Otherwise start a separate job and retain the prior partial rows as
  // evidence; never overwrite unverified translations from a failed attempt.
  const failed=rows.filter(r=>r[1]===id&&r[2]===stage&&
    r[3]===languages.join(",")&&r[4]===revision&&r[5]==="error").at(-1);
  if(failed){
    const previouslyWritten=(await get(OUTPUT,"A1:G50000")).slice(1)
      .filter(r=>r[5]===failed[0]&&r[1]===revision);
    const receipts=(await get(QA_TAB,"A1:I5000")).slice(1)
      .filter(r=>r[0]===failed[0]&&r[2]===revision&&r[7]==="passed");
    const approved=new Set(receipts.map(r=>String(r[3])));
    const unsafePartial=previouslyWritten.some(r=>!approved.has(String(r[2])));
    if(!unsafePartial){
      const failedIndex=rows.indexOf(failed);
      await put(TAB,"F"+(failedIndex+2)+":J"+(failedIndex+2),
        [["queued",failed[6]||utcNow(),"","","原工作安全恢復；保留已通過 QA 的語言"]]);
      await appendStatus(id,stage,"queued",failed[0],0,
        "原工作已安全重新排隊，來源與 QA 完整性保留",revision);
      return {ok:true,resumed:true,task_id:id,stage,job_id:failed[0],
        status:"queued",queue_mode:"scheduled-github-actions"};
    }
  }
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
  let index=rows.findIndex(r=>r[5]==="queued");
  if(index<0){
   // Legacy-style bounded automatic recovery. Do not reopen a completed job
   // or run an unlimited retry loop when external API daily quota is exhausted.
   for(let i=rows.length-1;i>=0;i--){
    const failed=rows[i];
    if(failed[5]!=="error")continue;
    const key=r=>r[1]===failed[1]&&r[3]===failed[3]&&r[4]===failed[4];
    const matching=rows.filter(key);
    if(matching.length>=4 || matching.some(r=>r[5]==="done"||
      r[5]==="queued"||r[5]==="running"))continue;
    if(matching.at(-1)!==failed)continue;
    const at=Date.parse(String(failed[8]||failed[6]||""));
    const isQuota=/429|quota|rate.limit/i.test(String(failed[9]||""));
    const cooldown=isQuota?6*60*60*1000:45*60*1000;
    if(!Number.isFinite(at)||Date.now()-at<cooldown)continue;
    const newId=randomUUID(),created=utcNow();
    await put(TAB,"A:J",[[newId,failed[1],"multi",failed[3],failed[4],
      "queued",created,"","","自動恢復失敗翻譯，僅重做未通過 QA 的語言"]],true);
    await appendStatus(failed[1],"multi","queued",newId,0,
      "已建立來源相同的安全恢復工作，保留歷史 QA 成果",failed[4]);
    return {ok:true,has_job:false,recovery_queued:true,job_id:newId};
   }
   return {ok:true,has_job:false};
  }
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
  const segments=final.manuscript.segments.map(x=>({
    id:x.id,start:x.start,end:x.end,text:x.text
  }));
  const glossaryRows=(await readGlossary())||[];
  const requested=parseLanguages(row[3]);
  // Legacy "專有名詞庫" column positions are authoritative; only include
  // English terms actually present in the approved source manuscript.
  const indexes={th:4,es:5,id:6,vi:7,hi:10,ta:11,ja:12,ko:13,km:14,bn:15,ne:16,lo:17,my:18,it:19,pt:20};
  const sourceText=segments.map(x=>String(x.text||"")).join(" ").toLocaleLowerCase();
  const glossary=glossaryRows.slice(0,500).filter(row=>{
    const en=String(row[3]||"").trim();
    return en.length>=2 && sourceText.includes(en.toLocaleLowerCase());
  }).slice(0,120).map(row=>{
    const fields=["source="+String(row[3]||"")];
    for(const lang of requested){
      const value=String(row[indexes[lang]]||"").trim();
      if(value)fields.push(lang+"="+value);
    }
    if(["true","1","yes","y","是"].includes(String(row[8]||"").toLowerCase()))
      fields.push("LOCKED");
    return "- "+fields.join(" | ");
  }).join("\n").slice(0,12000);
  const [allQa,allOutput]=await Promise.all([
   get(QA_TAB,"A1:I5000"),get(OUTPUT,"A1:G50000")
  ]);
  const approved=verifiedLanguages({
   task,revision,languages:requested,ids:segments.map(x=>String(x.id)),
   outputs:allOutput.slice(1),receipts:allQa.slice(1)
  });
  const completedLanguages=[...approved.keys()];
  return {ok:true,has_job:true,job:{
    id,task_id:task,stage:"multi",chunked_upload:true,
    qa_required:true,qa_completed_languages:completedLanguages,
    langs:requested,revision,glossary,segments
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
  // Whole-language idempotent upload replaces dozens of 8-row uploads:
  // each old upload performed four quota-consuming Sheet reads.
  if(!Array.isArray(batch)||!batch.length||batch.length>2000)
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
 async function quality(p){
  const id=String(p.job_id||""),lang=String(p.language||"");
  if(!JOB.test(id))throw Error("invalid_job_id");
  const rows=await findRows(),job=rows.find(r=>r[0]===id);
  if(!job||job[5]!=="running")throw Error("job_not_running");
  if(!parseLanguages(job[3]).includes(lang))throw Error("quality_language_not_requested");
  const revision=String(p.input_revision||"");
  if(revision!==job[4])throw Error("quality_revision_mismatch");
  const final=await readFinal(job[1]);
  if(!final||final.backup_id!==revision)throw Error("final_changed_during_quality");
  const ids=new Set(final.manuscript.segments.map(s=>String(s.id)));
  const saved=(await get(OUTPUT,"A1:G50000")).slice(1)
    .filter(r=>r[5]===id&&r[1]===revision&&r[2]===lang);
  const unique=new Map();
  for(const row of saved){
    const sid=String(row[3]);
    if(!ids.has(sid)||unique.has(sid)||!String(row[4]||"").trim())
      throw Error("quality_invalid_or_duplicate_saved_segments");
    unique.set(sid,row[4]);
  }
  if(unique.size!==ids.size)throw Error("quality_translation_not_complete");
  if(String(p.status)!=="passed"||String(p.unresolved||"0")!=="0")
    throw Error("quality_has_unresolved_failures");
  const batches=Number(p.qa_batches),repairs=Number(p.repair_count||0);
  const model=String(p.model||"");
  if(!Number.isSafeInteger(batches)||batches<1||
     !Number.isSafeInteger(repairs)||repairs<0||
     !/^gemini-[a-z0-9.\-]{2,80}$/.test(model))
    throw Error("invalid_quality_receipt");
  const prior=(await get(QA_TAB,"A1:I5000")).slice(1)
    .find(r=>r[0]===id&&r[2]===revision&&r[3]===lang&&r[7]==="passed");
  if(prior){
    if(prior[4]!==model)throw Error("quality_model_conflict");
    return {ok:true,duplicate:true,job_id:id,language:lang};
  }
  await put(QA_TAB,"A:I",[[id,job[1],revision,lang,model,
    String(batches),String(repairs),"passed",utcNow()]],true);
  const check=(await get(QA_TAB,"A1:I5000")).slice(1)
    .some(r=>r[0]===id&&r[2]===revision&&r[3]===lang&&r[7]==="passed");
  if(!check)throw Error("quality_receipt_not_persisted");
  return {ok:true,job_id:id,language:lang,qa_passed:true};
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
  // Require fully QA-verified inputs. Reuse complete past-job languages rather
  // than re-translating after one other language hit Gemini/Sheets quota.
  const ids=final.manuscript.segments.map(x=>String(x.id));
  const [receipts,outputs]=await Promise.all([
    get(QA_TAB,"A1:I5000"),get(OUTPUT,"A1:G50000")
  ]);
  const approved=verifiedLanguages({
    task,revision,languages:langs,ids,
    outputs:outputs.slice(1),receipts:receipts.slice(1)
  });
  for(const lang of langs)
    if(!approved.has(lang))throw Error("missing_semantic_quality_receipt_"+lang);
  const results=[];
  for(const code of langs){
    const source=approved.get(code);
    for(const part of source.segments)
      results.push([task,revision,code,part.id,part.text,source.job_id,utcNow()]);
  }
  await put(TAB,"F"+(idx+2)+":J"+(idx+2),
   [["done",job[6]||"",job[7]||"",utcNow(),"多語翻譯 "+langs.join(",")+" 完成"]]);
  await appendStatus(task,"multi","done",id,100,
   "中央 Google Sheet 多語翻譯已核對 "+results.length+" 段",revision);
  return {ok:true,task_id:task,status:"done",
   language_count:langs.length,segment_count:results.length};
 }
 async function diagnostics(){
  const rows=await findRows();
  const queued=rows.filter(r=>r[5]==="queued");
  const running=rows.filter(r=>r[5]==="running");
  const finished=rows.filter(r=>r[5]==="done"||r[5]==="error");
  const lastClaim=rows.filter(r=>r[7]).map(r=>String(r[7])).sort().at(-1)||"";
  const stalled=queued.filter(r=>{
    const t=Date.parse(String(r[6]||""));
    return Number.isFinite(t)&&Date.now()-t>15*60*1000;
  });
  return {
    queued_count:queued.length,running_count:running.length,
    overdue_unclaimed_count:stalled.length,
    oldest_queued_at:queued.map(r=>String(r[6]||"")).filter(Boolean).sort()[0]||"",
    last_claimed_at:lastClaim,
    last_finished_at:finished.map(r=>String(r[8]||"")).filter(Boolean).sort().at(-1)||""
  };
 }
 return {enqueue,claim,part,quality,report,parseLanguages,ready:init,diagnostics};
}
module.exports={createTranslationQueue,parseLanguages,HEADER,OUT_HEADER,verifiedLanguages};

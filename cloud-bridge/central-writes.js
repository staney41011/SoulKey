"use strict";
// Restore conservative, source-bound central writes lost in the Cloud Run migration.
// Never overwrite a different YouTube video ID or any existing lesson output.
const {videoId}=require("./youtube-cc-queue");
const TASK=/^P(\d{3,4})-L(\d{2})$/;
const LANG=new Set(["en","th","es","id","vi","sd","km","hi","ta","ja","ko","bn","ne","lo","my","it","pt"]);
const TRUE=x=>x===true||String(x).toUpperCase()==="TRUE";
const canonical=(id)=>{const m=String(id||"").match(TASK);if(!m)throw Error("invalid_task_id");return m;};
function parseJson(value){
 const x=typeof value==="string"?JSON.parse(value):value;
 if(!Array.isArray(x)||x.length===0||x.length>20)throw Error("invalid_json_array");
 return x;
}
function createCentralWrites({get,put,now=()=>new Date().toISOString()}){
 async function tasksUpsert(p){
  const payload=parseJson(p.tasks_json);
  const current=await get("任務佇列","A1:Z5000");
  const existing=new Map(current.slice(1).map((r,i)=>[String(r[0]||""),{r,row:i+2}]));
  const seen=new Set(),updates=[],newRows=[],result=[];
  let uid=Math.max(0,...current.slice(1).map(r=>Number(String(r[20]||"").match(/^SKC-(\d+)$/)?.[1]||0)));
  for(const item of payload){
   const id=String(item?.id||""),m=canonical(id);
   const period=Number(item.period),lesson="第"+Number(m[2])+"堂";
   if(!Number.isSafeInteger(period)||period!==Number(m[1])||
      Number(m[2])<1||Number(m[2])>99||seen.has(id))
     throw Error("invalid_or_duplicate_task");
   seen.add(id);
   const url=String(item.url||"").trim();
   if(!videoId(url))throw Error("invalid_youtube_url_"+id);
   const note=String(item.note||"").slice(0,1000);
   const record=existing.get(id);
   if(record){
    const oldVideo=videoId(record.r[4]||"");
    if(oldVideo && oldVideo!==videoId(url))
      throw Error("source_change_requires_explicit_reconciliation_"+id);
    updates.push({row:record.row,url,note,id});
    result.push({id,period,lesson,course_uid:String(record.r[20]||"")});
   }else{
    // Refuse to silently overwrite an existing scheduled lesson's position.
    const collides=current.slice(1).some(r=>
      Number(r[1])===period&&String(r[2]||"")===lesson);
    if(collides||newRows.some(r=>Number(r[1])===period&&r[2]===lesson))
      throw Error("lesson_position_already_taken_"+id);
    const row=Array(26).fill("");
    row[0]=id;row[1]=String(period);row[2]=lesson;row[4]=url;
    row[6]="zh-TW";row[7]="未開始";row[8]="未開始";row[9]="未開始";
    row[17]="0%";row[18]=now();row[19]=note;
    row[20]="SKC-"+String(++uid).padStart(6,"0");
    row[21]="已排定";row[22]=String(period);row[23]=lesson;
    newRows.push(row);
    result.push({id,period,lesson,course_uid:row[20]});
   }
  }
  // All validation above runs before the first write.
  if(newRows.length)await put("任務佇列","A:Z",newRows,true);
  for(const u of updates){
   await put("任務佇列","E"+u.row,[[u.url]]);
   await put("任務佇列","T"+u.row,[[u.note]]);
  }
  const saved=(await get("任務佇列","A1:Z5000")).slice(1);
  for(const t of result){
   const rows=saved.filter(r=>String(r[0])===t.id);
   if(rows.length!==1||!videoId(rows[0][4]))
     throw Error("task_upsert_readback_failed_"+t.id);
   const submitted=payload.find(x=>x.id===t.id);
   if(videoId(rows[0][4])!==videoId(submitted.url))
     throw Error("task_source_readback_mismatch_"+t.id);
  }
  return {ok:true,tasks:result,message:"中央課程資料已回讀驗證；原有課程成果未修改"};
 }
 async function languagePlanSave(p){
  const id=String(p.task_id||"");
  if(!/^P\d{3,4}-L\d{2}(?:-R\d+)?$/.test(id))throw Error("invalid_task_id");
  const tasks=(await get("任務佇列","A1:A5000")).slice(1);
  if(!tasks.some(r=>r[0]===id))throw Error("task_not_registered");
  const items=parseJson(p.plan_json);
  const seen=new Set(),at=now();
  const normalized=items.map(x=>{
   const code=String(x.language_code||"").trim().toLowerCase();
   if(!LANG.has(code)||seen.has(code))throw Error("invalid_or_duplicate_language");
   seen.add(code);
   const transcript=code==="en"||TRUE(x.transcript_enabled);
   const audio=TRUE(x.audio_enabled);
   const tSource=String(x.transcript_source||"");
   const aSource=String(x.audio_source||"");
   if(!["ai","human","youtube","manual"].includes(tSource)||
      !["tts","human","manual"].includes(aSource))
     throw Error("invalid_language_source_"+code);
   return [id,code,String(x.language_name||code).slice(0,100),
     transcript?"TRUE":"FALSE",tSource,audio?"TRUE":"FALSE",
     aSource,"planned",at,""];
  });
  const rows=await get("語言任務設定","A1:J5000");
  const original=new Map(rows.slice(1).map((r,i)=>[String(r[0])+":"+String(r[1]),{r,row:i+2}]));
  let translationChanged=false,audioChanged=false;
  const append=[];
  for(const row of normalized){
   const prev=original.get(id+":"+row[1]);
   if(prev){
    translationChanged||=String(prev.r[3]||"")!==row[3]||String(prev.r[4]||"")!==row[4];
    audioChanged||=String(prev.r[5]||"")!==row[5]||String(prev.r[6]||"")!==row[6];
    // Preserve the existing workflow status and any prior annotations.
    row[7]=String(prev.r[7]||"planned");row[9]=String(prev.r[9]||"");
   }else{
    translationChanged||=row[3]==="TRUE" && row[1]!=="en";
    audioChanged||=row[5]==="TRUE";
    append.push(row);
   }
  }
  if(append.length)await put("語言任務設定","A:J",append,true);
  for(const row of normalized){
   const prev=original.get(id+":"+row[1]);
   if(prev)await put("語言任務設定","A"+prev.row+":J"+prev.row,[row]);
  }
  const verified=(await get("語言任務設定","A1:J5000")).slice(1);
  for(const row of normalized){
   const matches=verified.filter(r=>r[0]===id&&r[1]===row[1]);
   if(matches.length!==1||[3,4,5,6].some(i=>String(matches[0][i]||"")!==row[i]))
     throw Error("language_plan_readback_failed_"+row[1]);
  }
  // Never delete old language outputs. Mark the prior stage outdated only when
  // the selected inputs have changed; manual rerun is explicitly required.
  if(translationChanged||audioChanged){
   const all=(await get("執行狀態","A1:M20000")).slice(1);
   for(const [stage,changed] of [["multi",translationChanged],["tts",audioChanged]]){
    if(!changed)continue;
    const latest=all.filter(r=>r[0]===id&&r[1]===stage).at(-1);
    if(latest?.[2]!=="done")continue;
    await put("執行狀態","A:M",[[id,stage,"stale","language-plan-"+at,
      "0","語言設定有變動，保留舊成果；需核對後重跑","", "",at,
      "","","",""]],true);
   }
  }
  return {ok:true,task_id:id,translation_changed:translationChanged,
    audio_changed:audioChanged,
    plan:normalized.map(r=>({task_id:id,language_code:r[1],language_name:r[2],
      transcript_enabled:TRUE(r[3]),transcript_source:r[4],
      audio_enabled:TRUE(r[5]),audio_source:r[6],status:r[7],
      updated_at:r[8],note:r[9]}))};
 }
 return {tasksUpsert,languagePlanSave};
}
module.exports={createCentralWrites};

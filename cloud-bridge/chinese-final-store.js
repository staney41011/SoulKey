"use strict";
const crypto=require("node:crypto");
const BACKUP="中文人工定稿備存",INDEX="中文人工定稿索引";
const BACKUP_HEAD=["task_id","revision","part_index","part_count","json_part","saved_at","sha256"];
const INDEX_HEAD=["task_id","revision","segment_count","saved_at","storage","publisher"];
const sum=v=>crypto.createHash("sha256").update(v).digest("hex");
const now=()=>new Date().toISOString();
function normalizeChineseFinal(p){
 const task=String(p.task_id||"");
 if(!/^P\d+-L\d{2}$/.test(task)||p.kind!=="zh")throw Error("invalid_chinese_final_task");
 let input;
 try{input=JSON.parse(p.segments_json||"[]");}catch(_){throw Error("invalid_chinese_json")}
 if(!Array.isArray(input)||!input.length||input.length>2500)throw Error("invalid_chinese_segments");
 const seen=new Set();
 const segments=input.map((x,i)=>{
  const id=Number(x?.id),start=Number(x?.start),end=Number(x?.end);
  const text=String(x?.text||"").trim();
  if(!Number.isSafeInteger(id)||id<0||seen.has(id)||
     !Number.isFinite(start)||!Number.isFinite(end)||
     start<0||end<start||!text||text.length>25000)
   throw Error("invalid_chinese_segment_"+i);
  seen.add(id);
  return{id,start,end,text};
 });
 return {task_id:task,kind:"zh",segments};
}
function createChineseFinalStore({get,put,ensureTab,readOriginal,utcNow=now}){
 async function read(task){
  if(!/^P\d+-L\d{2}$/.test(String(task||"")))throw Error("invalid_task_id");
  let rows;
  try{rows=await get(INDEX,"A1:F10000");}
  catch(e){
   if(/unable to parse range|not found|404|400/i.test(String(e.message||e)))return null;
   throw e;
  }
  const latest=(rows||[]).slice(1).filter(r=>r[0]===task&&/^[0-9a-f]{64}$/.test(r[1]||"")).at(-1);
  if(!latest)return null;
  const revision=latest[1],parts=(await get(BACKUP,"A1:G15000")).slice(1)
    .filter(r=>r[0]===task&&r[1]===revision);
  const count=Number(parts[0]?.[3]||0);
  if(!Number.isSafeInteger(count)||count<1||count>150)throw Error("chinese_final_invalid_part_count");
  const byIndex=new Map();
  for(const r of parts){
   const i=Number(r[2]);
   if(i>=0&&i<count&&Number(r[3])===count&&r[6]===revision&&
      typeof r[4]==="string")byIndex.set(i,r[4]);
  }
  if(byIndex.size!==count)throw Error("chinese_final_parts_missing");
  const payload=Array.from({length:count},(_,i)=>byIndex.get(i)).join("");
  if(sum(payload)!==revision)throw Error("chinese_final_sha_mismatch");
  const manuscript=JSON.parse(payload);
  if(manuscript.task_id!==task||manuscript.kind!=="zh"||
     manuscript.segments?.length!==Number(latest[2]))
   throw Error("chinese_final_content_mismatch");
  return {revision,manuscript,saved_at:latest[3]};
 }
 async function save(p){
  const manuscript=normalizeChineseFinal(p);
  // Never accept old segments from a different lesson even when an editor
  // requests another task ID. The original lesson-specific Final must exist,
  // and every original ID/time anchor must match.
  const original=await readOriginal(manuscript.task_id);
  if(!Array.isArray(original?.segments)||!original.segments.length)
   throw Error("chinese_source_not_found_for_lesson");
  const base=new Map(original.segments.map((x,i)=>[Number(x.id??i),x]));
  const submitted=manuscript.segments;
  if(submitted.length!==base.size || submitted.some(x=>{
   const y=base.get(x.id);
   return !y || Math.abs(x.start-Number(y.start||0))>2.5 ||
     Math.abs(x.end-Number(y.end||0))>3.5;
  }))throw Error("chinese_source_timeline_mismatch");
  const payload=JSON.stringify(manuscript),revision=sum(payload);
  const chunks=[];
  for(let start=0;start<payload.length;){
   let end=Math.min(start+28000,payload.length);
   if(end<payload.length && /[\uD800-\uDBFF]/.test(payload[end-1]) &&
      /[\uDC00-\uDFFF]/.test(payload[end]))end--;
   chunks.push(payload.slice(start,end));start=end;
  }
  if(chunks.length>150)throw Error("chinese_final_too_large");
  await ensureTab(BACKUP,BACKUP_HEAD);
  await ensureTab(INDEX,INDEX_HEAD);
  const existing=(await get(BACKUP,"A1:G15000")).slice(1);
  const saved=new Set(existing.filter(r=>r[0]===manuscript.task_id&&r[1]===revision&&
   r[4]===chunks[Number(r[2])]&&Number(r[3])===chunks.length).map(r=>Number(r[2])));
  const at=utcNow(),add=chunks.map((value,i)=>({value,i}))
   .filter(x=>!saved.has(x.i)).map(x=>[
    manuscript.task_id,revision,String(x.i),String(chunks.length),x.value,at,revision
   ]);
  if(add.length)await put(BACKUP,"A:G",add,true);
  const check=(await get(BACKUP,"A1:G15000")).slice(1);
  const verified=new Map(check.filter(r=>r[0]===manuscript.task_id&&r[1]===revision)
   .map(r=>[Number(r[2]),r[4]]));
  if(verified.size!==chunks.length||
     sum(chunks.map((v,i)=>verified.get(i)).join(""))!==revision)
   throw Error("chinese_final_backup_readback_failed");
  const indices=await get(INDEX,"A1:F10000");
  if(!indices.slice(1).some(r=>r[0]===manuscript.task_id&&r[1]===revision))
   await put(INDEX,"A:F",[[manuscript.task_id,revision,
    String(submitted.length),utcNow(),"google-sheet","soulkey-cloud-run"]],true);
  const final=await read(manuscript.task_id);
  if(!final || final.revision!==revision)throw Error("chinese_final_index_readback_failed");
  return {source:"soulkey-bridge",type:"review_saved",ok:true,
   kind:"zh",task_id:manuscript.task_id,revision,segment_count:submitted.length,
   sheet_finalized:true,drive_saved:false,pending_drive:true,
   message:"中文定稿已安全寫入中央 Google Sheet 並回讀驗證；原 Google Drive 檔案尚待同步"};
 }
 return {read,save};
}
module.exports={createChineseFinalStore,normalizeChineseFinal};

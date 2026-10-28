"use strict";
const crypto=require("node:crypto");
const TAB="英文定稿索引";
const HEAD=["task_id","backup_id","segment_count","finalized_at","storage","publisher"];
const valid=id=>/^P\d+-L\d{2}$/i.test(String(id||""));
const sha=s=>crypto.createHash("sha256").update(s).digest("hex");
function createSheetFinalStore({get,put,ensureTab,now=()=>new Date().toISOString()}){
 async function read(task){
  if(!valid(task))throw Error("invalid_final_task_id");
  const index=await get(TAB,"A1:F10000").catch(e=>{
   if(/Unable to parse range|not found|404|400/i.test(String(e.message||e)))return[];
   throw e;
  });
  const completed=index.slice(1).filter(r=>r[0]===task&&
    /^[a-f0-9]{64}$/.test(String(r[1]||"")));
  if(!completed.length)return null;
  const latest=completed[completed.length-1];
  const hash=String(latest[1]),raw=await get("英文定稿備存","A1:G10000");
  const parts=raw.slice(1).filter(r=>r[0]===task&&r[1]===hash);
  const count=Number(parts[0]?.[3]||0),chunks=new Map();
  if(!Number.isSafeInteger(count)||count<1||count>100)throw Error("invalid_final_chunk_count");
  for(const r of parts){
   const index=Number(r[2]);
   if(index>=0&&index<count&&r[3]==String(count)&&r[6]===hash&&
      typeof r[4]==="string"&&!chunks.has(index))chunks.set(index,r[4]);
  }
  if(chunks.size!==count)throw Error("sheet_final_missing_chunks");
  const data=Array.from({length:count},(_,i)=>chunks.get(i)).join("");
  if(sha(data)!==hash)throw Error("sheet_final_hash_mismatch");
  const parsed=JSON.parse(data);
  if(parsed.task_id!==task||parsed.kind!=="en"||!Array.isArray(parsed.segments)||
     parsed.segments.length!==Number(latest[2]))throw Error("sheet_final_content_mismatch");
  return {backup_id:hash,finalized_at:latest[3],manuscript:parsed};
 }
 async function finalize(task,hash,segmentCount){
  if(!valid(task)||!/^[a-f0-9]{64}$/.test(hash))throw Error("invalid_final_receipt");
  await ensureTab(TAB,HEAD);
  const index=await get(TAB,"A1:F10000");
  const exists=index.slice(1).some(r=>r[0]===task&&r[1]===hash);
  if(!exists)await put(TAB,"A:F",[[task,hash,String(segmentCount),now(),"google-sheet","soulkey-cloud-run"]],true);
  const verified=await read(task);
  if(!verified||verified.backup_id!==hash||
     verified.manuscript.segments.length!==segmentCount)
    throw Error("sheet_final_readback_failed");
  return {source:"soulkey-bridge",type:"review_saved",ok:true,
   task_id:task,kind:"en",backup_id:hash,segment_count:segmentCount,
   sheet_finalized:true,drive_saved:false,pending_drive:true,
   message:"英文全文已寫入 Google Sheet 正式定稿並通過 SHA-256 回讀驗證；Drive 同步尚待授權。"};
 }
 return {read,finalize};
}
module.exports={createSheetFinalStore};

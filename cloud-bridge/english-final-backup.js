"use strict";
const crypto=require("node:crypto");
const TAB="英文定稿備存";
const HEADER=["task_id","backup_id","part_index","part_count","payload_json_part","saved_at","sha256"];
const MAX_SEGMENTS=2000;
const CHUNK_SIZE=28000;
function normalizeEnglishFinal(p){
 const task=String(p.task_id||"").trim();
 if(!/^P\d+-L\d{2}$/.test(task)||String(p.kind)!=="en")
  throw Error("invalid_english_final_task");
 let raw,terms;
 try{
  raw=JSON.parse(p.segments_json||"[]");
  terms=JSON.parse(p.terms_json||"[]");
 }catch(_){throw Error("invalid_english_final_json")}
 if(!Array.isArray(raw)||!raw.length||raw.length>MAX_SEGMENTS)
  throw Error("invalid_segment_count");
 if(!Array.isArray(terms)||terms.length>1000)throw Error("invalid_terms");
 const seen=new Set();
 const segments=raw.map((x,i)=>{
  const id=Number(x?.id??i),start=Number(x?.start||0),end=Number(x?.end??start);
  const text=String(x?.text||"").trim();
  if(!Number.isSafeInteger(id)||id<0||seen.has(id)||
     !Number.isFinite(start)||!Number.isFinite(end)||
     start<0||end<start||text.length>20000||!text)
   throw Error("invalid_english_segment_"+i);
  seen.add(id);
  return {id,start,end,text};
 });
 const cleanTerms=terms.map(x=>({
  zh:String(x?.zh||"").trim().slice(0,200),
  en:String(x?.en||"").trim().slice(0,200)
 })).filter(x=>x.zh&&x.en);
 return {task_id:task,kind:"en",segments,learned_terms:cleanTerms};
}
function createEnglishFinalBackup({get,put,ensureTab,now=()=>new Date().toISOString()}){
 async function save(p){
  const final=normalizeEnglishFinal(p);
  const data=JSON.stringify(final);
  const hash=crypto.createHash("sha256").update(data).digest("hex");
  const parts=[];
  // Do not split a Unicode surrogate pair across separate Sheet cells.
  for(let i=0;i<data.length;){
   let end=Math.min(i+CHUNK_SIZE,data.length);
   if(end<data.length){
    const previous=data.charCodeAt(end-1),next=data.charCodeAt(end);
    if(previous>=0xD800&&previous<=0xDBFF&&next>=0xDC00&&next<=0xDFFF)end--;
   }
   parts.push(data.slice(i,end));
   i=end;
  }
  if(parts.length>100)throw Error("final_backup_too_large");
  await ensureTab(TAB,HEADER);
  const existing=await get(TAB,"A1:G10000");
  const group=existing.slice(1).filter(r=>r[0]===final.task_id&&r[1]===hash);
  const seen=new Map();
  for(const row of group){
   const index=Number(row[2]);
   if(Number.isInteger(index)&&index>=0&&index<parts.length && row[4]===parts[index])
    seen.set(index,row[4]);
  }
  const missing=parts.map((value,index)=>({index,value})).filter(x=>!seen.has(x.index));
  if(missing.length){
   const at=now();
   const rows=missing.map(({index,value})=>[
    final.task_id,hash,String(index),String(parts.length),value,at,hash
   ]);
   await put(TAB,"A:G",rows,true);
  }
  const after=await get(TAB,"A1:G10000");
  const verified=new Map();
  for(const row of after.slice(1)){
   if(row[0]!==final.task_id||row[1]!==hash)continue;
   const index=Number(row[2]);
   if(Number.isInteger(index)&&index>=0&&index<parts.length &&
      Number(row[3])===parts.length&&row[4]===parts[index]&&row[6]===hash)
    verified.set(index,row[4]);
  }
  if(verified.size!==parts.length||
     crypto.createHash("sha256").update([...verified.entries()]
       .sort((a,b)=>a[0]-b[0]).map(v=>v[1]).join("")).digest("hex")!==hash)
    throw Error("english_final_backup_readback_failed");
  return {source:"soulkey-bridge",type:"review_saved",
   ok:false,task_id:final.task_id,kind:"en",pending_drive:true,
   backup_saved:true,backup_id:hash,segment_count:final.segments.length,
   message:"英文逐字稿已完整備份到中央 Google Sheet；Google Drive 正式定稿尚未完成。請勿將此狀態當成定稿完成。"};
 }
 return {save};
}
module.exports={normalizeEnglishFinal,createEnglishFinalBackup};

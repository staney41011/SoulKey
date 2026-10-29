"use strict";
const {randomUUID}=require("node:crypto");
const TASK_TAB="YouTube CC 任務";
const CONTENT_TAB="YouTube CC 成果";
const TASK_HEAD=["job_id","task_id","video_id","status","created_at","claimed_at","finished_at","message","lang_count"];
const CONTENT_HEAD=["job_id","task_id","video_id","language","part_index","part_count","transcript_text","stored_at","source"];
const VID=/^[A-Za-z0-9_-]{11}$/;
const TASK=/^P\d+-L\d{2}(?:-R\d+)?$/;
const JOB=/^[0-9a-f-]{36}$/;
const LANGS=new Set(["en","th","es","id","vi","sd","ta"]);
function videoId(url){
 const text=String(url||"").trim();
 const match=text.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?[^#]*?v=|shorts\/|live\/))([\w-]{11})(?![\w-])/);
 return match?.[1]||"";
}
function createYoutubeCCQueue({get,put,ensureTab,now=()=>new Date().toISOString()}){
 async function init(){
  await ensureTab(TASK_TAB,TASK_HEAD);
  await ensureTab(CONTENT_TAB,CONTENT_HEAD);
 }
 async function tasks(){await init();return (await get(TASK_TAB,"A1:I5000")).slice(1);}
 async function contents(){await init();return (await get(CONTENT_TAB,"A1:I30000")).slice(1);}
 async function taskVideo(task){
  if(!TASK.test(task))throw Error("invalid_task_id");
  const rows=await get("任務佇列","A1:E5000");
  const row=rows.slice(1).find(r=>r[0]===task);
  if(!row)throw Error("task_not_registered");
  const video=videoId(row[4]||"");
  if(!VID.test(video))throw Error("task_has_no_youtube_video_id");
  return video;
 }
 async function appendStatus(task,state,id,video,message){
  const at=now();
  await put("執行狀態","A:M",[[
   task,"cc",state,id,state==="done"?"100":"0",message,
   "",state==="done"||state==="error"?at:"",at,"","",video,video
  ]],true);
 }
 async function enqueue(p){
  const task=String(p.task_id||"").trim();
  if(p.stage!=="cc"||p.lang==="multi-audio")
   throw Error("unsupported_capture_stage");
  const video=await taskVideo(task);
  const rows=await tasks();
  const existing=rows.slice().reverse().find(r=>r[1]===task&&r[2]===video&&
    ["queued","running"].includes(r[3]));
  if(existing)return {ok:true,task_id:task,stage:"cc",job_id:existing[0],
   status:existing[3],duplicate:true,queue_mode:"scheduled-github-actions",
   message:"本堂 YouTube CC 已在佇列，沒有重複抓取"};
  const id=randomUUID();
  await put(TASK_TAB,"A:I",[[id,task,video,"queued",now(),"","",
   "等待 GitHub Actions 領取",""]],true);
  const verify=await tasks();
  if(!verify.some(r=>r[0]===id&&r[3]==="queued"))
   throw Error("youtube_cc_queue_not_verified");
  await appendStatus(task,"queued",id,video,"CC 抓取已加入中央佇列，等待 GitHub Worker");
  return {ok:true,task_id:task,stage:"cc",job_id:id,status:"queued",
   queue_mode:"scheduled-github-actions",message:"中央佇列已確認；等待 Worker 真正抓取 YouTube CC"};
 }
 async function claim(){
  const rows=await tasks(),index=rows.findIndex(r=>r[3]==="queued");
  if(index<0)return {ok:true,has_job:false};
  const row=rows[index],video=await taskVideo(row[1]);
  if(video!==row[2]){
   await put(TASK_TAB,"D"+(index+2)+":H"+(index+2),
    [["error",row[4]||"",row[5]||"",now(),"課程影片已更換，拒絕舊抓取工作"]]);
   await appendStatus(row[1],"error",row[0],row[2],"課程 YouTube 來源已改變");
   return {ok:true,has_job:false,invalidated:true};
  }
  await put(TASK_TAB,"D"+(index+2)+":H"+(index+2),
   [["running",row[4]||"",now(),"","GitHub Worker 已領取 CC 抓取工作"]]);
  await appendStatus(row[1],"running",row[0],video,"正在從本堂 YouTube 抓取 CC");
  return {ok:true,has_job:true,job:{id:row[0],task_id:row[1],video_id:video,
   languages:[...LANGS]}};
 }
 async function part(p){
  const id=String(p.job_id||""),lang=String(p.language||"").trim().toLowerCase();
  const index=Number(p.part_index),count=Number(p.part_count);
  if(!JOB.test(id)||!LANGS.has(lang)||!Number.isSafeInteger(index)||
   !Number.isSafeInteger(count)||count<1||count>250||index<0||index>=count)
    throw Error("invalid_caption_part");
  const text=String(p.content||"");
  if(!text.trim()||text.length>20000)throw Error("invalid_caption_content");
  const rows=await tasks(),record=rows.find(r=>r[0]===id);
  if(!record||record[3]!=="running")throw Error("caption_job_not_running");
  const canonical=await taskVideo(record[1]);
  if(canonical!==record[2])throw Error("caption_video_changed");
  const existing=await contents();
  const seen=existing.find(r=>r[0]===id&&r[3]===lang&&Number(r[4])===index);
  if(seen){
   if(seen[6]!==text||Number(seen[5])!==count)
    throw Error("caption_part_conflict");
   return {ok:true,duplicate:true};
  }
  await put(CONTENT_TAB,"A:I",[[id,record[1],canonical,lang,
   String(index),String(count),text,now(),String(p.source||"youtube").slice(0,70)]],true);
  const verify=await contents();
  if(!verify.some(r=>r[0]===id&&r[3]===lang&&Number(r[4])===index&&r[6]===text))
   throw Error("caption_part_readback_failed");
  return {ok:true,task_id:record[1],language:lang,part_index:index};
 }
 function grouped(rows,id){
  const groups=new Map();
  for(const r of rows.filter(x=>x[0]===id)){
   const lang=r[3];if(!LANGS.has(lang))continue;
   const g=groups.get(lang)||{count:Number(r[5]),parts:new Map(),source:r[8]};
   if(g.count!==Number(r[5]))throw Error("caption_part_count_mismatch");
   const i=Number(r[4]);if(i<0||i>=g.count)throw Error("caption_part_index_invalid");
   if(g.parts.has(i)&&g.parts.get(i)!==r[6])throw Error("caption_part_conflict");
   g.parts.set(i,r[6]);groups.set(lang,g);
  }
  return groups;
 }
 async function finish(p){
  const id=String(p.job_id||"");
  if(!JOB.test(id))throw Error("invalid_cc_job_id");
  const rows=await tasks(),idx=rows.findIndex(r=>r[0]===id);
  if(idx<0)throw Error("cc_job_not_found");
  const job=rows[idx];
  if(job[3]==="done")return {ok:true,duplicate:true};
  if(job[3]!=="running")throw Error("cc_job_not_running");
  const latest=await taskVideo(job[1]);
  if(latest!==job[2])throw Error("cc_source_changed");
  if(p.status==="error"){
   const reason=String(p.message||"worker_failed").slice(0,280);
   await put(TASK_TAB,"D"+(idx+2)+":I"+(idx+2),
    [["error",job[4]||"",job[5]||"",now(),reason,job[8]||""]]);
   await appendStatus(job[1],"error",id,job[2],reason);
   return {ok:true,status:"error",task_id:job[1]};
  }
  if(p.status!=="done")throw Error("invalid_cc_finish_status");
  const expected=String(p.languages||"").split(",").filter(Boolean);
  if(!expected.length||expected.some(x=>!LANGS.has(x))||
     new Set(expected).size!==expected.length)throw Error("invalid_caption_languages");
  const groups=grouped(await contents(),id);
  if(groups.size!==expected.length||expected.some(x=>!groups.has(x)))
   throw Error("cc_languages_incomplete");
  for(const lang of expected){
   const g=groups.get(lang);
   if(!Number.isSafeInteger(g.count)||g.count<1||g.parts.size!==g.count)
    throw Error("cc_parts_missing_"+lang);
   for(let i=0;i<g.count;i++)if(!g.parts.get(i))
    throw Error("cc_part_missing_"+lang+"_"+i);
  }
  await put(TASK_TAB,"D"+(idx+2)+":I"+(idx+2),
   [["done",job[4]||"",job[5]||"",now(),
     "已保存 "+expected.length+" 種本堂原始字幕；尚未同步 Google Drive",
     String(expected.length)]]);
  await appendStatus(job[1],"done",id,job[2],
   "YouTube CC 已保存 "+expected.length+" 種語言至中央 Sheet（Drive 待同步）");
  return {ok:true,status:"done",task_id:job[1],language_count:expected.length};
 }
 async function manifest(task){
  const canonical=await taskVideo(task);
  const entries=(await tasks()).filter(r=>r[1]===task&&r[2]===canonical&&r[3]==="done");
  const data=await contents(),cc=[];
  for(const job of entries){
   const groups=grouped(data,job[0]);
   for(const [lang,g] of groups){
    if(g.parts.size!==g.count)continue;
    const name=lang+".transcript.txt";
    if(cc.some(x=>x.name===name))continue;
    cc.push({name,display_name:lang.toUpperCase()+" YouTube CC 純逐字稿",
     storage:"google-sheet",job_id:job[0],lang,updated_at:job[6],
     source:"youtube",size:[...g.parts.values()].reduce((sum,x)=>sum+x.length,0)});
   }
  }
  return {source:"soulkey-bridge",type:"youtube_capture_files",ok:true,
   task_id:task,video_id:canonical,cc_files:cc,asr_files:[],audio_files:[],
   captions_storage:"google-sheet",drive_synced:false};
 }
 async function transcript(task,jobId,lang){
  if(!JOB.test(String(jobId||""))||!LANGS.has(lang))throw Error("invalid_caption_read");
  const rows=await tasks();
  const job=rows.find(r=>r[0]===jobId&&r[1]===task&&r[3]==="done");
  if(!job||job[2]!==await taskVideo(task))throw Error("caption_job_not_finalized_for_lesson");
  const g=grouped(await contents(),jobId).get(lang);
  if(!g||g.parts.size!==g.count)throw Error("caption_content_not_complete");
  return {source:"soulkey-bridge",type:"youtube_cc_content",ok:true,
    task_id:task,lang,name:lang+".transcript.txt",
    content:Array.from({length:g.count},(_,i)=>g.parts.get(i)).join("")};
 }
 return {enqueue,claim,part,finish,manifest,transcript};
}
module.exports={createYoutubeCCQueue,videoId,TASK_HEAD,CONTENT_HEAD};
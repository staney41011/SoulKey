"use strict";
const http=require("node:http"),{GoogleAuth}=require("google-auth-library");
const {createBridgeAuth}=require("./auth");
const {createDriveReview}=require("./drive-review");
const {createEnglishFinalBackup,normalizeEnglishFinal}=require("./english-final-backup");
const {createSheetFinalStore}=require("./sheet-final-store");
const {createChineseFinalStore}=require("./chinese-final-store");
const {createDriveFinalPublisher}=require("./drive-final-publisher");
const {createTranslationQueue}=require("./translation-queue");
const {createYoutubeCCQueue}=require("./youtube-cc-queue");
const {verifyGithubWorker}=require("./github-worker-auth");
const ID="1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8";
const N={tasks:"任務佇列",status:"執行狀態",lang:"語言設定",plans:"語言任務設定",edits:"英文人工定稿"};
const key=process.env.BRIDGE_KEY||"",source="soulkey-bridge";
const bridgeAuth=createBridgeAuth({primaryKey:key,legacyHmac:process.env.BRIDGE_LEGACY_HMAC||""});
const auth=new GoogleAuth({scopes:["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive.readonly"]});
let client;async function google(method,url,body){client??=await auth.getClient();return(await client.request({method,url:"https://sheets.googleapis.com/v4/spreadsheets/"+ID+((url.startsWith("?")||url.startsWith(":"))?"":"/")+url,data:body,timeout:20000})).data;}
const range=(sheet,a)=>encodeURIComponent("'"+sheet+"'!"+a);
async function get(s,a="A1:Z10000"){return(await google("GET","values/"+range(s,a)+"?valueRenderOption=FORMATTED_VALUE")).values||[];}
async function put(s,a,rows,append=false){return google(append?"POST":"PUT","values/"+range(s,a)+(append?":append?valueInputOption=RAW&insertDataOption=INSERT_ROWS":"?valueInputOption=RAW"),{values:rows,majorDimension:"ROWS"});}
const driveReview=createDriveReview(auth,get);
const finalBackupTabReady=new Map();
async function ensureBackupTab(title,headers){
 if(finalBackupTabReady.has(title))return finalBackupTabReady.get(title);
 const promise=(async()=>{
  const metadata=await google("GET","?fields=sheets.properties.title");
  const found=(metadata.sheets||[]).some(s=>s.properties.title===title);
  if(!found){
   try{
    await google("POST",":batchUpdate",{requests:[{addSheet:{properties:{title}}}]});
   }catch(error){
    const latest=await google("GET","?fields=sheets.properties.title");
    if(!(latest.sheets||[]).some(s=>s.properties.title===title))throw error;
   }
  }
  const endCol=String.fromCharCode(64+headers.length);
  const existing=(await get(title,"A1:"+endCol+"1"))[0]||[];
  if(!existing.length){
   await put(title,"A1:"+endCol+"1",[headers]);
  }else if(headers.some((value,i)=>String(existing[i]||"")!==value)){
   throw Error("tab_header_mismatch:"+title);
  }
 })();
 finalBackupTabReady.set(title,promise);
 try{await promise;}
 catch(error){finalBackupTabReady.delete(title);throw error;}
}

const englishFinalBackup=createEnglishFinalBackup({
 get,put,ensureTab:ensureBackupTab
});
const sheetFinalStore=createSheetFinalStore({get,put,ensureTab:ensureBackupTab});
const chineseFinalStore=createChineseFinalStore({
 get,put,ensureTab:ensureBackupTab,
 readOriginal:task=>driveReview.readOriginalChineseFinal(task)
});
driveReview.setChineseFinalLoader(task=>chineseFinalStore.read(task));
driveReview.setSheetFinalLoader(task=>sheetFinalStore.read(task));
const youtubeCCQueue=createYoutubeCCQueue({get,put,ensureTab:ensureBackupTab});
const translationQueue=createTranslationQueue({
 get,put,ensureTab:ensureBackupTab,
 readFinal:task=>sheetFinalStore.read(task),
 taskExists:async id=>(await get(N.tasks,"A1:A5000")).slice(1).some(r=>r[0]===id)
});
const driveFinalPublisher=createDriveFinalPublisher({
 resolveFolders:driveReview.resolveFolders,invalidateFolder:driveReview.invalidateFolder,get,put
});
async function recordVerifiedEnglishStage(taskId,hash,mode){
 const tasksRows=await get(N.tasks,"A1:J5000");
 const taskRow=tasksRows.findIndex((r,i)=>i>0&&r[0]===taskId);
 if(taskRow<1)throw Error("english_final_task_not_found");
 if(String(tasksRows[taskRow][9]||"")!=="完成")
  await put(N.tasks,"J"+(taskRow+1),[["完成"]]);
 const rows=await get(N.status,"A1:M20000");
 const previouslyRecorded=rows.slice(1).some(r=>
  r[0]===taskId&&r[1]==="en-review"&&r[2]==="done"&&
  (r[11]===hash||r[12]===hash));
 if(previouslyRecorded)return;
 const timestamp=now();
 await put(N.status,"A:M",[[
  taskId,"en-review","done","sheet-final-"+hash.slice(0,12),"100",
  mode==="drive"?"英文 Google Drive 正式定稿已回讀驗證":
    "英文 Google Sheet 中央定稿已回讀驗證；Drive 待同步",
  "",timestamp,timestamp,"","",hash,hash
 ]],true);
}
async function saveFullEnglishFinal(p){
 // Never accept third-lesson English pasted under another lesson's ID.
 // The matching, per-task English source must exist in the canonical Drive
 // lesson folder or in this task's verified Sheet Final.
 const sourceCheck=await driveReview.review({task_id:String(p.task_id||""),kind:"en"});
 if(!sourceCheck.ok||!Array.isArray(sourceCheck.segments)||!sourceCheck.segments.length)
  throw Error("english_source_missing_for_this_lesson");
 const manuscript=normalizeEnglishFinal(p);
 const original=sourceCheck.segments;
 const aligned=manuscript.segments.every(seg=>
  original.some(row=>Math.abs(Number(row.start||0)-seg.start)<2.6 &&
   Number(row.end||row.start||0)>=seg.start));
 if(!aligned)throw Error("english_final_timeline_does_not_match_lesson");
 const task=(await get(N.tasks,"A1:J5000")).slice(1).find(r=>r[0]===String(p.task_id||""));
 const targetUrl=String(task?.[4]||"");
 const targetVideo=(targetUrl.match(/(?:youtu\.be\/|[?&]v=)([A-Za-z0-9_-]{6,})/)||[])[1]||"";
 if(p.source_video_id && targetVideo &&
    String(p.source_video_id)!==targetVideo)
  throw Error("english_final_source_video_mismatch");
 const backup=await englishFinalBackup.save(p);
 if(!backup.backup_saved)throw Error("english_final_backup_incomplete");
 if(!driveFinalPublisher.isConfigured()){
  const result=await sheetFinalStore.finalize(String(p.task_id||""),
    backup.backup_id,backup.segment_count);
  await recordVerifiedEnglishStage(String(p.task_id||""),
    backup.backup_id,"sheet");
  return {...result,backup_saved:true};
 }
 try{
  const result=await driveFinalPublisher.publish(String(p.task_id||""),manuscript);
  await recordVerifiedEnglishStage(String(p.task_id||""),
    backup.backup_id,"drive");
  return {...result,backup_id:backup.backup_id,backup_saved:true};
 }catch(err){
  console.error("Owner Drive finalize failed",String(err.message||err).slice(0,180));
  const result=await sheetFinalStore.finalize(String(p.task_id||""),
    backup.backup_id,backup.segment_count);
  await recordVerifiedEnglishStage(String(p.task_id||""),
    backup.backup_id,"sheet");
  return {...result,backup_saved:true,
   message:"英文全文已正式儲存至中央 Google Sheet；Google Drive 同步未成功："+String(err.message||err).slice(0,100)};
 }
}

const out=(type,o={})=>({source,type,...o}), now=()=>new Date().toISOString(),n=x=>Number(String(x||"").replace(/\D/g,""))||null,b=x=>String(x||"").toUpperCase()==="TRUE", valid=x=>/^P\d+-L\d+(?:-R\d+)?$/i.test(String(x));
function ok(k){return bridgeAuth.valid(k);}
async function tasks(){return(await get(N.tasks,"A1:Z5000")).slice(1).filter(r=>valid(r[0])).map(r=>({
 id:r[0],period:n(r[1]),lesson:r[2]||"",title:r[3]||"",url:r[4]||"",lecturer:r[5]||"",source_language:r[6]||"",
 asr:r[7]||"",zh_review:r[8]||"",en:r[9]||"",th:r[10]||"",es:r[11]||"",id_lang:r[12]||"",vi:r[13]||"",subtitle:r[14]||"",audio:r[15]||"",video:r[16]||"",
 progress:r[17]||"",updated_at:r[18]||"",note:r[19]||"",course_uid:r[20]||"",schedule_status:r[21]||"",original_period:n(r[22]),original_lesson:r[23]||"",rescheduled_at:r[24]||"",schedule_note:r[25]||""
}));}
async function langs(){return(await get(N.lang,"A1:E200")).slice(1).filter(r=>r[0]&&b(r[2])).map(r=>({code:r[0],name:r[1]||r[0],translation_model:r[3]||"",tts_model:r[4]||"",can_ai_translate:!!r[3],can_tts:!!r[4]}));}
async function plans(id){return(await get(N.plans,"A1:J5000")).slice(1).filter(r=>r[0]===id).map(r=>({task_id:id,language_code:r[1]||"",language_name:r[2]||"",transcript_enabled:b(r[3]),transcript_source:r[4]||"",audio_enabled:b(r[5]),audio_source:r[6]||"",status:r[7]||"",updated_at:r[8]||"",note:r[9]||""}));}
async function status(ids){const rows=await get(N.status,"A1:Z20000");const h=rows.shift()||[],col=Object.fromEntries(h.map((x,i)=>[x,i]));const data={};for(const r of rows){const id=r[col.task_id],stage=r[col.stage];if(!ids.includes(id)||!stage)continue;data[id]??={stages:{}};const state={task_id:id,stage};for(const field of ["status","run_id","progress","message","started_at","finished_at","updated_at","error_code","error_message","input_revision","output_revision"]){state[field]=r[col[field]]||"";}state.root_error_code=state.error_code;state.root_error_message=state.error_message;data[id].stages[stage]=state;}return data;}
let tabReady=false;
async function editsTab(){if(tabReady)return;const m=await google("GET","?fields=sheets.properties.title");if(!(m.sheets||[]).some(s=>s.properties.title===N.edits)){await google("POST",":batchUpdate",{requests:[{addSheet:{properties:{title:N.edits}}}]});await put(N.edits,"A1:I1",[["task_id","segment_id","en_text","request_id","base_request_id","updated_at","confirmed","meta_json","source"]]);}tabReady=true;}
async function allEdits(task){await editsTab();const r=await get(N.edits,"A1:I20000");const edits={},receipts={};for(const x of r.slice(1)){if(x[0]!==task)continue;const id=String(x[1]);if(!/^\d+$/.test(id))continue;edits[id]={en_text:String(x[2]??""),en_confirmed:true,request_id:String(x[3]||""),updated_at:String(x[5]||"")};receipts[String(x[3]||"")]=String(x[5]||"");}return{edits,receipts};}
async function saveEnglish(p){const task=p.task_id;if(!valid(task))throw Error("invalid_task_id");const payload=JSON.parse(p.payload_json||"{}"),rid=String(payload.save_request_id||""),ids=new Set((payload.confirmed_segment_ids||[]).map(x=>String(Number(x))));if(!rid||!ids.size||ids.size>30||!Array.isArray(payload.segments))throw Error("invalid_review_payload");
 const existing=await allEdits(task);if(existing.receipts[rid])return out("english_review_draft_saved",{ok:true,task_id:task,request_id:rid,saved_at:existing.receipts[rid]});
 const batch=[];for(const x of payload.segments){const id=String(Number(x.id));if(!ids.has(id))continue;if(x.en_confirmed!==true)throw Error("not_confirmed_"+id);
 const prior=existing.edits[id];if(prior&&prior.request_id!==String(x.base_request_id||""))throw Error("edit_conflict_reload_required_"+id);
 batch.push([task,id,String(x.en_text??""),rid,String(x.base_request_id||""),now(),"TRUE","{}","cloud-bridge"]);}if(batch.length!==ids.size)throw Error("missing_segments");
 await put(N.edits,"A:I",batch,true);const after=await allEdits(task);
 for(const x of batch)if(after.edits[x[1]]?.request_id!==rid||after.edits[x[1]]?.en_text!==x[2])throw Error("readback_failed_"+x[1]);
 return out("english_review_draft_saved",{ok:true,task_id:task,request_id:rid,saved_at:now(),github_synced:false,message:"Drive 暫不可用；人工修改已保存至原 Google Sheet 並驗證"});
}
async function read(p){const a=p.action;if(a==="review_final_status"){
 const task=String(p.task_id||"");
 const final=await sheetFinalStore.read(task);
 return out("review_final_status",{ok:true,task_id:task,
  sheet_finalized:!!final,segment_count:final?.manuscript?.segments?.length||0,
  backup_id:final?.backup_id||""});
}if(a==="drive_owner_probe")return out("drive_owner_probe",{task_id:String(p.task_id||""),...await driveFinalPublisher.probe(String(p.task_id||""))});if(a==="youtube_capture_files"){
 const manifest=await youtubeCCQueue.manifest(String(p.task_id||""));
 const files=await driveReview.courseFiles(p);
 const groups=Array.isArray(files.groups)?files.groups:[];
 const transcripts=groups.find(g=>g.key==="transcript")?.files||[];
 const original=await driveReview.youtubeCaptureFiles(String(p.task_id||""));
 const folder=await driveReview.resolveFolders(String(p.task_id||""));
 const captions=new Map();
 for(const file of [...(original.cc_files||[]),...(manifest.cc_files||[])])
  captions.set(file.name,file);
 return {...manifest,
  cc_files:[...captions.values()],
  asr_files:transcripts.filter(x=>x.canonical_name==="zh-TW.transcript.txt"),
  audio_files:original.audio_files||[],
  source_folder_url:"https://drive.google.com/drive/folders/"+folder.source,
  transcript_folder_url:"https://drive.google.com/drive/folders/"+folder.transcript,
  audio_folder_url:"https://drive.google.com/drive/folders/"+folder.audio
 };
}
if(a==="youtube_cc_content")return youtubeCCQueue.transcript(String(p.task_id||""),
 String(p.job_id||""),String(p.language||""));
if(a==="course_files")return driveReview.courseFiles(p);if(a==="tts_share_links")return driveReview.ttsShareLinks(p);if(a==="review_load")return driveReview.review(p);if(a==="status_health"){
  const rows=await get(N.status,"A1:A10000");
  const [translationHealth,captureHealth]=await Promise.allSettled([
    translationQueue.diagnostics(),youtubeCCQueue.ready()
  ]);
  const translationReady=translationHealth.status==="fulfilled";
  const captionReady=captureHealth.status==="fulfilled";
  return out("status_health",{
    ok:true,sheet:N.status,rows:Math.max(rows.length-1,0),
    bridge_protocol:"cloud-recovery",
    bridge_build:String(process.env.SOULKEY_BUILD_SHA||"unversioned"),
    sheet_final_enabled:true,chinese_sheet_final_enabled:true,
    lesson_source_guard:true,
    translation_queue_enabled:translationReady,
    translation_queue_diagnostics:translationReady?translationHealth.value:null,
    youtube_cc_queue_enabled:captionReady,
    youtube_cc_storage:"google-sheet",
    translation_worker:"github-actions-oidc-scheduled",
    drive_owner_configured:driveFinalPublisher.isConfigured(),
    youtube_cookies_configured:false,server_time:now()
  });
 }
 if(a==="tasks_get")return out("tasks_result",{ok:true,tasks:await tasks(),server_time:now()});
 if(a==="language_settings")return out("language_settings",{ok:true,languages:await langs(),server_time:now()});
 if(a==="language_plan_get")return out("language_plan",{ok:true,task_id:p.task_id||"",plan:await plans(String(p.task_id||""))});
 if(a==="status"||a==="status_batch"){const ids=String(p.task_ids||p.task_id||"").split(",").filter(valid).slice(0,20);return out("status_result",{ok:!!ids.length,tasks:await status(ids),server_time:now()});}
 if(a==="review_en_draft_status"){const task=String(p.task_id||"");if(!valid(task))return out("review_en_draft_status",{ok:false,error:"invalid_task_id"});const r=await allEdits(task),rid=String(p.request_id||""),at=r.receipts[rid]||"";return out("review_en_draft_status",{ok:true,task_id:task,request_id:rid,committed:!!at,saved_at:at,confirmed_count:Object.keys(r.edits).length,...(p.include_edits==="1"?{edits:r.edits}:{})});}
 return out("bridge_error",{ok:false,error:"not_yet_restored",message:a+" 暫時無法使用，沒有修改資料"});
}
async function write(p){
 if(p.action==="run_stage"){
  if(p.stage==="cc" && p.lang!=="multi-audio"){
   try{return out("run_stage",await youtubeCCQueue.enqueue(p));}
   catch(error){
    const message=String(error.message||error);
    return out("run_stage",{ok:false,task_id:p.task_id||"",
     stage:"cc",error:message,message:"CC 無法加入佇列："+message});
   }
  }
  if(p.stage!=="multi")return out("run_stage",{ok:false,task_id:p.task_id||"",
   stage:p.stage||"",error:"stage_not_restored",
   message:"目前只恢復各國語言文字翻譯派工；音檔與其他階段尚未接回"});
  try{return out("run_stage",await translationQueue.enqueue(p));}
  catch(error){
   const message=String(error.message||error);
   return out("run_stage",{ok:false,task_id:p.task_id||"",
    stage:p.stage||"",error:message,message:"無法建立翻譯工作："+message});
  }
 }
 if(p.action==="review_save" && p.kind==="zh"){
  const saved=await chineseFinalStore.save(p);
  // Only after the entire Chinese manuscript is independently read back,
  // confirm the current task's Chinese stage as completed.
  const rows=await get(N.tasks,"A1:J5000");
  const index=rows.findIndex((row,i)=>i>0&&row[0]===p.task_id);
  if(index<1)throw Error("chinese_final_task_not_registered");
  if(String(rows[index][8]||"")!=="完成")
   await put(N.tasks,"I"+(index+1),[["完成"]]);
  await put(N.status,"A:M",[[
   p.task_id,"zh","done","sheet-zh-"+saved.revision.slice(0,12),"100",
   "中文中央定稿已回讀驗證；Drive 待同步","",now(),now(),"","",saved.revision,saved.revision
  ]],true);
  return saved;
 }
 if(p.action==="review_en_draft_save")return saveEnglish(p);
 if(p.action==="review_save" && p.kind==="en")return saveFullEnglishFinal(p);
 return out(({tasks_upsert:"tasks_saved",language_plan_save:"language_plan_saved",task_reschedule:"task_rescheduled",review_save:"review_saved",run_stage:"run_stage"}[p.action]||"bridge_error"),{ok:false,error:"not_yet_restored",message:"這項寫入尚在修復，沒有修改資料"});}
function send(res,data,status=200,jsonp){if(jsonp&&/^[a-zA-Z_$][\w.$]{0,120}$/.test(jsonp)){res.writeHead(200,{"content-type":"application/javascript; charset=utf-8","cache-control":"no-store"});res.end(jsonp+"("+JSON.stringify(data)+");");return;}res.writeHead(status,{"content-type":"application/json; charset=utf-8","cache-control":"no-store"});res.end(JSON.stringify(data));}
http.createServer(async(req,res)=>{let p={};try{if(req.headers.origin==="https://staney41011.github.io"){res.setHeader("Access-Control-Allow-Origin",req.headers.origin);res.setHeader("Vary","Origin");res.setHeader("Access-Control-Allow-Methods","GET,POST,OPTIONS");res.setHeader("Access-Control-Allow-Headers","Content-Type");}if(req.method==="OPTIONS"){res.writeHead(204);res.end();return;}
 if(req.method==="GET"){p=Object.fromEntries(new URL(req.url,"http://localhost").searchParams);if(!p.action){send(res,{ok:true,service:"SoulKey Studio Cloud Bridge",message:"bridge-ready",build:String(process.env.SOULKEY_BUILD_SHA||"unversioned"),source_capabilities:["translation-chunks","youtube-cc-sheet","chinese-sheet-final","english-sheet-final"]});return;}}
 else if(req.method==="POST"){let size=0,buff=[];for await(const part of req){size+=part.length;if(size>1000000)throw Error("payload_too_large");buff.push(part);}p=Object.fromEntries(new URLSearchParams(Buffer.concat(buff).toString("utf8")));}else{send(res,{error:"method_not_allowed"},405);return;}
 // The Google ingress adds the peer and proxy at the end of XFF.
 // Prefer the penultimate peer to avoid trusting a user-supplied first hop.
 const peers=String(req.headers["x-forwarded-for"]||"").split(",").map(x=>x.trim()).filter(Boolean);
 const address=String(peers.length>=2?peers[peers.length-2]:(peers[0]||req.socket.remoteAddress||"unknown"));
 if(bridgeAuth.isBlocked(address)){
   send(res,out(p.action==="status_health"?"status_health":"bridge_error",
    {ok:false,error:"rate_limited",message:"登入嘗試過多，請稍後再試"}),429,p.callback);
   return;
 }
 // Signed GitHub OIDC is the sole path for background worker queue access.
 // Never accept a user-supplied task ID as authentication.
 if(["worker_job_claim","worker_job_part","worker_job_report","worker_cc_claim","worker_cc_part","worker_cc_finish"].includes(p.action)){
   try{
    if(req.method!=="POST")throw Error("worker_post_required");
    const bearer=String(req.headers.authorization||"").match(/^Bearer (.+)$/i);
    await verifyGithubWorker(bearer?.[1],String(p.action||"").startsWith("worker_cc_")?"cc":"translation");
    let result;
    if(p.action==="worker_job_claim")result=await translationQueue.claim();
    else if(p.action==="worker_job_part")result=await translationQueue.part(p);
    else if(p.action==="worker_job_report")result=await translationQueue.report(p);
    else if(p.action==="worker_cc_claim")result=await youtubeCCQueue.claim();
    else if(p.action==="worker_cc_part")result=await youtubeCCQueue.part(p);
    else result=await youtubeCCQueue.finish(p);
    send(res,out(p.action,result),result.ok===false?409:200);
   }catch(error){
    console.error("Worker queue request rejected",String(error.message||error).slice(0,110));
    send(res,out(p.action,{ok:false,error:"worker_auth_or_queue_failed",
     message:"GitHub Worker 驗證或中央佇列請求失敗"}),401);
   }
   return;
 }
 if(!ok(p.bridge_key)){
   const limited=bridgeAuth.noteFailure(address);
   send(res,out(p.action==="status_health"?"status_health":"bridge_error",{ok:false,error:limited?"rate_limited":"unauthorized",message:limited?"登入嘗試過多，請稍後再試":"Bridge Key 不正確"}),limited?429:401,p.callback);
   return;
 }
 const readActions=new Set(["status_health","tasks_get","language_settings","language_plan_get","status","status_batch","review_en_draft_status","review_load","youtube_capture_files","youtube_cc_content","course_files","tts_share_links","drive_owner_probe","review_final_status"]);
 const data=req.method==="GET"||readActions.has(String(p.action||""))?await read(p):await write(p);
 send(res,data,data.ok===false?409:200,p.callback);
 }catch(e){
  const message=String(e.message||e).slice(0,200);
  console.error("Bridge failure",message);
  const isFiles=p.action==="course_files" || p.action==="tts_share_links";
  const isReview=p.action==="review_load";
  const isEnglishSave=p.action==="review_en_draft_save";
  const isFinalSave=p.action==="review_save";
  let requestId="";
  if(isEnglishSave)try{requestId=String(JSON.parse(p.payload_json||"{}").save_request_id||"");}catch(_){}
  const conflict=/^edit_conflict_reload_required_/.test(message);
  const type=isFiles?String(p.action):isFinalSave?"review_saved":isEnglishSave?"english_review_draft_saved":isReview?"review_data":p.action==="status_health"?"status_health":"bridge_error";
  send(res,out(type,{ok:false,error:conflict?"edit_conflict_reload_required":"bridge_exception",message,
    ...(isFinalSave?{task_id:String(p.task_id||""),kind:String(p.kind||"")}:{}),
    ...(isFiles?{task_id:String(p.task_id||""),groups:[],total_files:0}:{}),
    ...(isEnglishSave?{task_id:String(p.task_id||""),request_id:requestId}:{}),
    ...(isReview?{task_id:String(p.task_id||""),kind:String(p.kind||"")}: {})}),conflict?409:500,p.callback);
 }
}).listen(Number(process.env.PORT)||8080,"0.0.0.0",()=>console.log("SoulKey bridge ready"));
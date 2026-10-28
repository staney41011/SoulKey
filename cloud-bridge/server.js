"use strict";
const http=require("node:http"),{GoogleAuth}=require("google-auth-library");
const {createBridgeAuth}=require("./auth");
const {createDriveReview}=require("./drive-review");
const {createEnglishFinalBackup}=require("./english-final-backup");
const ID="1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8";
const N={tasks:"任務佇列",status:"執行狀態",lang:"語言設定",plans:"語言任務設定",edits:"英文人工定稿"};
const key=process.env.BRIDGE_KEY||"",source="soulkey-bridge";
const bridgeAuth=createBridgeAuth({primaryKey:key,legacyHmac:process.env.BRIDGE_LEGACY_HMAC||""});
const auth=new GoogleAuth({scopes:["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive.readonly"]});
let client;async function google(method,url,body){client??=await auth.getClient();return(await client.request({method,url:"https://sheets.googleapis.com/v4/spreadsheets/"+ID+"/"+url,data:body,timeout:20000})).data;}
const range=(sheet,a)=>encodeURIComponent("'"+sheet+"'!"+a);
async function get(s,a="A1:Z10000"){return(await google("GET","values/"+range(s,a)+"?valueRenderOption=FORMATTED_VALUE")).values||[];}
async function put(s,a,rows,append=false){return google(append?"POST":"PUT","values/"+range(s,a)+(append?":append?valueInputOption=RAW&insertDataOption=INSERT_ROWS":"?valueInputOption=RAW"),{values:rows,majorDimension:"ROWS"});}
const driveReview=createDriveReview(auth,get);
let finalBackupTabReady=null;
async function ensureBackupTab(title,headers){
 if(finalBackupTabReady)return finalBackupTabReady;
 finalBackupTabReady=(async()=>{
  const m=await google("GET","?fields=sheets.properties.title");
  if(!(m.sheets||[]).some(s=>s.properties.title===title)){
   await google("POST",":batchUpdate",{requests:[{addSheet:{properties:{title}}}]});
   await put(title,"A1:G1",[headers]);
  }
 })();
 try{await finalBackupTabReady;}catch(e){finalBackupTabReady=null;throw e;}
}
const englishFinalBackup=createEnglishFinalBackup({
 get,put,ensureTab:ensureBackupTab
});
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
async function read(p){const a=p.action;if(a==="course_files")return driveReview.courseFiles(p);if(a==="tts_share_links")return driveReview.ttsShareLinks(p);if(a==="review_load")return driveReview.review(p);if(a==="status_health"){const rows=await get(N.status,"A1:A10000");return out("status_health",{ok:true,sheet:N.status,rows:Math.max(rows.length-1,0),bridge_protocol:"cloud-recovery",youtube_cookies_configured:false,server_time:now()});}
 if(a==="tasks_get")return out("tasks_result",{ok:true,tasks:await tasks(),server_time:now()});
 if(a==="language_settings")return out("language_settings",{ok:true,languages:await langs(),server_time:now()});
 if(a==="language_plan_get")return out("language_plan",{ok:true,task_id:p.task_id||"",plan:await plans(String(p.task_id||""))});
 if(a==="status"||a==="status_batch"){const ids=String(p.task_ids||p.task_id||"").split(",").filter(valid).slice(0,20);return out("status_result",{ok:!!ids.length,tasks:await status(ids),server_time:now()});}
 if(a==="review_en_draft_status"){const task=String(p.task_id||"");if(!valid(task))return out("review_en_draft_status",{ok:false,error:"invalid_task_id"});const r=await allEdits(task),rid=String(p.request_id||""),at=r.receipts[rid]||"";return out("review_en_draft_status",{ok:true,task_id:task,request_id:rid,committed:!!at,saved_at:at,confirmed_count:Object.keys(r.edits).length,...(p.include_edits==="1"?{edits:r.edits}:{})});}
 return out("bridge_error",{ok:false,error:"not_yet_restored",message:a+" 暫時無法使用，沒有修改資料"});
}
async function write(p){if(p.action==="review_en_draft_save")return saveEnglish(p);if(p.action==="review_save" && p.kind==="en")return englishFinalBackup.save(p);return out(({tasks_upsert:"tasks_saved",language_plan_save:"language_plan_saved",task_reschedule:"task_rescheduled",review_save:"review_saved",run_stage:"run_stage"}[p.action]||"bridge_error"),{ok:false,error:"not_yet_restored",message:"這項寫入尚在修復，沒有修改資料"});}
function send(res,data,status=200,jsonp){if(jsonp&&/^[a-zA-Z_$][\w.$]{0,120}$/.test(jsonp)){res.writeHead(200,{"content-type":"application/javascript; charset=utf-8","cache-control":"no-store"});res.end(jsonp+"("+JSON.stringify(data)+");");return;}res.writeHead(status,{"content-type":"application/json; charset=utf-8","cache-control":"no-store"});res.end(JSON.stringify(data));}
http.createServer(async(req,res)=>{let p={};try{if(req.headers.origin==="https://staney41011.github.io"){res.setHeader("Access-Control-Allow-Origin",req.headers.origin);res.setHeader("Vary","Origin");res.setHeader("Access-Control-Allow-Methods","GET,POST,OPTIONS");res.setHeader("Access-Control-Allow-Headers","Content-Type");}if(req.method==="OPTIONS"){res.writeHead(204);res.end();return;}
 if(req.method==="GET"){p=Object.fromEntries(new URL(req.url,"http://localhost").searchParams);if(!p.action){send(res,{ok:true,service:"SoulKey Studio Cloud Bridge",message:"bridge-ready"});return;}}
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
 if(!ok(p.bridge_key)){
   const limited=bridgeAuth.noteFailure(address);
   send(res,out(p.action==="status_health"?"status_health":"bridge_error",{ok:false,error:limited?"rate_limited":"unauthorized",message:limited?"登入嘗試過多，請稍後再試":"Bridge Key 不正確"}),limited?429:401,p.callback);
   return;
 }
 const readActions=new Set(["status_health","tasks_get","language_settings","language_plan_get","status","status_batch","review_en_draft_status","review_load","course_files","tts_share_links"]);
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
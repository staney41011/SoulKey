"use strict";
const crypto=require("node:crypto");
const DRIVE="https://www.googleapis.com/drive/v3/files";
const UPLOAD="https://www.googleapis.com/upload/drive/v3/files";
const MANIFEST_ID=/^[A-Za-z0-9_-]{12,}$/;
function ownerAuth(){
 const id=String(process.env.GOOGLE_OWNER_CLIENT_ID||"").trim();
 const secret=String(process.env.GOOGLE_OWNER_CLIENT_SECRET||"").trim();
 const refresh=String(process.env.GOOGLE_OWNER_REFRESH_TOKEN||"").trim();
 if(!id||!secret||!refresh)return null;
 const {OAuth2Client}=require("google-auth-library");
 const client=new OAuth2Client(id,secret);
 client.setCredentials({refresh_token:refresh});
 return client;
}
function pad(n){return String(Math.max(0,Math.floor(n))).padStart(2,"0");}
function srtClock(t){
 const ms=Math.max(0,Math.round(Number(t||0)*1000));
 const secs=Math.floor(ms/1000);
 return pad(Math.floor(secs/3600))+":"+pad(Math.floor(secs%3600/60))+":"+
  pad(secs%60)+","+String(ms%1000).padStart(3,"0");
}
function outputs(manuscript){
 const segments=manuscript.segments.map(x=>({
  id:x.id,start:x.start,end:x.end,text:x.text
 }));
 const final=new Date().toISOString();
 const txt=segments.map(x=>x.text).join("\n");
 const srt=segments.map((x,i)=>
  String(i+1)+"\n"+srtClock(x.start)+" --> "+srtClock(Math.max(x.start+0.01,x.end))+
   "\n"+x.text+"\n").join("\n");
 return [
  {name:"en.final.json",mime:"application/json",value:JSON.stringify({
    language:"English Final",finalized_at:final,segments,
    learned_terms:Array.isArray(manuscript.learned_terms)?manuscript.learned_terms:[]
   },null,2)},
  {name:"en.final.txt",mime:"text/plain",value:txt},
  {name:"en.final.srt",mime:"text/plain",value:srt}
 ];
}
function bodyMeta(meta,mime,contents){
 const b="soulkey-"+crypto.randomBytes(12).toString("hex");
 const body=Buffer.concat([
  Buffer.from("--"+b+"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"+JSON.stringify(meta)+"\r\n"),
  Buffer.from("--"+b+"\r\nContent-Type: "+mime+"; charset=UTF-8\r\n\r\n"),
  Buffer.from(contents,"utf8"),
  Buffer.from("\r\n--"+b+"--\r\n")
 ]);
 return {body,boundary:b};
}
function createDriveFinalPublisher({authFactory=ownerAuth,resolveFolders,get,put}){
 const client=authFactory();
 const isConfigured=()=>!!client;
 async function request(opts){
  if(!client)throw Error("owner_drive_authorization_not_configured");
  const response=await client.request({timeout:50000,...opts});
  return response.data;
 }
 async function media(id){
  if(!MANIFEST_ID.test(id))throw Error("invalid_drive_id");
  const raw=await request({method:"GET",url:DRIVE+"/"+encodeURIComponent(id)+"?alt=media&supportsAllDrives=true"});
  return typeof raw==="string"?raw:JSON.stringify(raw,null,2);
 }
 async function list(folder){
  const q=new URLSearchParams({
   q:"'"+folder+"' in parents and trashed = false",
   fields:"nextPageToken,files(id,name,mimeType,description,parents)",
   pageSize:"1000",supportsAllDrives:"true",includeItemsFromAllDrives:"true"
  });
  const data=await request({method:"GET",url:DRIVE+"?"+q});
  return data.files||[];
 }
 function marker(task,name){return "soulkey:canonical="+name+";task="+task;}
 async function write(folder,task,file){
  if(!MANIFEST_ID.test(folder))throw Error("invalid_drive_folder");
  const files=await list(folder);
  const found=files.find(f=>f.name===file.name||
   String(f.description||"").includes(marker(task,file.name)));
  // An existing final is never deleted. Google Drive retains file revisions
  // on in-place updates.
  if(found){
   const current=await media(found.id);
   if(current===file.value)return {id:found.id,url:"https://drive.google.com/file/d/"+found.id+"/view",unchanged:true};
  }
  const meta={name:file.name,mimeType:file.mime,description:marker(task,file.name)};
  if(!found)meta.parents=[folder];
  const {body,boundary}=bodyMeta(meta,file.mime,file.value);
  const result=await request({
   method:found?"PATCH":"POST",
   url:UPLOAD+(found?"/"+encodeURIComponent(found.id):"")+"?uploadType=multipart&supportsAllDrives=true&fields=id,name",
   headers:{"Content-Type":"multipart/related; boundary="+boundary},
   data:body
  });
  if(!result.id)throw Error("drive_write_missing_file_id");
  const readback=await media(result.id);
  // JSON is normalized by Google API transport in some Node versions.
  const verified=file.mime==="application/json"?
    crypto.createHash("sha256").update(JSON.stringify(JSON.parse(readback))).digest("hex")===
    crypto.createHash("sha256").update(JSON.stringify(JSON.parse(file.value))).digest("hex"):
    readback===file.value;
  if(!verified)throw Error("drive_final_readback_mismatch:"+file.name);
  return {id:result.id,url:"https://drive.google.com/file/d/"+result.id+"/view",unchanged:false};
 }
 async function probe(task){
  if(!isConfigured())return {ok:false,error:"owner_drive_authorization_not_configured"};
  const folders=await resolveFolders(task);
  const resp=await request({method:"GET",url:DRIVE+"/"+encodeURIComponent(folders.translation)+
   "?fields=id,capabilities(canAddChildren)&supportsAllDrives=true"});
  return {ok:!!resp.id && resp.capabilities?.canAddChildren===true,
   can_add_children:resp.capabilities?.canAddChildren===true,
   message:resp.capabilities?.canAddChildren===true
    ?"已驗證 Google Drive 寫入授權":"授權帳號沒有此課程的資料夾編輯權限"};
 }
 async function publish(task,manuscript){
  if(!isConfigured())return {ok:false,error:"owner_drive_authorization_not_configured"};
  const folders=await resolveFolders(task);
  const folder=folders.translation;
  const generated=outputs(manuscript);
  const files={};
  for(const f of generated)files[f.name]=await write(folder,task,f);
  if(Object.keys(files).length!==3)throw Error("incomplete_final_outputs");
  // Only after verifying all three Drive files, mark the lesson as finalized.
  const rows=await get("任務佇列","A1:J5000");
  const rowIndex=rows.findIndex((r,i)=>i>0&&r[0]===task);
  if(rowIndex===-1)throw Error("task_not_registered");
  await put("任務佇列","J"+(rowIndex+1),[["完成"]]);
  const stamp=new Date().toISOString();
  await put("任務佇列","S"+(rowIndex+1)+":T"+(rowIndex+1),[[stamp,"英文人工定稿完成"]]);
  // Schema order is from the system's 13-column status table.
  const check=await get("執行狀態","A1:M20000");
  const header=check[0]||[];
  const at=Object.fromEntries(header.map((x,i)=>[x,i]));
  const statusRow=Array(header.length).fill("");
  const data={task_id:task,stage:"en-review",status:"done",
   run_id:"human-"+Date.now(),progress:100,message:"English Final saved and read back from Google Drive",
   finished_at:stamp,updated_at:stamp};
  for(const [k,v] of Object.entries(data))if(at[k]!==undefined)statusRow[at[k]]=v;
  const old=check.slice(1).some(x=>x[at.task_id]===task&&x[at.stage]==="en-review"&&x[at.status]==="done");
  if(!old)await put("執行狀態","A:M",[statusRow],true);
  return {ok:true,task_id:task,kind:"en",drive_saved:true,files,
   finalized_at:stamp,source:"soulkey-bridge",type:"review_saved",
   message:"English Final 已寫入 Google Drive（JSON、TXT、SRT）並完成回讀驗證"};
 }
 return {publish,probe,isConfigured};
}
module.exports={ownerAuth,createDriveFinalPublisher,outputs};

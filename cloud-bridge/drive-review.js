"use strict";
const {createDriveOverview}=require("./drive-overview");
const ROOT="https://www.googleapis.com/drive/v3/files";
const ID_RE=/^[a-zA-Z0-9_-]{12,}$/;
const TASK_RE=/^P(\d+)-L(\d{2})$/i;
const FOLDER="application/vnd.google-apps.folder";
const fmtTime=x=>{const t=Math.max(0,Math.floor(Number(x)||0));return [Math.floor(t/3600),Math.floor(t%3600/60),t%60].map(a=>String(a).padStart(2,"0")).join(":");};
const cache=new Map();
function cached(key,load,ttl=180000){
 const old=cache.get(key);
 if(old&&Date.now()-old.at<ttl)return Promise.resolve(old.value);
 return load().then(value=>{cache.set(key,{at:Date.now(),value});return value;});
}
function createDriveReview(auth,get){
 let client;
 async function drive(url){
  client??=await auth.getClient();
  return (await client.request({method:"GET",url,timeout:19000})).data;
 }
 async function children(parent){
  if(!ID_RE.test(parent))throw Error("invalid_drive_folder_id");
  return cached("dir:"+parent,async()=>{
   const result=[];
   let pageToken="";
   for(let page=0;page<8;page++){
    const q=new URLSearchParams({
      q:"'"+parent+"' in parents and trashed = false",
      fields:"nextPageToken,files(id,name,mimeType,size,description,webViewLink,modifiedTime)",
      pageSize:"1000",supportsAllDrives:"true",includeItemsFromAllDrives:"true"
    });
    if(pageToken)q.set("pageToken",pageToken);
    const data=await drive(ROOT+"?"+q.toString());
    result.push(...(data.files||[]));
    if(!data.nextPageToken)break;
    pageToken=data.nextPageToken;
   }
   return result;
  });
 }
 function folder(items,name){
  const item=items.find(f=>f.mimeType===FOLDER && f.name===name);
  if(!item)throw Error("missing_folder:"+name);
  return item.id;
 }
 async function context(task){
  const m=TASK_RE.exec(String(task||""));
  if(!m)throw Error("invalid_task_id");
  const period=Number(m[1]),lesson=Number(m[2]);
  const rows=await get("期數設定","A1:G1000");
  const row=rows.slice(1).find(r=>{
   const p1=Number((String(r[0]||"").match(/\d+/)||[])[0]);
   const p2=Number((String(r[1]||"").match(/\d+/)||[])[0]);
   return p1===period||p2===period;
  });
  if(!row)throw Error("period_not_found");
  const value=String(row[5]||"");
  const match=/\/folders\/([a-zA-Z0-9_-]+)/.exec(value)||([ID_RE.test(value),value]);
  if(!match||!ID_RE.test(match[1]))throw Error("period_folder_missing");
  const p=match[1];
  const c=folder(await children(p),"01_課程");
  const l=folder(await children(c),String(lesson).padStart(2,"0")+"_第"+lesson+"堂");
  const folders=await children(l);
  return {lesson:l,source:folder(folders,"00_來源資訊"),
   transcript:folder(folders,"01_中文逐字稿"),
   translation:folder(folders,"02_翻譯稿"),
   audio:folder(folders,"04_音檔"),
   video:folder(folders,"05_完成影片")};
 }
 async function filesOf(p){return children(p);}
 function findFile(files,canonical){
  const original=files.find(f=>f.mimeType!==FOLDER && f.name===canonical);
  if(original)return original;
  const suffix="_"+canonical;
  const byName=files.find(f=>f.mimeType!==FOLDER && f.name.endsWith(suffix));
  if(byName)return byName;
  const byDesc=files.find(f=>f.mimeType!==FOLDER &&
   String(f.description||"").includes(canonical));
  if(byDesc)return byDesc;
  const zhAlias={
   "zh-TW.final.json":/_中文人工定稿資料\.json$/,
   "zh-TW.review.manifest.json":/zh-TW\.review\.manifest\.json$/,
   "en.final.json":/_英文人工定稿資料\.json$/,
   "youtube.en.json":/_英文CC資料\.json$/
  };
  return zhAlias[canonical]?
    (files.find(f=>f.mimeType!==FOLDER&&zhAlias[canonical].test(f.name))||null):null;
 }
 async function jsonFile(p,canonical){
  const files=await filesOf(p),item=findFile(files,canonical);
  if(!item)return null;
  const obj=await drive(ROOT+"/"+encodeURIComponent(item.id)+"?alt=media&supportsAllDrives=true");
  if(typeof obj==="string")return JSON.parse(obj);
  if(obj && typeof obj==="object")return obj;
  throw Error("invalid_json_file:"+canonical);
 }
 const err=(task,kind,message,code="review_files_missing")=>({
  source:"soulkey-bridge",type:"review_data",ok:false,task_id:task,
  kind,error:code,message});
 function overlap(original,start,end,id){
  const hit=original.filter(s=>Number(s.end||s.start||0)>start &&
    Number(s.start||0)<end).map(s=>String(s.text||"").trim()).filter(Boolean);
  if(hit.length)return hit.join("");
  return String((original.find((s,i)=>Number(s.id??i)===id)||{}).text||"");
 }
function uniqueEnglish(prev,text){
 const newWords=String(text||"").replace(/\s+/g," ").trim().split(" ").filter(Boolean);
 if(!newWords.length)return "";
 const oldWords=String(prev||"").split(" ").filter(Boolean).slice(-70);
 const norm=x=>x.toLowerCase().replace(/^[^a-z0-9]+|[^a-z0-9]+$/g,"");
 let duplicate=0;
 for(let i=Math.min(oldWords.length,newWords.length,40);i>=3;i--){
  const end=oldWords.slice(-i).map(norm);
  const start=newWords.slice(0,i).map(norm);
  if(end.every(Boolean)&&start.every(Boolean)&&end.join(" ")===start.join(" ")){
   duplicate=i;break;
  }
 }
 return newWords.slice(duplicate).join(" ");
}
function ccRows(chinese,cues){
 let history="";
 return chinese.map((item,i)=>{
  const id=Number(item.id??i),start=Number(item.start||0),end=Number(item.end||start);
  const matched=[],seen=new Set();
  for(const cue of cues){
   const from=Number(cue.start||0),to=Number(cue.end||from);
   if(to<=start||from>=end)continue;
   const text=String(cue.text||"").replace(/\s+/g," ").trim();
   if(text&&!seen.has(text)){matched.push(text);seen.add(text);}
  }
  const clipped=uniqueEnglish(history,matched.join(" "));
  if(clipped)history=(history+" "+clipped).trim().split(" ").slice(-80).join(" ");
  return {id,start,end,time:fmtTime(start),original:String(item.text||""),
   vernacular:"",en:clipped,source_en:clipped,en_confirmed:false,
   ids:[id],terms:[]};
 });
}
 async function review(p){
  const task=String(p.task_id||""),kind=String(p.kind||"");
  if(!TASK_RE.test(task))return err(task,kind,"課程編號不正確","invalid_task_id");
  const begin=Date.now(),ids=await context(task);
  if(kind==="zh"){
   const manifest=await jsonFile(ids.transcript,"zh-TW.review.manifest.json");
   if(!manifest || !Array.isArray(manifest.first_chunk))
    return err(task,kind,"找不到中文校稿快取，請檢查雲端資料");
   const count=Math.max(1,Number(manifest.chunk_count||1));
   const idx=Math.min(Math.max(0,Number(p.chunk_index||0)||0),count-1);
   const item=idx===0?manifest:await jsonFile(ids.transcript,"zh-TW.review."+String(idx).padStart(3,"0")+".json");
   return {source:"soulkey-bridge",type:"review_data",ok:true,task_id:task,kind,
    chunk_index:idx,chunk_count:count,total_segments:Number(manifest.total_segments||0),
    has_more:idx<count-1,segments:idx===0?manifest.first_chunk:(item?.segments||[]),
    load_ms:Date.now()-begin};
  }
  if(kind==="en"){
   const original=await jsonFile(ids.transcript,"zh-TW.final.json");
   if(!Array.isArray(original?.segments)||!original.segments.length)
    return err(task,kind,"這堂課尚未有中文人工定稿");
   const source=original.segments;
   for(const [canonical,tag] of [["en.final.json","final"],["en.review.draft.json","draft"],["en.json","machine"]]){
    const english=await jsonFile(ids.translation,canonical);
    if(!Array.isArray(english?.segments)||!english.segments.length)continue;
    const rows=english.segments.map((s,i)=>{
     const id=Number(s.id??i),start=Number(s.start||0),end=Number(s.end||start);
     const chinese=tag==="draft"?String(s.text||"")||overlap(source,start,end,id):overlap(source,start,end,id);
     return {id,start,end,time:String(s.time||fmtTime(start)),
      original:chinese,vernacular:"",
      en:String(tag==="draft"?(s.en_text??s.source_en??""):s.text||""),
      source_en:String(s.source_en||""),en_confirmed:tag==="final"||s.en_confirmed===true,
      pre_aligned:s.pre_aligned===true,
      ids:Array.isArray(s.zh_ids)?s.zh_ids.map(Number):[id],terms:[]};
    });
    return {source:"soulkey-bridge",type:"review_data",ok:true,task_id:task,kind,
     manuscript_source:canonical,load_ms:Date.now()-begin,segments:rows};
   }
   const cc=await jsonFile(ids.source,"youtube.en.json");
   if(Array.isArray(cc?.segments)&&cc.segments.length){
    const rows=ccRows(source,cc.segments);
    if(rows.some(x=>x.en.trim()))return {
     source:"soulkey-bridge",type:"review_data",ok:true,task_id:task,kind,
     manuscript_source:"youtube.en.json",needs_human_review:true,
     load_ms:Date.now()-begin,segments:rows};
   }
   return err(task,kind,"中文定稿已保存，但尚未產生英文稿或可用的 English CC");
  }
  return err(task,kind,"尚未支援這種類型的校稿資料","unsupported_review_kind");
 }
 const overview=createDriveOverview({children,context,getJsonFile:async id=>{
  if(!ID_RE.test(id))throw Error("invalid_audio_report_id");
  return cached("report:"+id,async()=>{
   const result=await drive(ROOT+"/"+encodeURIComponent(id)+"?alt=media&supportsAllDrives=true");
   return typeof result==="string"?JSON.parse(result):result;
  },180000);
 }});
 return {review,resolveFolders:context,invalidateFolder:id=>cache.delete("dir:"+String(id||"")),courseFiles:overview.courseFiles,ttsShareLinks:overview.ttsShareLinks};
}
module.exports={createDriveReview};

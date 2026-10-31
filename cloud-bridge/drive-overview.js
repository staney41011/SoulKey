"use strict";
// Read-only Google Drive lesson deliverables. Files are returned from Drive
// metadata, never guessed from a task ID or a filename convention.
const LANG={
 "中文":"zh-TW","英文":"en","泰文":"th","西班牙文":"es","印尼文":"id",
 "越南文":"vi","高棉文":"km","印地語":"hi","信德文":"hi",
 "泰米爾文":"ta","日文":"ja","韓文":"ko","孟加拉文":"bn",
 "尼泊爾文":"ne","寮文":"lo","緬甸文":"my","義大利文":"it","葡萄牙文":"pt"
};
const codes=["zh-TW","en","th","es","id","vi","km","hi","ta","ja","ko","bn","ne","lo","my","it","pt"];
const shareCodes=codes.filter(code=>code!=="zh-TW");
const FOLDER="application/vnd.google-apps.folder";
const url=id=>"https://drive.google.com/file/d/"+id+"/view";
const folderUrl=id=>"https://drive.google.com/drive/folders/"+id;
function createDriveOverview({children,context,getJsonFile=null}){
 function filesOf(all){return (all||[]).filter(x=>x.mimeType!==FOLDER &&
   /^[a-zA-Z0-9_-]{12,}$/.test(String(x.id||"")));}
 function languageFromName(name){
  const raw=String(name||"");
  for(const [label,code] of Object.entries(LANG)){
   if(raw.includes(label))return code;
  }
  const base=raw.match(/(?:^|_)(zh-TW|en|th|es|id|vi|km|hi|ta|ja|ko|bn|ne|lo|my|it|pt)(?:\.preview)?\.(?:txt|mp3)$/i);
  return base?.[1]?.toLowerCase()==="zh-tw"?"zh-TW":(base?.[1]?.toLowerCase()||"");
 }
 function canonicalText(name,code){
  const n=String(name||"");
  if(!code||!/\.txt$/i.test(n))return "";
  if(n.endsWith(code+".final.txt"))return code+".final.txt";
  if(/中文人工定稿時間軸|英文人工定稿時間軸|人工定稿時間軸|最終逐字稿|正式逐字稿/i.test(n))return code+".final.txt";
  if(/中文純逐字稿|中文ASR時間軸|中文潤稿時間軸/i.test(n))
   return code+(n.includes("純逐字稿")?".transcript.txt":".readable.txt");
  if(/英文CC|youtube\.en\./i.test(n))return code+".transcript.txt";
  if(/翻譯稿|逐字稿|時間軸|\.txt$/i.test(n))return code+".txt";
  return "";
 }
 function audioKind(name){
  const n=String(name||"");
  if(!/\.mp3$/i.test(n))return null;
  const code=languageFromName(n);
  if(!code||code==="zh-TW")return null;
  const preview=/(?:\.preview\.mp3|試聽|預覽)/i.test(n);
  const official=/^(?:zh-TW|en|th|es|id|vi|km|hi|ta|ja|ko|bn|ne|lo|my|it|pt)\.mp3$/i.test(n) ||
    /TTS音檔\.mp3$/i.test(n);
  if(!preview&&!official)return null; // exclude YouTube source audio
  return {code,preview,canonical_name:code+(preview?".preview.mp3":".mp3")};
 }
 function item(file,key,label,canonical="",preview=false){
  return {id:file.id,name:String(file.name||""),
   canonical_name:canonical,display_name:String(file.name||""),
   url:url(file.id),size:Number(file.size||0),
   updated_at:String(file.modifiedTime||""),
   group_key:key,group_label:label,
   ...(key==="audio"?{
     needs_timing_review:preview,
     audio_kind:preview?"standalone_preview":"formal_aligned"
   }:{})};
 }
 function pickNewest(items){return items.slice().sort((a,b)=>
  String(b.updated_at).localeCompare(String(a.updated_at)))[0]||null;}
 async function scan(task){
  const ids=await context(task);
  const [source,zh,translations,audio,video]=await Promise.all([
   children(ids.source),children(ids.transcript),children(ids.translation),
   children(ids.audio),children(ids.video)
  ]);
  const transcriptPool=filesOf([...source,...zh,...translations])
   .filter(f=>/\.txt$/i.test(f.name||"")).map(f=>{
    const lang=languageFromName(f.name);
    if(!lang)return null;
    const canonical=canonicalText(f.name,lang);
    const rank=canonical===lang+".final.txt"?100:
      canonical===lang+".readable.txt"?80:
      canonical===lang+".transcript.txt"?60:40;
    return {...item(f,"transcript","逐字稿",canonical),lang,rank};
   }).filter(Boolean);
  const transcriptFiles=codes.map(lang=>{
   const items=transcriptPool.filter(x=>x.lang===lang)
    .sort((a,b)=>b.rank-a.rank||String(b.updated_at).localeCompare(String(a.updated_at)));
   const best=items[0];if(!best)return null;
   const {lang:_,rank:__,...entry}=best;
   return entry;
  }).filter(Boolean);
  // TTS reports may explicitly show natural, unaligned audio that is
  // substantially shorter than the source lesson. Do not advertise such a
  // rendition as a synchronized official MP3 merely because the name is formal.
  const reports={};
  if(getJsonFile){
   const candidates=filesOf(audio).filter(f=>/TTS對齊報告\.json$|\.alignment\.json$/i.test(f.name||""));
   await Promise.all(candidates.map(async f=>{
    const lang=languageFromName(f.name);
    if(!lang)return;
    try {
     const report=await getJsonFile(f.id);
     const timeline=report?.timeline||{};
     const sourceDuration=Number(timeline.source_duration);
     const finalDuration=Number(timeline.final_duration);
     if(sourceDuration>0 && finalDuration>0){
      const ratio=finalDuration/sourceDuration;
      // Below 90% or above the full source length needs human timing review.
      // Also honor the backend's explicit review flag.
      const short=ratio<0.90, long=ratio>1.02;
      const review=short||long||timeline.needs_review===true;
      if(review)reports[lang]={
       review:true,
       reason:short?"配音比原影片短 "+Math.round((1-ratio)*100)+"%":
         long?"配音超過原影片時長":"音檔對時尚未完成"
      };
     }
    }catch(_){ /* A missing report must never hide an existing audio file. */ }
   }));
  }
  const audioPool=filesOf(audio).map(f=>{
   const meta=audioKind(f.name);
   if(!meta)return null;
   const lengthReport=reports[meta.code]||{};
   const needsReview=meta.preview||Boolean(lengthReport.review);
   const entry=item(f,"audio","音檔",meta.canonical_name,needsReview);
   if(needsReview && !meta.preview){
    entry.audio_kind="length_review";
    entry.timing_review_reason=lengthReport.reason||"音檔對時尚未完成";
   }
   return {...entry,lang:meta.code,preview:meta.preview};
  }).filter(Boolean);
  const audioFiles=codes.filter(x=>x!=="zh-TW").flatMap(lang=>{
   const official=pickNewest(audioPool.filter(f=>f.lang===lang&&!f.preview));
   const preview=pickNewest(audioPool.filter(f=>f.lang===lang&&f.preview));
   return [official,preview].filter(Boolean).map(({lang:_,preview:__,...entry})=>entry);
  });
  const videoFiles=filesOf(video)
    .filter(f=>/\.(mp4|mkv|webm)$/i.test(f.name||""))
    .map(f=>item(f,"video","完成影片"))
    .sort((a,b)=>a.name.localeCompare(b.name));
  const groups=[
   {key:"transcript",label:"逐字稿",folder_url:folderUrl(ids.transcript),files:transcriptFiles},
   {key:"audio",label:"音檔",folder_url:folderUrl(ids.audio),files:audioFiles},
   {key:"video",label:"完成影片",folder_url:folderUrl(ids.video),files:videoFiles}
  ];
  return {source:"soulkey-bridge",type:"course_files",ok:true,
   task_id:task,lesson_folder_url:folderUrl(ids.lesson),
   total_files:groups.reduce((n,g)=>n+g.files.length,0),groups,
   server_time:new Date().toISOString()};
 }
 async function courseFiles(p){
  const task=String(p.task_id||"");
  if(!/^P\d+-L\d{2}$/i.test(task))
   return {source:"soulkey-bridge",type:"course_files",ok:false,
     task_id:task,error:"invalid_task_id",groups:[],total_files:0};
  return scan(task);
 }
 async function ttsShareLinks(p){
  const task=String(p.task_id||"");
  if(!/^P\d+-L\d{2}$/i.test(task))
   return {source:"soulkey-bridge",type:"tts_share_links",ok:false,
    task_id:task,error:"invalid_task_id",groups:[],total_files:0};
  const overview=await scan(task);
  const all=overview.groups.find(g=>g.key==="audio")?.files||[];
  const files=all.filter(f=>shareCodes.some(code=>
    f.canonical_name===code+".mp3" || f.canonical_name===code+".preview.mp3")&&
    f.size>0);
  return {source:"soulkey-bridge",type:"tts_share_links",ok:true,
    task_id:task,groups:[{key:"audio",label:"音檔",
      folder_url:overview.groups.find(g=>g.key==="audio")?.folder_url||"",
      files}],total_files:files.length,server_time:new Date().toISOString()};
 }
 return {courseFiles,ttsShareLinks};
}
module.exports={createDriveOverview};

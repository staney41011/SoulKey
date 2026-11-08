/**
 * SoulKey automatic SECOND copy for classroom audio playback.
 *
 * Original audio (and its MP3/WAV/QA receipt) stays under the lesson.
 * DriveApp.File.makeCopy creates a separate MP3 in "所有口譯檔案":
 *   {period}/{language}/第{period}期_第{lesson}堂課_{title}_{lecturer}_{lang}TTS音檔.mp3
 * An unapproved playable MP3 gets suffix _待驗收.mp3.
 *
 * Source revisions are immutable; old *automated* playback copies are
 * renamed as historical files. User-authored files are never altered.
 * Retry is safe after a partial Google Apps Script execution.
 */
const SK_PLAYBACK_ROOT_ID = "1Z2BTD_WvMG08VSa3MSECFNj1yy_UuO66";
const SK_PLAYBACK_OWNED_PREFIX = "SoulKey-CLASSROOM-COPY|";
const SK_PLAYBACK_LANGUAGE_NAMES = {
  en:"英文", th:"泰文", es:"西班牙", id:"印尼", vi:"越南",
  hi:"印地文",ta:"泰米爾文",ja:"日文",ko:"韓文",km:"柬文",
  bn:"孟加拉文",ne:"尼泊爾文",lo:"寮文",my:"緬文",
  it:"義大利文",pt:"葡萄牙文",nan:"台語"
};

function skPlaybackSafePart_(value){
  return String(value||"").trim()
    .replace(/[\u0000-\u001f\u007f\/\\:*?"<>|]/g," ")
    .replace(/\s+/g," ").replace(/^[. ]+|[. ]+$/g,"")
    .slice(0,90);
}
function skPlaybackFolder_(parent,name){
  const iter=parent.getFoldersByName(name);
  if(iter.hasNext()){
    const found=iter.next();
    if(iter.hasNext())throw new Error("duplicate_playback_folder:"+name);
    return found;
  }
  return parent.createFolder(name);
}
function skPlaybackMarker_(obj){
  return SK_PLAYBACK_OWNED_PREFIX+JSON.stringify(obj);
}
function skPlaybackOwned_(file){
  const s=String(file.getDescription()||"");
  if(s.indexOf(SK_PLAYBACK_OWNED_PREFIX)!==0)return null;
  try{
    const meta=JSON.parse(s.slice(SK_PLAYBACK_OWNED_PREFIX.length));
    return meta && meta.system==="SoulKey" && meta.kind==="playback" ?
      meta:null;
  }catch(e){return null;}
}
function skPlaybackFileValid_(file){
  return file && !file.isTrashed() && Number(file.getSize())>0;
}
function skPlaybackExisting_(folder,name){
  const iter=folder.getFilesByName(name),out=[];
  while(iter.hasNext())out.push(iter.next());
  return out.filter(function(f){return !f.isTrashed();});
}
function skPlaybackReceipt_(lesson,lang){
  return readJsonFile_(lesson.folder,"sheets.native_playback."+lang+".json");
}
function skPlaybackReceiptSave_(lesson,lang,receipt){
  writeTextFile_(lesson.folder,"sheets.native_playback."+lang+".json",
    JSON.stringify(receipt,null,2),"application/json");
}
function skPlaybackHistoryName_(file,metadata){
  const current=String(file.getName()||"");
  if(/_舊版_[0-9a-f]{10}\.mp3$/i.test(current))return current;
  const sha=String(metadata.sha||"").slice(0,10)||
    String(file.getId()||"").slice(0,10);
  return current.replace(/\.mp3$/i,"_舊版_"+sha+".mp3");
}
function skPlaybackEnsure_(lesson,lang,sourceReceipt,requested,taskMeta){
  const expected=String(requested && requested.sha||"");
  if(!sourceReceipt || !requested ||
     ["done","needs_review"].indexOf(sourceReceipt.status)<0 ||
     sourceReceipt.release_tag!==requested.tag ||
     sourceReceipt.source_sha256!==expected ||
     !sourceReceipt.mp3_drive_id)
    return {ok:false,reason:"not_yet_ready_for_playback_copy"};
  const source=DriveApp.getFileById(sourceReceipt.mp3_drive_id);
  const sourceFilename=lesson.task+"-"+lang+"-"+expected.slice(0,16)+
    (sourceReceipt.status==="done"?".mp3":".preview.mp3");
  if(source.getName()!==sourceFilename || !skPlaybackFileValid_(source))
    throw new Error("playback_source_mp3_missing_or_changed");

  const task=taskMeta||readTasks_().find(function(row){
    return row.id===lesson.task;
  });
  const title=skPlaybackSafePart_(task&&task.title);
  const teacher=skPlaybackSafePart_(task&&task.lecturer);
  const language=SK_PLAYBACK_LANGUAGE_NAMES[lang];
  const period=Number(lesson.period||task&&task.period);
  const lessonNumber=Number(String(lesson.lesson||task&&task.lesson||"")
    .replace(/[^0-9]/g,""));
  if(!title || !teacher || !language || !Number.isInteger(period) ||
     !Number.isInteger(lessonNumber) || period<261 || lessonNumber<1)
    throw new Error("playback_course_metadata_missing_or_unsupported");

  const base="第"+period+"期_第"+lessonNumber+"堂課_"+
    title+"_"+teacher+"_"+language+"TTS音檔";
  // Technical MP3 validation and semantic Gemma4 QA are two different
  // checks. A technically valid MP3 must still be labeled unverified if
  // the text has not passed the chosen risk-based QA.
  const semanticReady=requested.review==="approved_english_final" ||
    requested.review==="approved_risk_based_not_full";
  const tier=(sourceReceipt.status==="done" && semanticReady)?
    "formal":"unverified";
  const suffix=tier==="unverified"?"_待驗收":"";
  const targetName=base+suffix+".mp3";
  const marker={
    system:"SoulKey",kind:"playback",task:lesson.task,lang:lang,
    sha:expected,tag:sourceReceipt.release_tag,status:sourceReceipt.status,
    review:String(requested.review||"not_approved"),tier:tier,
    source_mp3_id:source.getId()
  };
  const root=DriveApp.getFolderById(SK_PLAYBACK_ROOT_ID);
  const periodFolder=skPlaybackFolder_(root,String(period));
  const languageFolder=skPlaybackFolder_(periodFolder,language);
  // Do not trust an old receipt without checking the actual destination.
  const oldReceipt=skPlaybackReceipt_(lesson,lang);
  if(oldReceipt && oldReceipt.status==="copied" &&
     oldReceipt.sha===expected &&
     oldReceipt.source_mp3_id===source.getId() &&
     oldReceipt.source_status===sourceReceipt.status &&
     oldReceipt.review===marker.review && oldReceipt.tier===tier &&
     [targetName,base+suffix+"_系統副本_"+expected.slice(0,10)+".mp3"]
       .indexOf(oldReceipt.dest_filename)>=0 &&
     oldReceipt.dest_mp3_id){
    try{
      const exists=DriveApp.getFileById(oldReceipt.dest_mp3_id);
      const owned=skPlaybackOwned_(exists);
      if(skPlaybackFileValid_(exists) && owned &&
         owned.tag===marker.tag && owned.review===marker.review &&
         owned.tier===tier && owned.source_mp3_id===source.getId() &&
         exists.getName()===oldReceipt.dest_filename &&
         exists.getParents().hasNext() &&
         exists.getParents().next().getId()===languageFolder.getId())
        oldReceipt.last_verified_at=soulkeyNextNow_();
        skPlaybackReceiptSave_(lesson,lang,oldReceipt);
        return {ok:true,created:false,dest_mp3_id:exists.getId(),
          name:exists.getName(),status:"copied",idempotent:true};
    }catch(e){Logger.log("[PLAYBACK] receipt needs recheck: "+String(e).slice(0,100));}
  }
  // Recovery from a crash after makeCopy / before receipt write.
  let matchingCopy=null,manualCollision=false;
  const candidates=skPlaybackExisting_(languageFolder,targetName);
  candidates.forEach(function(f){
    const meta=skPlaybackOwned_(f);
    if(meta && meta.tag===marker.tag &&
       meta.review===marker.review && meta.tier===tier &&
       meta.source_mp3_id===source.getId())
      matchingCopy=matchingCopy||f;
    else if(!meta)manualCollision=true;
  });
  // Never overwrite a manually managed playback file.
  const actualName=manualCollision?
    base+suffix+"_系統副本_"+expected.slice(0,10)+".mp3":targetName;
  if(!matchingCopy){
    skPlaybackExisting_(languageFolder,actualName).forEach(function(f){
      const meta=skPlaybackOwned_(f);
      if(meta && meta.tag===marker.tag &&
         meta.review===marker.review && meta.tier===tier &&
       meta.source_mp3_id===source.getId())
        matchingCopy=matchingCopy||f;
      else if(!meta || meta.tag!==marker.tag)
        throw new Error("playback_name_collision_needs_manual_review");
    });
  }
  const stagedName=base+suffix+"_匯入中_"+expected.slice(0,12)+".mp3";
  if(!matchingCopy){
    skPlaybackExisting_(languageFolder,stagedName).forEach(function(f){
      const meta=skPlaybackOwned_(f);
      if(meta && meta.tag===marker.tag &&
         meta.review===marker.review && meta.tier===tier &&
       meta.source_mp3_id===source.getId())
        matchingCopy=matchingCopy||f;
      else throw new Error("playback_staged_name_collision");
    });
  }
  let created=false;
  if(!matchingCopy){
    // Uses a Drive-side copy, no 20-40 MB download/re-upload or GAS memory.
    matchingCopy=source.makeCopy(stagedName,languageFolder);
    matchingCopy.setDescription(skPlaybackMarker_(marker));
    created=true;
  }
  if(!skPlaybackFileValid_(matchingCopy))
    throw new Error("playback_copied_mp3_invalid");
  // Keep prior automated copies as historical versions, never touch manual.
  // We only rename after the new MP3 has been copied and validated.
  const iter=languageFolder.getFiles();
  while(iter.hasNext()){
    const f=iter.next();
    if(f.getId()===matchingCopy.getId() || f.isTrashed())continue;
    const old=skPlaybackOwned_(f);
    if(!old || old.task!==lesson.task || old.lang!==lang)continue;
    const filename=String(f.getName()||"");
    if(/_舊版_[0-9a-f]{10}\.mp3$/i.test(filename))continue;
    const backup=skPlaybackHistoryName_(f,old);
    const existingBackup=skPlaybackExisting_(languageFolder,backup)
      .filter(function(x){return x.getId()!==f.getId();});
    if(existingBackup.length)
      throw new Error("playback_history_filename_collision");
    f.setName(backup);
  }
  if(matchingCopy.getName()!==actualName)matchingCopy.setName(actualName);
  if(!skPlaybackOwned_(matchingCopy))
    matchingCopy.setDescription(skPlaybackMarker_(marker));
  const result={
    task_id:lesson.task,language:lang,status:"copied",
    source_status:sourceReceipt.status,review:marker.review,tier:tier,
    sha:expected,release_tag:sourceReceipt.release_tag,
    source_mp3_id:source.getId(),
    dest_mp3_id:matchingCopy.getId(),dest_filename:matchingCopy.getName(),
    classroom_folder_id:languageFolder.getId(),
    classroom_folder_url:languageFolder.getUrl(),
    copied_at:soulkeyNextNow_(),last_verified_at:soulkeyNextNow_()
  };
  skPlaybackReceiptSave_(lesson,lang,result);
  return {ok:true,created:created,
    dest_mp3_id:matchingCopy.getId(),name:matchingCopy.getName(),
    status:"copied",idempotent:!created};
}
function soulkeyPlaybackStatus(){
  const sources=soulkeyNextSources_();
  const root=DriveApp.getFolderById(SK_PLAYBACK_ROOT_ID);
  return {ok:true,root_name:root.getName(),root_id:root.getId(),
    ready_lessons:sources.length,
    current_periods:sources.map(function(x){return x.period;})
      .filter(function(x,i,a){return a.indexOf(x)===i;})};
}

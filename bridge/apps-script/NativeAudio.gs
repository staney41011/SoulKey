/**
 * SoulKey next-period TTS delivery without public Apps Script webhook.
 *
 * Runs inside Apps Script installable trigger with existing Studio Script
 * Properties GITHUB_TOKEN. Sends only approved/human-final transcript text
 * to a PRIVATE repo. Never sends any Google access/refresh tokens or cookies.
 * Release binary assets are downloaded back into Google Drive, with per-asset
 * digest checks. Existing official MP3/WAV files are never overwritten.
 */
const SK_AUDIO_REPO="staney41011/SoulKey-Private-Runner";
const SK_AUDIO_WORKFLOW="soulkey_private_tts.yml";
// App Script may initialize NativeAudio before NativeNext. Keep globals independent.
const SK_AUDIO_LANGUAGES=["en","es","id","km","vi","th","ja","ko",
  "ta","hi","bn","ne","lo","my","it","pt"];

function skAudioHash_(text){
  return soulkeyNextSha_(text);
}
function skAudioFloat_(v){
  const n=Number(v);
  if(!Number.isFinite(n))throw new Error("invalid_audio_timing");
  return Number.isInteger(n)?n.toFixed(1):String(n);
}
function skAudioFingerprint_(segments){
  // Exactly matches translation-system/tts_fingerprint.py:
  // json.dumps(canonical,sort_keys=True,ensure_ascii=False,separators=(",",":")).
  const encoded="["+segments.map(function(row){
    return '{"end":'+skAudioFloat_(row.end)+
      ',"id":'+String(Number(row.id))+
      ',"start":'+skAudioFloat_(row.start)+
      ',"text":'+JSON.stringify(String(row.text||"").trim())+'}';
  }).join(",")+"]";
  return skAudioHash_(encoded);
}
function skAudioGithub_(path,method,body,additionalHeaders){
  // The public worker and private TTS runner use separate credentials.
  const props=PropertiesService.getScriptProperties();
  const token=String(props.getProperty("SOULKEY_PRIVATE_GITHUB_TOKEN")||
    props.getProperty("GITHUB_TOKEN")||"").trim();
  if(!token)throw new Error("private_github_token_missing");
  const headers={
    Authorization:"Bearer "+token,
    Accept:"application/vnd.github+json",
    "X-GitHub-Api-Version":"2022-11-28"
  };
  Object.keys(additionalHeaders||{}).forEach(function(k){
    headers[k]=additionalHeaders[k];
  });
  const options={method:method||"get",headers:headers,
    muteHttpExceptions:true,followRedirects:false};
  if(body!==undefined && body!==null){
    options.contentType="application/json";
    options.payload=JSON.stringify(body);
  }
  const response=UrlFetchApp.fetch("https://api.github.com/repos/"+
    SK_AUDIO_REPO+path,options);
  return response;
}
function skAudioGithubJson_(path,method,body,allow404){
  const response=skAudioGithub_(path,method,body);
  const code=response.getResponseCode();
  if(code===404 && allow404)return null;
  if(code<200||code>=300)throw new Error(
    "private_github_http_"+code+"_"+path.slice(0,70));
  if(code===204)return {ok:true};
  return JSON.parse(response.getContentText());
}
function skAudioRelease_(tag){
  return skAudioGithubJson_("/releases/tags/"+encodeURIComponent(tag),
    "get",null,true);
}
function skAudioAsset_(asset){
  if(!asset || !asset.id || !Number(asset.size))
    throw new Error("github_release_asset_missing");
  const r=skAudioGithub_("/releases/assets/"+asset.id,"get",null,{
    Accept:"application/octet-stream"
  });
  const status=r.getResponseCode();
  let body;
  if(status===302||status===301||status===307){
    const loc=(r.getAllHeaders()||{}).Location||
      (r.getAllHeaders()||{}).location;
    if(!loc || !/^https:\/\/[A-Za-z0-9.-]+\//.test(loc))
      throw new Error("unsigned_release_redirect");
    const redirected=UrlFetchApp.fetch(loc,{method:"get",
      muteHttpExceptions:true,followRedirects:false});
    if(redirected.getResponseCode()!==200)
      throw new Error("asset_redirect_http_"+redirected.getResponseCode());
    body=redirected.getBlob().getBytes();
  }else if(status===200){
    body=r.getBlob().getBytes();
  }else{
    throw new Error("release_asset_http_"+status);
  }
  if(body.length!==Number(asset.size))
    throw new Error("release_asset_bytes_mismatch:"+asset.name);
  return body;
}
function skAudioDigestBytes_(bytes){
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,bytes)
    .map(function(b){return ("0"+(b&255).toString(16)).slice(-2);})
    .join("");
}
function skAudioAssetChecked_(asset,receipt){
  const bytes=skAudioAsset_(asset);
  if(!receipt || Number(receipt.bytes)!==bytes.length ||
     skAudioDigestBytes_(bytes)!==String(receipt.sha256||""))
    throw new Error("private_release_digest_mismatch:"+asset.name);
  return bytes;
}
function skAudioAssetByName_(release,name){
  const matching=(release.assets||[]).filter(function(x){return x.name===name;});
  if(matching.length!==1)throw new Error("release_missing_asset:"+name);
  return matching[0];
}
function skAudioCanonicalFile_(folder,name,blob,description){
  const existing=folder.getFilesByName(name);
  if(existing.hasNext()){
    const file=existing.next();
    const old=String(file.getDescription()||"");
    if(old!==description)
      throw new Error("refusing_to_overwrite_existing_audio_revision");
    return file;
  }
  const file=folder.createFile(blob.setName(name));
  file.setDescription(description);
  return file;
}
function skAudioUploadWav_(folder,name,parts,totalBytes,revision){
  // Google Drive REST resumable upload. The Google OAuth token remains
  // exclusively inside Google UrlFetchApp; GitHub never sees it.
  const previous=folder.getFilesByName(name);
  if(previous.hasNext()){
    const same=previous.next();
    if(String(same.getDescription()||"").indexOf(revision)>=0 &&
       same.getSize()===totalBytes)return same;
    throw new Error("refusing_to_overwrite_existing_wav");
  }
  const auth="Bearer "+ScriptApp.getOAuthToken();
  const description="SoulKey private Edge TTS WAV "+revision;
  const start=UrlFetchApp.fetch(
    "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",{
      method:"post",headers:{
        Authorization:auth,
        "X-Upload-Content-Type":"audio/wav",
        "X-Upload-Content-Length":String(totalBytes)
      },contentType:"application/json",muteHttpExceptions:true,
      payload:JSON.stringify({
        name:name,description:description,
        mimeType:"audio/wav",parents:[folder.getId()]
      })
    });
  if(start.getResponseCode()!==200 && start.getResponseCode()!==201)
    throw new Error("wav_upload_session_http_"+start.getResponseCode());
  const headers=start.getAllHeaders();
  const location=headers.Location||headers.location;
  if(!location || !String(location).startsWith("https://"))
    throw new Error("wav_upload_session_url_missing");
  let offset=0,driveResult=null;
  for(let i=0;i<parts.length;i++){
    const item=parts[i];
    const bytes=item.bytes;
    const ending=offset+bytes.length-1;
    const upload=UrlFetchApp.fetch(location,{
      method:"put",contentType:"audio/wav",
      headers:{Authorization:auth,
        "Content-Range":"bytes "+offset+"-"+ending+"/"+totalBytes},
      payload:bytes,muteHttpExceptions:true
    });
    const code=upload.getResponseCode();
    if(i<parts.length-1 && code!==308)
      throw new Error("wav_upload_chunk_http_"+code);
    if(i===parts.length-1){
      if(code!==200 && code!==201)
        throw new Error("wav_upload_final_http_"+code);
      driveResult=JSON.parse(upload.getContentText());
    }
    offset+=bytes.length;
  }
  if(offset!==totalBytes || !driveResult || !driveResult.id)
    throw new Error("wav_upload_incomplete");
  const uploaded=DriveApp.getFileById(driveResult.id);
  if(uploaded.getSize()!==totalBytes)
    throw new Error("wav_drive_size_mismatch");
  return uploaded;
}
function skAudioPayload_(lesson,lang,terms){
  let rows,draftId=null,review="not_approved";
  if(lang==="en"){
    rows=lesson.segments.map(function(s){
      return {id:s.id,start:s.start,end:s.end,text:s.text};
    });
    review="approved_english_final";
  }else{
    const draft=skNQDraft_(lesson,lang);
    if(!draft)return null;
    draftId=draft.id;
    const enBy={};
    lesson.segments.forEach(function(s){enBy[String(s.id)]=s;});
    if(draft.draft.segments.some(function(s){
      const en=enBy[String(s.id)];
      return !en || en.source_hash!==s.source_hash ||
        Math.abs(Number(s.start)-en.start)>.06 ||
        Math.abs(Number(s.end)-en.end)>.06 ||
        !String(s.text||"").trim();
    }))throw new Error("draft_not_current_english_final");
    rows=draft.draft.segments.map(function(s){
      return {id:Number(s.id),start:Number(s.start),
        end:Number(s.end),text:String(s.text||"").trim()};
    });
    // Never confuse the risk-based QA with exhaustive semantic approval.
    const report=readJsonFile_(lesson.folder,"sheets.qa.native."+lang+".json");
    const revision=skAudioHash_(JSON.stringify({
      task:lesson.task,language:lang,draft:draft.draft.segments,
      english:lesson.segments,terms:terms}));
    if(report && report.revision_key===revision &&
       report.state==="approved_risk_based"){
      const decisions=report.decisions||{};
      rows.forEach(function(s){
        const decision=decisions[String(s.id)]||{};
        if(["B_verified","B_editorial"].indexOf(decision.grade)>=0 &&
          String(decision.corrected_text||"").trim())
          s.text=String(decision.corrected_text).trim();
      });
      review="approved_risk_based_not_full";
    }
  }
  const maxEnd=rows.reduce(function(n,x){return Math.max(n,Number(x.end));},0);
  if(!(maxEnd>=60 && maxEnd<21600))return null;
  const fingerprint=skAudioFingerprint_(rows);
  const tag=lesson.task+"-"+lang+"-"+fingerprint.slice(0,16);
  const payload={
    task_id:lesson.task,language:lang,segments:rows,
    source_duration:Math.ceil(maxEnd+6),
    source_sha256:fingerprint,release_tag:tag
  };
  const bytes=Utilities.gzip(Utilities.newBlob(
    JSON.stringify(payload,null,0),"application/json")).getBytes();
  const b64=Utilities.base64EncodeWebSafe(bytes).replace(/=+$/,"");
  if(b64.length>56000)throw new Error("github_dispatch_payload_too_large");
  return {payload:payload,encoded:b64,tag:tag,sha:fingerprint,
    review:review,draft_file_id:draftId};
}
// Always keep a downloadable TTS source document; failed synthesis must
// not erase the text that can be reviewed and submitted again.
function skAudioSaveSource_(lesson,lang,requested){
  const name="sheets.native_tts."+lang+".source.json";
  const files=lesson.folder.getFilesByName(name);
  const text=JSON.stringify({
    task_id:lesson.task,language:lang,
    status:"not_a_release",
    review_scope:requested.review,
    source_sha256:requested.sha,release_tag:requested.tag,
    segments:requested.payload.segments
  },null,2);
  const file=files.hasNext()?files.next():null;
  if(file){
    if(String(file.getDescription()||"")!==requested.tag){
      file.setContent(text);
      file.setDescription(requested.tag);
    }
    return file;
  }
  const created=lesson.folder.createFile(name,text,MimeType.PLAIN_TEXT);
  created.setDescription(requested.tag);
  return created;
}
// Only expose a current, approved manuscript paired to the exact TTS input.
function skAudioVerifiedSource_(lesson,lang,requested){
  if(!requested || ["approved_english_final","approved_risk_based_not_full"]
      .indexOf(requested.review)<0)return "";
  try{
    const files=lesson.folder.getFilesByName("sheets.native_tts."+lang+".source.json");
    if(!files.hasNext())return "";
    const file=files.next();
    if(file.isTrashed() || Number(file.getSize())<=0)return "";
    const obj=JSON.parse(file.getBlob().getDataAsString("UTF-8"));
    if(obj.task_id!==lesson.task || obj.language!==lang ||
       obj.source_sha256!==requested.sha || obj.release_tag!==requested.tag ||
       obj.review_scope!==requested.review ||
       !Array.isArray(obj.segments) || !obj.segments.length ||
       skAudioFingerprint_(obj.segments)!==requested.sha)return "";
    return file.getUrl();
  }catch(e){return "";}
}
function skShareSaveManuscript_(lesson,lang,requested){
  if(["approved_english_final","approved_risk_based_not_full"].indexOf(requested.review)<0)return;
  const base=lesson.task+"-"+lang+"-"+requested.sha.slice(0,16)+"-approved";
  const rows=requested.payload.segments;
  [[".txt",function(){return buildTxt_(rows);}],[".srt",function(){return buildSrt_(rows);}]].forEach(function(item){
    const name=base+item[0],files=lesson.folder.getFilesByName(name);
    if(!files.hasNext())lesson.folder.createFile(name,item[1](),MimeType.PLAIN_TEXT);
  });
}
function skShareModern_(id){
  return Number((String(id).match(/^P(\d+)-/)||[])[1]||0)>=263;
}
function skShareKey_(id,lang){return "SOULKEY_SHARE_V1_"+id+"_"+lang;}
function skShareEpoch_(id,lang){
  const p=PropertiesService.getScriptProperties();
  return [p.getProperty("SOULKEY_SHARE_EPOCH_"+id)||"",
    lang==="en"?"":p.getProperty("SOULKEY_SHARE_TERMS_EPOCH")||""].join("|");
}
function skShareInvalidate_(id,lang){
  if(!skShareModern_(id))return;
  const p=PropertiesService.getScriptProperties();
  if(lang){p.deleteProperty(skShareKey_(id,lang));return;}
  p.setProperty("SOULKEY_SHARE_EPOCH_"+id,String(Date.now())+"-"+Math.random());
  SK_AUDIO_LANGUAGES.forEach(function(code){p.deleteProperty(skShareKey_(id,code));});
}
function skShareInvalidateTerms_(){
  PropertiesService.getScriptProperties().setProperty("SOULKEY_SHARE_TERMS_EPOCH",String(Date.now())+"-"+Math.random());
}
function skShareReadEntry_(id,lang){
  try{
    const p=PropertiesService.getScriptProperties();
    const r=JSON.parse(p.getProperty(skShareKey_(id,lang))||"null");
    return r&&r.task_id===id&&r.language===lang&&r.epoch===skShareEpoch_(id,lang)?r:null;
  }catch(_){return null;}
}
function skShareRead_(id){
  const files=SK_AUDIO_LANGUAGES.map(function(lang){return skShareReadEntry_(id,lang);})
    .filter(Boolean).map(function(r){return r.file;});
  return {ok:true,task_id:id,groups:[{key:"audio",label:"音檔",files:files}],
    total_files:files.length,server_time:new Date().toISOString(),central_index:true};
}
function skSharePublish_(lesson,lang,receipt,requested){
  const id=lesson.task;
  if(!skShareModern_(id))return false;
  const epoch=requested&&requested.share_epoch;
  if(!requested){skShareInvalidate_(id,lang);return false;}
  if(epoch!==skShareEpoch_(id,lang))return false;
  if(!receipt||receipt.status!=="done"||receipt.release_tag!==requested.tag||
      receipt.source_sha256!==requested.sha||
      !skAudioVerifiedSource_(lesson,lang,requested)){
    skShareInvalidate_(id,lang);return false;
  }
  const proof=skPlaybackReceipt_(lesson,lang);
  if(!proof||proof.status!=="copied"||proof.tier!=="formal"||
     proof.sha!==requested.sha||proof.release_tag!==requested.tag||
     proof.review!==requested.review||proof.source_mp3_id!==receipt.mp3_drive_id||
     !proof.dest_mp3_id){
    skShareInvalidate_(id,lang);return false;
  }
  const source=DriveApp.getFileById(receipt.mp3_drive_id);
  const file=DriveApp.getFileById(proof.dest_mp3_id);
  const marker=skPlaybackOwned_(file);
  const expected=id+"-"+lang+"-"+requested.sha.slice(0,16)+".mp3";
  if(!skPlaybackFileValid_(source)||source.getName()!==expected||
     !skPlaybackFileValid_(file)||!marker||marker.task!==id||marker.lang!==lang||
     marker.tag!==requested.tag||marker.sha!==requested.sha||
     marker.review!==requested.review||marker.tier!=="formal"||
     marker.source_mp3_id!==receipt.mp3_drive_id||
     file.getName()!==proof.dest_filename||
     !file.getParents().hasNext()||file.getParents().next().getId()!==proof.classroom_folder_id){
    skShareInvalidate_(id,lang);return false;
  }
  if(epoch!==skShareEpoch_(id,lang))return false;
  const value={task_id:id,language:lang,epoch:epoch,sha:requested.sha,
    file:{id:file.getId(),name:file.getName(),canonical_name:lang+".mp3",
      needs_timing_review:false,audio_kind:"formal_aligned",native_verified:true,
      url:file.getUrl(),size:Number(file.getSize()),group_key:"audio",group_label:"音檔"}};
  const p=PropertiesService.getScriptProperties(),key=skShareKey_(id,lang);
  const json=JSON.stringify(value);
  if(p.getProperty(key)!==json)p.setProperty(key,json);
  return true;
}
function skAudioReceipt_(lesson,lang){
  return readJsonFile_(lesson.folder,"sheets.native_tts."+lang+".json");
}
function skAudioSaveReceipt_(lesson,lang,record){
  const name="sheets.native_tts."+lang+".json";
  writeTextFile_(lesson.folder,name,JSON.stringify(record,null,2),
    "application/json");
}
function skAudioImport_(lesson,lang,requested,release){
  const meta=skAudioAssetByName_(release,"voice.result.json");
  const raw=skAudioAsset_(meta);
  const result=JSON.parse(Utilities.newBlob(raw).getDataAsString("UTF-8"));
  if(result.task_id!==lesson.task || result.language!==lang ||
     result.release_tag!==requested.tag ||
     result.source_sha256!==requested.sha ||
     !result.files || !["done","needs_review"].includes(result.status))
    throw new Error("private_tts_source_or_result_mismatch");
  const audioFolder=cachedChildFolder_(
    lessonFolders_(lesson.task).lesson,"04_音檔");
  const base=lesson.task+"-"+lang+"-"+requested.sha.slice(0,16);
  const extension=result.status==="done"?"mp3":"preview.mp3";
  const mp3Name="voice."+extension;
  const mp3Bytes=skAudioAssetChecked_(
    skAudioAssetByName_(release,mp3Name),result.files[mp3Name]);
  const description="SoulKey Sheets-first Edge TTS private release; "+
    requested.tag+"; semanticQA="+requested.review;
  const mp3=skAudioCanonicalFile_(audioFolder,base+"."+extension,
    Utilities.newBlob(mp3Bytes,"audio/mpeg"),description);
  // Make the verified MP3 a first-class deliverable. The original synchronous
  // path fetched and uploaded all WAV chunks (often >60 MB) BEFORE writing
  // the MP3 receipt, which exceeded the signed bridge's 300-second limit and
  // prevented the automatic "所有口譯檔案" copy despite successful synthesis.
  // WAV remains archived, immutable and recoverable from the private release.
  let audioStatus=result.status,issue="",savedMp3=mp3;
  let archivedWavParts=0;
  if(result.status==="done"){
    try{
      const chunks=result.wav_chunks||[];
      if(!Array.isArray(chunks)||!chunks.length||chunks.length>30)
        throw new Error("invalid_voice_wav_chunks");
      let observed=0;
      chunks.forEach(function(name){
        const asset=skAudioAssetByName_(release,name);
        const proof=result.files&&result.files[name];
        if(!proof || !Number.isFinite(Number(proof.bytes)) ||
           Number(proof.bytes)<=0 || Number(asset.size)!==Number(proof.bytes))
          throw new Error("wav_release_manifest_mismatch");
        observed+=Number(proof.bytes);
      });
      if(observed!==Number(result.wav_bytes))
        throw new Error("wav_parts_total_mismatch");
      archivedWavParts=chunks.length;
    }catch(e){
      // A missing or corrupt WAV *release* is still a review issue. Retain
      // the valid MP3 as explicitly unverified, never silently publish it.
      audioStatus="needs_review";
      issue="wav_import_failed:"+String(e&&e.message||e).slice(0,140);
      savedMp3=skAudioCanonicalFile_(audioFolder,base+".preview.mp3",
        Utilities.newBlob(mp3Bytes,"audio/mpeg"),description);
    }
  }
  const output={
    task_id:lesson.task,language:lang,status:audioStatus,
    issue:issue,source_sha256:requested.sha,release_tag:requested.tag,
    semantic_review_scope:requested.review,
    mp3_drive_id:savedMp3.getId(),wav_drive_id:null,
    wav_archived_release_tag:archivedWavParts?requested.tag:null,
    wav_archived_parts:archivedWavParts,
    source_duration_seconds:Number(result.source_duration_seconds),
    timing:result.timing,
    imported_at:soulkeyNextNow_()
  };
  skAudioSaveReceipt_(lesson,lang,output);
  return output;
}
// GH Actions may finish with "failure" long before the former two-hour
// missing-release timeout. Detect only the LATEST run for the exact source
// revision; never relaunch a queued/in-progress run or a stale old failure.
function skAudioLatestRunFailed_(lesson,lang,requested,receipt,runs){
  const dispatched=Date.parse(
    String(receipt&&receipt.dispatched_at||"").replace(" ","T")+"+08:00");
  if(!Number.isFinite(dispatched))return false;
  const label="SoulKey TTS "+lesson.task+"-"+lang+"-"+
    requested.sha.slice(0,8);
  const candidates=(runs||[]).filter(function(run){
    const created=Date.parse(String(run.created_at||""));
    return run.display_title===label && Number.isFinite(created) &&
      created+15000>=dispatched;
  }).sort(function(a,b){
    return Date.parse(b.created_at)-Date.parse(a.created_at);
  });
  const latest=candidates[0];
  return !!latest && latest.status==="completed" &&
    ["failure","cancelled","timed_out","startup_failure"]
      .indexOf(String(latest.conclusion||""))>=0;
}

function soulkeyNextAudioTick(focusTask,focusLanguage){
  const invocationMode=typeof focusTask==="string"?"manual":"scheduled";
  focusTask=soulkeyNextNormalizeTask_(focusTask);
  focusLanguage=(typeof focusLanguage==="string" &&
    SK_AUDIO_LANGUAGES.indexOf(focusLanguage)>=0)?focusLanguage:"";
  soulkeyNextHeartbeat_("audio","started",invocationMode,
    focusTask+"/"+focusLanguage);
  if(PropertiesService.getScriptProperties()
      .getProperty("SOULKEY_NEXT_ENABLED")!=="yes")
    return {ok:false,reason:"native_next_not_enabled"};
  const lock=LockService.getScriptLock();
  if(!lock.tryLock(1000)){
    soulkeyNextHeartbeat_("audio","busy",invocationMode,
      focusTask+"/"+focusLanguage);
    return {ok:false,reason:"busy"};
  }
  let runError=null;
  try{
    const sources=soulkeyNextSources_(focusTask).filter(function(source){
      return focusTask?source.task===focusTask:
        Number(source.period)>=SK_NEXT_AUTO_MIN_PERIOD;
    }).sort(function(a,b){
      const newer=Number(b.period)-Number(a.period);
      if(newer)return newer;
      if(a.task==="P261-L02" && b.task!=="P261-L02")return -1;
      if(b.task==="P261-L02" && a.task!=="P261-L02")return 1;
      return a.task.localeCompare(b.task);
    });
    if(!sources.length)
      return {ok:true,queued:0,imported:0,reason:"no_p261_english_final"};
    const terms=skNQTerms_();
    const byTask={};
    readTasks_().forEach(function(row){byTask[row.id]=row;});
    let dispatched=0,playbackAttempts=0,periodicPlaybackChecks=0;
    let privateRuns=null;
    for(let i=0;i<sources.length;i++){
      const lesson=sources[i];
      for(let j=0;j<SK_AUDIO_LANGUAGES.length;j++){
        const lang=SK_AUDIO_LANGUAGES[j];
        if(focusLanguage && lang!==focusLanguage)continue;
        if(soulkeyNextSelectedCodes_(lesson.task,"audio")
           .indexOf(lang)<0)continue;
        let requested;
        const shareEpoch=skShareModern_(lesson.task)?skShareEpoch_(lesson.task,lang):"";
        try{
          requested=skAudioPayload_(lesson,lang,terms);
          if(requested)requested.share_epoch=shareEpoch;
        }catch(e){
          Logger.log("[NEXT-AUDIO] "+lesson.task+"/"+lang+" "+
            String(e&&e.message||e).slice(0,150));
          skShareInvalidate_(lesson.task,lang);
          continue;
        }
        if(!requested){
          skShareInvalidate_(lesson.task,lang);
          if(focusTask&&focusLanguage)return {ok:false,task:lesson.task,lang:lang,reason:"current_source_not_ready"};
          continue;
        }
        // P262+: a DRAFT may be used for preview, but never issue a
        // production MP3 before this exact revision passes risk-based QA.
        if(Number(lesson.period)>=262 && lang!=="en" &&
           requested.review!=="approved_risk_based_not_full"){
          Logger.log("[NEXT-AUDIO] "+lesson.task+"/"+lang+
            " awaiting current Gemma4 QA; not publishable");
          skShareInvalidate_(lesson.task,lang);
          if(focusTask&&focusLanguage)return {ok:false,task:lesson.task,lang:lang,reason:"awaiting_current_qa"};
          continue;
        }
        try{
          skAudioSaveSource_(lesson,lang,requested);
          if(skShareModern_(lesson.task)&&!skShareReadEntry_(lesson.task,lang))
            skShareSaveManuscript_(lesson,lang,requested);
        }catch(e){
          Logger.log("[NEXT-AUDIO] source archive "+lesson.task+" "+lang+": "+
            String(e).slice(0,120));
        }
        const receipt=skAudioReceipt_(lesson,lang);
        const indexed=skShareModern_(lesson.task)?skShareReadEntry_(lesson.task,lang):null;
        if(indexed&&indexed.sha!==requested.sha)skShareInvalidate_(lesson.task,lang);
        if(receipt && receipt.release_tag===requested.tag &&
           ["done","needs_review"].includes(receipt.status) &&
           receipt.mp3_drive_id){
          // A completed receipt alone is not proof that the Drive output
          // still exists. Resume import/rebuild when a file is gone/stale.
          let verified=false;
          try{
            const file=DriveApp.getFileById(receipt.mp3_drive_id);
            const expectedName=lesson.task+"-"+lang+"-"+
              requested.sha.slice(0,16)+
              (receipt.status==="done"?".mp3":".preview.mp3");
            verified=file.getName()===expectedName &&
              Number(file.getSize())>0 && !file.isTrashed();
          }catch(e){Logger.log("[NEXT-AUDIO] output needs restore: "+lang);}
          if(verified){
            // Classroom copy is a separate deliverable. Never block
            // SoulKey's original audio from being marked as generated.
            // Missing classroom copies take precedence over daily rechecks
            // of copies that were already verified. Repair at most eight
            // missing copies plus one periodic recheck per audio tick.
            if(playbackAttempts<9){
              const proof=skPlaybackReceipt_(lesson,lang);
              const same=proof && proof.status==="copied" &&
                proof.sha===requested.sha &&
                proof.release_tag===requested.tag &&
                proof.source_status===receipt.status &&
                proof.review===requested.review &&
                proof.tier===((receipt.status==="done" &&
                  ["approved_english_final","approved_risk_based_not_full"]
                    .indexOf(requested.review)>=0)?"formal":"unverified") &&
                proof.source_mp3_id===receipt.mp3_drive_id;
              const verifiedAt=Date.parse(String(proof&&proof.last_verified_at||""));
              // Focused, signed repair must verify the current destination
              // even when an old receipt (e.g. legacy 柬文/西班牙 folder)
              // was checked recently. The copy helper remains idempotent.
              const due=!!(focusTask && focusLanguage) ||
                (skShareModern_(lesson.task)&&!skShareReadEntry_(lesson.task,lang)) || !same ||
                !Number.isFinite(verifiedAt) ||
                Date.now()-verifiedAt>24*60*60*1000;
              if(due && (!same || periodicPlaybackChecks<1)){
                playbackAttempts++;
                if(same)periodicPlaybackChecks++;
                try{
                  const copy=skPlaybackEnsure_(lesson,lang,receipt,requested,
                    byTask[lesson.task]);
                  if(copy.ok&&skShareModern_(lesson.task))skSharePublish_(lesson,lang,receipt,requested);
                  if(focusTask&&focusLanguage)return {ok:!!copy.ok,task:lesson.task,lang:lang,
                    status:receipt.status,imported:0,queued:0,
                    classroom_playback:copy.ok?"copied":"pending",reason:copy.reason||""};
                }catch(error){
                  Logger.log("[PLAYBACK] retry next tick "+
                    lesson.task+"/"+lang+" "+
                    String(error&&error.message||error).slice(0,160));
                  if(focusTask&&focusLanguage)return {ok:false,task:lesson.task,lang:lang,
                    status:receipt.status,classroom_playback:"retry",
                    reason:String(error&&error.message||error).slice(0,150)};
                }
              }
            }
            continue;
          }
        }
        try{
          const release=skAudioRelease_(requested.tag);
          if(release){
            const imported=skAudioImport_(lesson,lang,requested,release);
            let playback="pending";
            try{
              const mirrored=skPlaybackEnsure_(lesson,lang,imported,
                requested,byTask[lesson.task]);
              playback=mirrored.ok?"copied":"pending";
              if(mirrored.ok&&skShareModern_(lesson.task))skSharePublish_(lesson,lang,imported,requested);
            }catch(error){
              // Important: a copy permission or naming failure may not
              // reclassify an otherwise valid SoulKey original MP3/WAV.
              playback="retry";
              Logger.log("[PLAYBACK] source kept, copy deferred "+
                lesson.task+"/"+lang+" "+
                String(error&&error.message||error).slice(0,160));
            }
            return {ok:true,imported:1,queued:dispatched,
              task:lesson.task,lang:lang,status:imported.status,
              classroom_playback:playback};
          }
           // Do not wait two hours after an already-failed private TTS run.
           // Read at most one private workflow run list per audio tick.
           // A still-running or queued run is never duplicated.
           let attempts=0;
           if(receipt && receipt.release_tag===requested.tag &&
              receipt.status==="queued"){
             attempts=Number(receipt.attempts||1);
             if(attempts>=3){
               Logger.log("[NEXT-AUDIO] manual review required after retries: "+
                 lesson.task+"/"+lang);
               continue;
             }
             const when=Date.parse(
               String(receipt.dispatched_at||"").replace(" ","T")+"+08:00");
             if(!Number.isFinite(when))continue;
             if(Date.now()-when<2*60*60*1000){
               if(privateRuns===null){
                 try{
                   const response=skAudioGithubJson_(
                     "/actions/workflows/"+SK_AUDIO_WORKFLOW+
                     "/runs?event=workflow_dispatch&per_page=100","get");
                   privateRuns=(response&&response.workflow_runs)||[];
                 }catch(e){
                   Logger.log("[NEXT-AUDIO] private run status deferred: "+
                     String(e&&e.message||e).slice(0,130));
                   privateRuns=[];
                 }
               }
               if(!skAudioLatestRunFailed_(lesson,lang,requested,receipt,
                    privateRuns))continue;
               Logger.log("[NEXT-AUDIO] private TTS failed; safe immediate retry "+
                 lesson.task+"/"+lang+" attempt="+(attempts+1));
             }
           }          // Drive checkpoint is written ONLY on successful dispatch.
          const response=skAudioGithub_("/actions/workflows/"+
            SK_AUDIO_WORKFLOW+"/dispatches","post",{
              ref:"main",inputs:{
                request_label:lesson.task+"-"+lang+"-"+requested.sha.slice(0,8),
                payload_b64:requested.encoded
              }
            });
          if(response.getResponseCode()!==204)
            throw new Error("github_private_dispatch_http_"+
              response.getResponseCode());
          skAudioSaveReceipt_(lesson,lang,{
            task_id:lesson.task,language:lang,status:"queued",
            source_sha256:requested.sha,release_tag:requested.tag,
            semantic_review_scope:requested.review,
            dispatched_at:soulkeyNextNow_(),
            attempts:attempts+1
          });
          dispatched++;
          if(dispatched>=2)return {ok:true,queued:dispatched,
            imported:0,task:lesson.task,lang:lang};
        }catch(e){
          Logger.log("[NEXT-AUDIO] dispatch/import "+
            lesson.task+"/"+lang+" "+
            String(e&&e.message||e).slice(0,160));
          const reason=String(e&&e.message||e).slice(0,150);
          soulkeyNextHeartbeat_("audio","error",invocationMode,lesson.task+"/"+lang+" "+reason);
          if(focusTask&&focusLanguage)return {ok:false,task:lesson.task,lang:lang,reason:reason};
          continue;
        }
      }
    }
    return {ok:true,queued:dispatched,imported:0,
      reason:"ready_or_jobs_in_progress"};
  }catch(error){
    runError=error;
    throw error;
  }finally{
    soulkeyNextHeartbeat_("audio",runError?"error":"returned",
      invocationMode,runError?String(runError&&runError.message||runError):
      focusTask+"/"+focusLanguage);
    lock.releaseLock();
  }
}

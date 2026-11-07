/**
 * SoulKey Studio P261+ authoritative read API.
 * Uses central Google Sheets + revision-checked Gemma QA + verified private TTS
 * receipts. Readonly calls must never dispatch duplicate generation.
 */
function soulkeyStudioCurrentPeriod_(){
  const rows=getSheetByName_("期數設定").getDataRange().getDisplayValues();
  let newest=0;
  rows.slice(1).forEach(function(row){
    if(String(row[2]||"").trim()!=="啟用")return;
    const match=String(row[0]||"").match(/^P(\d+)$/i);
    if(match)newest=Math.max(newest,Number(match[1]));
  });
  return {source:"soulkey-bridge",type:"period_latest",ok:newest>0,
    period:newest,server_time:new Date().toISOString()};
}

function soulkeyStudioGlossaryRows_(){
  const sheet=getSheetByName_("專有名詞庫");
  const data=sheet.getDataRange().getDisplayValues();
  return data.slice(1).map(function(row){
    return {name:String(row[0]||"").trim(),category:String(row[1]||""),
      description:String(row[2]||""),en:String(row[3]||""),
      locked:String(row[8]||"").toUpperCase()==="TRUE",
      note:String(row[9]||"")};
  }).filter(function(x){return !!x.name;}).slice(0,800);
}

function soulkeyStudioGlossaryUpsert_(request){
  const name=String(request.name||"").trim();
  const en=String(request.en||"").trim();
  const category=String(request.category||"宗教術語").trim();
  const desc=String(request.description||"").trim();
  if(!name||name.length>80||en.length>180||
     desc.length>500||category.length>70)
    return {source:"soulkey-bridge",type:"glossary_saved",
      ok:false,error:"invalid_glossary_term",name:name};
  const lock=LockService.getScriptLock();
  lock.waitLock(15000);
  try{
    const sheet=getSheetByName_("專有名詞庫");
    const rows=sheet.getDataRange().getDisplayValues();
    let index=-1;
    for(let i=1;i<rows.length;i++){
      if(String(rows[i][0]||"").trim()===name){index=i+1;break;}
    }
    let mode="created";
    if(index>0){
      const prev=rows[index-1];
      if(en && String(prev[3]||"").trim() &&
         String(prev[3]).trim()!==en)
        return {source:"soulkey-bridge",type:"glossary_saved",
          ok:false,error:"existing_translation_conflict_requires_review",
          name:name};
      mode="existing";
      if(en && !String(prev[3]||"").trim())
        sheet.getRange(index,4).setValue(en);
      if(desc && !String(prev[2]||"").trim())
        sheet.getRange(index,3).setValue(desc);
    }else{
      const row=new Array(Math.max(sheet.getLastColumn(),21)).fill("");
      row[0]=name;row[1]=category;row[2]=desc;row[3]=en;
      row[8]=false;row[9]="SoulKey Studio 中央同步";
      sheet.appendRow(row);
    }
    SpreadsheetApp.flush();
    return {source:"soulkey-bridge",type:"glossary_saved",
      ok:true,mode:mode,name:name};
  }finally{lock.releaseLock();}
}

function soulkeyStudioNativeStatus_(taskId){
  const id=String(taskId||"").trim();
  if(!/^P\d+-L\d+$/.test(id) || Number(id.match(/^P(\d+)/)[1])<261)
    return {source:"soulkey-bridge",type:"native_pipeline_status",
      ok:false,error:"not_next_period",task_id:id};
  const registered=readTasks_().find(function(x){return x.id===id;});
  if(!registered)
    return {source:"soulkey-bridge",type:"native_pipeline_status",
      ok:false,error:"task_not_registered",task_id:id};
  const selectedTexts=soulkeyNextSelectedCodes_(id,"translation");
  const selectedAudio=soulkeyNextSelectedCodes_(id,"audio");
  const source=soulkeyNextSources_().find(function(x){return x.task===id;});
  const common={source:"soulkey-bridge",type:"native_pipeline_status",
    ok:true,task_id:id,mode:"sheets_gemma4_independent",
    selected_text_languages:selectedTexts,
    selected_audio_languages:selectedAudio,
    semantic_review_scope:"risk_based_not_full_semantic_review",
    english_final_ready:!!source,server_time:new Date().toISOString()};
  if(!source)return Object.assign(common,{
    state:"awaiting_english_final",can_publish:false,
    blockers:["英文人工定稿尚未完成或來源不符合版本條件"],
    languages:[],translation_done:0,qa_done:0,audio_done:0});
  let sheetRows=[];
  try{
    const tab=getSheetByName_("AppsScript初譯");
    if(tab.getLastRow()>1)sheetRows=tab.getRange(
      2,1,tab.getLastRow()-1,25).getDisplayValues()
      .filter(function(row){return String(row[0])===id;});
  }catch(e){
    Logger.log("[NATIVE-STUDIO] sheet progress: "+String(e).slice(0,150));
  }
  const total=source.segments.length;
  const validHash={};
  source.segments.forEach(function(seg){validHash[String(seg.id)]=seg.source_hash;});
  let terms=[];
  try{terms=skNQTerms_();}catch(e){
    Logger.log("[NATIVE-STUDIO] glossary: "+String(e).slice(0,150));
  }
  const results=[],blockers=[];
  let translationDone=0,qaDone=0,audioDone=0;
  ["en"].concat(SK_NEXT_LANGS).forEach(function(lang,ix){
    const textSelected=lang!=="en" && selectedTexts.indexOf(lang)>=0;
    const audioSelected=selectedAudio.indexOf(lang)>=0;
    if(!textSelected && !audioSelected)return;
    let count=lang==="en"?total:0;
    if(lang!=="en"){
      sheetRows.forEach(function(row){
        if(String(row[5])===String(validHash[String(row[1])]||"") &&
           String(row[6+SK_NEXT_LANGS.indexOf(lang)]||"").trim())count++;
      });
    }
    const item={lang:lang,translation_count:count,
      translation_total:total,translation_ready:lang==="en",
      qa_state:lang==="en"?"english_final":"pending_translation",
      qa_reviewed:0,qa_required:0,blocked_segments:[],
      audio_state:audioSelected?"pending":"not_selected",
      audio_url:"",text_selected:textSelected,audio_selected:audioSelected};
    let draft=null,report=null,currentQA=false;
    if(lang!=="en"){
      try{draft=skNQDraft_(source,lang);}catch(e){
        item.qa_state="draft_revision_error";
      }
      item.translation_ready=!!draft;
      if(draft){
        translationDone++;
        report=readJsonFile_(source.folder,"sheets.qa.native."+lang+".json");
        const revision=soulkeyNextSha_(JSON.stringify({
          task:source.task,language:lang,draft:draft.draft.segments,
          english:source.segments,terms:terms}));
        currentQA=!!(report && report.revision_key===revision);
        item.qa_state=!report?"pending_qa":
          currentQA?String(report.state||"needs_review"):"stale_qa";
        item.qa_revision=currentQA?revision:"";
        if(currentQA){
          item.qa_reviewed=Number(report.summary&&report.summary.model_reviewed_pass||0);
          item.qa_required=Number(report.summary&&report.summary.model_review_required||0);
          item.blocked_segments=(report.summary&&report.summary.blocked_segment_ids||[]).slice(0,15);
          item.qa_issue=item.blocked_segments.map(function(sid){
            const v=(report.decisions||{})[String(sid)]||{};
            return String(v.reason||"待進一步審核").slice(0,100);
          }).slice(0,3).join("；");
          item.review_items=item.blocked_segments.slice(0,5).map(function(sid){
            const en=source.segments.find(function(x){return x.id===sid;})||{};
            const translated=draft.draft.segments.find(function(x){return x.id===sid;})||{};
            const decision=(report.decisions||{})[String(sid)]||{};
            return {id:sid,english:String(en.text||""),
              translation:String(translated.text||""),
              reason:String(decision.reason||"尚待人工或模型審核").slice(0,200),
              grade:String(decision.grade||"pending")};
          });
        }
        if(item.qa_state==="approved_risk_based")qaDone++;
        else if(textSelected)blockers.push(lang+": 翻譯 QA 未通過");
      }else if(textSelected)blockers.push(lang+": 初譯尚未完成");
    }
    if(audioSelected){
      try{
        const requested=skAudioPayload_(source,lang,terms);
        const receipt=skAudioReceipt_(source,lang);
        if(!requested){
          item.audio_state="pending_source";
        }else if(receipt && receipt.release_tag===requested.tag &&
          receipt.source_sha256===requested.sha){
          item.audio_state=String(receipt.status||"pending");
          if(item.audio_state==="done" && !receipt.mp3_drive_id){
            item.audio_state="missing_or_invalid_file";
            item.audio_issue="驗收紀錄缺少正式 MP3 的 Drive 檔案 ID";
          }else if(item.audio_state==="done" && receipt.mp3_drive_id){
            // Verifying the canonical filename and nonempty actual Drive
            // object keeps stale/deleted MP3s out of the release gate.
            const f=DriveApp.getFileById(receipt.mp3_drive_id);
            const expectedName=source.task+"-"+lang+"-"+
              requested.sha.slice(0,16)+".mp3";
            if(f.getName()!==expectedName || Number(f.getSize())<=0 ||
               f.isTrashed()){
              item.audio_state="missing_or_invalid_file";
              item.audio_issue="正式音檔不存在或版本檔名不一致，需重製";
            }else{
              item.audio_url="https://drive.google.com/file/d/"+
                encodeURIComponent(receipt.mp3_drive_id)+"/view";
              audioDone++;
            }
          }else if(item.audio_state==="needs_review"){
            item.audio_issue="配音超時，需修正時長";
          }
        }else if(receipt){
          item.audio_state="stale_audio";
        }
      }catch(e){
        item.audio_state="missing_or_invalid_file";
        item.audio_issue="Drive 音檔驗證失敗："+String(e&&e.message||e).slice(0,120);
      }
      if(item.audio_state!=="done")blockers.push(lang+": 正式音檔未通過");
    }
    results.push(item);
  });
  const release=blockers.length===0 &&
    selectedAudio.every(function(lang){
      return results.some(function(item){return item.lang===lang && item.audio_state==="done";});
    });
  return Object.assign(common,{
    state:release?"ready_risk_based":"processing_or_needs_review",
    can_publish:release,blockers:blockers,
    translation_done:translationDone,translation_required:selectedTexts.length,
    qa_done:qaDone,qa_required:selectedTexts.length,
    audio_done:audioDone,audio_required:selectedAudio.length,
    languages:results});
}

/**
 * Manual review requires a deliberate correction and matching text revision;
 * it never silently upgrades grade C, and never mutates the Sheets draft.
 */
function soulkeyStudioManualCorrection_(req){
  const taskId=String(req.task_id||"").trim();
  const lang=String(req.lang||"").trim();
  const segmentId=Number(req.segment_id);
  const corrected=String(req.corrected_text||"").trim();
  const expected=String(req.revision_key||"").trim();
  if(!/^P\d+-L\d+$/.test(taskId) || !SK_NEXT_LANGS.includes(lang) ||
     !Number.isInteger(segmentId) || corrected.length<4 ||
     corrected.length>12000 || !expected){
    return {source:"soulkey-bridge",type:"native_manual_review_result",
      ok:false,error:"invalid_manual_review_input",task_id:taskId,lang:lang};
  }
  const lock=LockService.getScriptLock();
  lock.waitLock(20000);
  try{
    const source=soulkeyNextSources_().find(function(x){return x.task===taskId;});
    if(!source)throw new Error("english_final_missing_or_stale");
    const draft=skNQDraft_(source,lang);
    if(!draft)throw new Error("draft_missing");
    const terms=skNQTerms_();
    const revision=soulkeyNextSha_(JSON.stringify({
      task:source.task,language:lang,draft:draft.draft.segments,
      english:source.segments,terms:terms}));
    const name="sheets.qa.native."+lang+".json";
    const report=readJsonFile_(source.folder,name);
    if(!report || report.revision_key!==revision || revision!==expected)
      throw new Error("qa_revision_changed_refresh_before_review");
    const audit=(report.audits||[]).find(function(x){return Number(x.id)===segmentId;});
    if(!audit || !audit.selected_for_ai || (audit.hard_errors||[]).length)
      throw new Error("segment_requires_structure_fix_not_manual_approval");
    const textSource=draft.draft.segments.find(function(x){
      return Number(x.id)===segmentId;
    });
    if(!textSource)throw new Error("segment_not_found");
    // Required fixed terminology cannot be removed by a human approval.
    const invalidLocked=(audit.glossary||[]).some(function(hit){
      return hit.locked && hit.target &&
        corrected.toLowerCase().indexOf(String(hit.target).toLowerCase())<0;
    });
    if(invalidLocked)throw new Error("locked_glossary_term_missing");
    const decisions=report.decisions||{};
    decisions[String(segmentId)]={
      grade:"B_verified",human_verified:true,
      reason:"人工在 SoulKey Studio 逐段確認／修正",
      corrected_text:corrected,
      verified_at:new Date().toISOString()
    };
    report.decisions=decisions;
    report.summary=skNQSummary_(report.audits,decisions);
    report.state=report.summary.state;
    report.updated_at=soulkeyNextNow_();
    report.last_error="";
    writeTextFile_(source.folder,name,JSON.stringify(report,null,2),
      "application/json");
    return {source:"soulkey-bridge",type:"native_manual_review_result",
      ok:true,task_id:taskId,lang:lang,id:segmentId,
      qa_state:report.state};
  }catch(error){
    return {source:"soulkey-bridge",type:"native_manual_review_result",
      ok:false,task_id:taskId,lang:lang,id:segmentId,
      error:String(error&&error.message||error).slice(0,230)};
  }finally{lock.releaseLock();}
}

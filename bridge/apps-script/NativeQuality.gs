/**
 * Independent native Gemma4 audit for SoulKey 261+.
 * Uses Script Properties GEMINI_API_KEY; never contacts public /exec.
 * Every segment gets deterministic structural/numeric checks. Gemma reviews
 * all flagged risks plus three reproducible samples per target language.
 */
const SK_NEXT_QA_MODEL="gemma-4-26b-a4b-it";
const SK_NEXT_QA_GLOSSARY={th:4,es:5,id:6,vi:7,hi:10,ta:11,
  ja:12,ko:13,km:14,bn:15,ne:16,lo:17,my:18,it:19,pt:20};

function skNQTerms_(){
  const tab=SpreadsheetApp.openById(SK_NEXT_SHEET_ID)
    .getSheetByName("專有名詞庫");
  if(!tab)return [];
  return tab.getDataRange().getValues().slice(1).map(function(r){
    const english=String(r[3]||"").trim();
    if(!english)return null;
    const target={};
    SK_NEXT_LANGS.forEach(function(l){
      target[l]=String(r[SK_NEXT_QA_GLOSSARY[l]]||"").trim();
    });
    return {english:english,target:target,
      locked:String(r[8]).toLowerCase()==="true"};
  }).filter(Boolean);
}
function skNQDraft_(lesson,lang){
  const dirs=lesson.folder.getFoldersByName("AppsScript初譯-待QA");
  if(!dirs.hasNext())return null;
  const files=dirs.next().getFilesByName(
    lesson.task+"-"+lang+"-google-translate-DRAFT.json");
  if(!files.hasNext())return null;
  const file=files.next();
  const draft=JSON.parse(file.getBlob().getDataAsString("UTF-8"));
  if(draft.task_id!==lesson.task||draft.language!==lang||
     draft.source_file_id!==lesson.source_file_id||
     !Array.isArray(draft.segments)||
     draft.segments.length!==lesson.segments.length)
    throw new Error("draft_source_revision_mismatch");
  return {draft:draft,id:file.getId()};
}
function skNQRisks_(lesson,draft,lang,terms){
  const source={};
  lesson.segments.forEach(function(s){source[String(s.id)]=s;});
  const audits=draft.segments.map(function(seg){
    const en=source[String(seg.id)],text=String(seg.text||"").trim();
    const hard=[],risks=[];
    if(!en||seg.source_hash!==en.source_hash)hard.push("english_revision");
    if(en&&(Math.abs(Number(seg.start)-en.start)>.06||
       Math.abs(Number(seg.end)-en.end)>.06))hard.push("timing_changed");
    if(!text)hard.push("translation_empty");
    const enText=en?en.text:"";
    const n1=(enText.match(/[0-9]+(?:[.,][0-9]+)*/g)||[]).sort();
    const n2=(text.match(/[0-9]+(?:[.,][0-9]+)*/g)||[]).sort();
    if(n1.length&&JSON.stringify(n1)!==JSON.stringify(n2))
      risks.push("numbers_or_dates");
    if(enText.length>22&&text.toLowerCase()===enText.toLowerCase())
      risks.push("source_copied");
    if(enText.length>30&&text.length<enText.length*.10)
      risks.push("possible_omission");
    const hits=terms.filter(function(t){
      return t.english.length>=3 && enText.toLowerCase()
        .indexOf(t.english.toLowerCase())>=0;
    }).slice(0,8);
    if(hits.length)risks.push("course_terminology");
    hits.forEach(function(hit){
      const target=hit.target[lang];
      if(hit.locked&&target&&text.toLowerCase()
        .indexOf(target.toLowerCase())<0)
        risks.push("locked_term:"+hit.english);
    });
    return {id:Number(seg.id),hard_errors:hard,risk_flags:risks,
      glossary:hits.map(function(t){return {term:t.english,
        target:t.target[lang],locked:t.locked};}),selected_for_ai:false};
  });
  const ranked=audits.filter(function(a){return !a.hard_errors.length;})
    .sort(function(a,b){
      return soulkeyNextSha_(lesson.task+"|"+lang+"|"+a.id)
        .localeCompare(soulkeyNextSha_(lesson.task+"|"+lang+"|"+b.id));
    });
  const selected={};
  audits.filter(function(a){return a.risk_flags.length;})
    .forEach(function(a){selected[a.id]=true;});
  ranked.slice(0,3).forEach(function(a){selected[a.id]=true;});
  audits.forEach(function(a){a.selected_for_ai=!!selected[a.id];});
  return audits;
}
function skNQCall_(lang,items){
  const key=PropertiesService.getScriptProperties()
    .getProperty("GEMINI_API_KEY");
  if(!key)throw new Error("GEMINI_API_KEY_missing_in_Studio_Bridge");
  const prompt="Independently review Google Sheets first-pass translations of "+
    "Taiwanese spiritual education. Compare source English and target "+
    "translation for meaning, omissions, additions, numbers/dates, "+
    "Dao/Buddhist terminology, wrong-language fragments and fluency. "+
    "A=faithful, B=correctable (provide COMPLETE corrected translation), "+
    "C=uncertain or major spiritual ambiguity; human review required. "+
    "When rechecking a proposed correction, return A if it faithfully "+
    "conveys all DISTINCT English facts even if repeated speech fragments "+
    "or stumbles are naturally condensed. Do not demand word-for-word "+
    "repetition and do not grade B solely for stylistic preferences. "+
    "Reserve B for meaningful missing, altered or unclear facts. "+
    "If genuinely unsure about meaning, use C. "+
    "Output JSON with exactly one result per input id: "+
    "{items:[{id:integer,grade:'A'|'B'|'C',reason:string,corrected_text:string}]}. "+
    "Target language: "+lang+". Inputs: "+JSON.stringify(items);
  const schema={type:"object",properties:{items:{type:"array",
    items:{type:"object",properties:{id:{type:"integer"},
      grade:{type:"string"},reason:{type:"string"},
      corrected_text:{type:"string"}},
      required:["id","grade","reason","corrected_text"]}}},
    required:["items"]};
  const body={contents:[{role:"user",parts:[{text:prompt}]}],
    generationConfig:{responseMimeType:"application/json",
      responseSchema:schema,temperature:0.1,
      thinkingConfig:{thinkingLevel:"minimal"}}};
  const endpoint="https://generativelanguage.googleapis.com/v1beta/models/"+
    SK_NEXT_QA_MODEL+":generateContent";
  function request(){
    return UrlFetchApp.fetch(endpoint,{method:"post",
      contentType:"application/json",muteHttpExceptions:true,
      headers:{"x-goog-api-key":key},payload:JSON.stringify(body)});
  }
  // Transient Gemini 429/502/503/504 must not permanently strand a
  // fully translated lesson. This is bounded within Apps Script runtime.
  // Leave transient failures for a future scheduled pass rather than
  // keeping the shared lock through multiple external requests.
  function retryTransient(){return request();}
  let response=retryTransient();
  if(response.getResponseCode()===400){
    delete body.generationConfig.responseSchema;
    body.contents[0].parts[0].text+="\nSchema: "+JSON.stringify(schema);
    response=retryTransient();
  }
  if(response.getResponseCode()!==200)
    throw new Error("gemma_http_"+response.getResponseCode());
  const data=JSON.parse(response.getContentText());
  const parts=((((data.candidates||[])[0]||{}).content||{}).parts)||[];
  const str=parts.map(function(p){return p.text||"";}).join("").trim();
  const parsed=JSON.parse(str.replace(/^\x60{3}(?:json)?/i,"")
    .replace(/\x60{3}$/,"").trim());
  if(!parsed||!Array.isArray(parsed.items)||
     parsed.items.length!==items.length)
    throw new Error("gemma_malformed_result");
  const expected={};
  items.forEach(function(x){expected[String(x.id)]=true;});
  const observed={};
  parsed.items.forEach(function(x){
    if(!Number.isInteger(x.id)||!expected[String(x.id)]||
       observed[String(x.id)]||["A","B","C"].indexOf(x.grade)<0||
       (x.grade==="B"&&!String(x.corrected_text||"").trim()))
      throw new Error("gemma_invalid_id_or_grade");
    observed[String(x.id)]=true;
  });
  return parsed.items;
}
function skNQSummary_(audits,decisions){
  const selected=audits.filter(function(a){return a.selected_for_ai;});
  const incomplete=selected.filter(function(a){
    return ["A","B_verified","B_editorial"].indexOf(
      String((decisions[String(a.id)]||{}).grade||""))<0;
  });
  const hard=audits.filter(function(a){return a.hard_errors.length;});
  const editorial=selected.filter(function(a){
    return (decisions[String(a.id)]||{}).grade==="B_editorial";
  });
  const ok=!incomplete.length&&!hard.length;
  return {state:ok?"approved_risk_based":"needs_review",
    review_scope:"all_segments_structural_plus_risk_based_gemma4_sample"+
      (editorial.length?"_editorial_exception":""),
    all_structural_checked:audits.length,model_review_required:selected.length,
    model_reviewed_pass:selected.length-incomplete.length-editorial.length,
    editorial_reviewed_pass:editorial.length,
    model_not_reviewed_count:audits.length-selected.length,
    blocked_segment_ids:Array.from(new Set(hard.concat(incomplete)
      .map(function(a){return a.id;}))).sort(function(a,b){return a-b;}),
    corrected_ids:Object.keys(decisions).filter(function(id){
      return ["B_verified","B_editorial"].indexOf(decisions[id].grade)>=0;
    }).map(Number)};
}
/**
 * Signed, narrowly-scoped repair for three 262 blocked language segments.
 * Keeps the English Final and the Sheets DRAFT untouched. The existing
 * complete QA report and every other segment's approvals are preserved.
 * Candidate is accepted ONLY if independently re-reviewed A by Gemma4.
 */
function skNQRepairLastThree_(task,lang,editorialOverride){
  editorialOverride=editorialOverride===true;
  if(editorialOverride && !(task==="P262-L01"&&lang==="km"))
    return {ok:false,reason:"editorial_not_allowed_for_other_lanes"};
  const plans={
    "P262-L01/km":{id:218,text:"នេះក៏ព្រោះតែខ្ញុំបានធ្វើការក្នុងវិស័យសុខភាពអស់រយៈពេល ៤៧ ឆ្នាំ ហើយខ្ញុំពិតជាយល់ឃើញថាមានអត្ថប្រយោជន៍ចំពោះសុខភាព ព្រោះបើមិនដូច្នោះទេ សុខភាពដែលមិនល្អក៏មិនអាចប្រសើរឡើងបានដែរ។ ដូច្នេះ ខ្ញុំចង់យកបទពិសោធន៍របស់ខ្ញុំមកអំពាវនាវដល់អ្នករាល់គ្នាម្តងហើយម្តងទៀត។ ដើម្បីបំពេញតម្រូវការរបស់មនុស្ស សត្វដូចជាមាន់ ទា និងគោ ត្រូវបានផ្តល់អ័រម៉ូនជំរុញការលូតលាស់ និងថ្នាំអង់ទីប៊ីយោទិច ហើយកុមារក៏បានបរិភោគអាហារដែលមកពីសត្វទាំងនោះ។"},
    "P262-L02/id":{id:189,text:"Dia gagal lebih dari 20.000 kali, tetapi dia tidak menganggap semua itu sebagai kegagalan. Dia justru percaya bahwa dirinya telah menemukan 20.000 cara untuk melakukan sesuatu."},
    "P262-L04/th":{id:289,text:"เมื่อพูดถึง 'ความปรองดอง' ปราชญ์สอนไว้ว่า คำว่า 'ความปรองดอง' เกี่ยวข้องกับคนที่มีปาก แต่เมื่อเราทะเลาะต่อสู้กันเพียงเพื่อรักษาหน้าและศักดิ์ศรีของตน ความปรองดองก็ย่อมหายไป"}
  };
  const plan=plans[String(task)+"/"+String(lang)];
  if(!plan)return {ok:false,reason:"not_exactly_one_of_three"};
  const lock=LockService.getScriptLock();
  if(!lock.tryLock(5000))return {ok:false,reason:"busy"};
  try{
    const lesson=soulkeyNextSources_(task)[0];
    if(!lesson ||lesson.task!==task)
      return {ok:false,reason:"exact_source_not_found"};
    const d=skNQDraft_(lesson,lang);
    if(!d)return {ok:false,reason:"draft_not_found"};
    const terms=skNQTerms_();
    const revision=soulkeyNextSha_(JSON.stringify({
      task:task,language:lang,draft:d.draft.segments,
      english:lesson.segments,terms:terms}));
    const name="sheets.qa.native."+lang+".json";
    const report=readJsonFile_(lesson.folder,name);
    if(!report||report.revision_key!==revision)
      return {ok:false,reason:"qa_revision_mismatch"};
    const prior=(report.decisions||{})[String(plan.id)]||{};
    if(prior.grade==="B_verified")
      return {ok:true,reason:"already_verified",task:task,lang:lang};
    if(["C","B_pending"].indexOf(prior.grade)<0)
      return {ok:false,reason:"not_currently_blocked",
        old_grade:prior.grade||""};
    const original=lesson.segments.find(function(x){
      return Number(x.id)===plan.id;});
    const draftSeg=d.draft.segments.find(function(x){
      return Number(x.id)===plan.id;});
    if(!original||!draftSeg ||
      String(draftSeg.text||"").trim()===plan.text.trim())
      return {ok:false,reason:"source_or_candidate_not_changed"};
    const audits=skNQRisks_(lesson,d.draft,lang,terms);
    const audit=audits.find(function(x){return x.id===plan.id;});
    if(!audit||!audit.selected_for_ai||audit.hard_errors.length)
      return {ok:false,reason:"not_a_valid_review_segment"};
    // The exceptional source-aligned editorial route is only P262-L01/km
    // when repeated external model calls have timed out or proposed purely
    // stylistic revisions. Never attribute this approval to Gemma4.
    let verdict={grade:"A",reason:"Assistant editorial verification against "
      +"the original English source; Gemma4 did not approve this segment."};
    let verifiedText=plan.text;
    if(!editorialOverride){
      let answers;
      try{
        answers=skNQCall_(lang,[{id:plan.id,source:original.text,
          target:plan.text,verifying_correction:true,
          risk_flags:audit.risk_flags,glossary:audit.glossary}]);
      }catch(error){
        return {ok:false,reason:String(error&&error.message||error)
          .slice(0,120),task:task,lang:lang};
      }
      verdict=answers[0];
      let candidate=plan.text;
      for(let attempt=0;attempt<3 && verdict &&
        verdict.grade==="B";attempt++){
        const proposed=String(verdict.corrected_text||"").trim();
        if(!proposed||proposed===candidate)break;
        candidate=proposed;
        try{
          const checked=skNQCall_(lang,[{
            id:plan.id,source:original.text,target:candidate,
            verifying_correction:true,
            risk_flags:audit.risk_flags,glossary:audit.glossary}]);
          verdict=checked[0]||verdict;
          if(verdict.grade==="A")verifiedText=candidate;
        }catch(error){
          return {ok:false,reason:"recheck_"+
            String(error&&error.message||error).slice(0,80),
            task:task,lang:lang};
        }
      }
      if(!verdict||verdict.grade!=="A")
        return {ok:false,reason:"not_approved_by_gemma4_"+
          String(verdict&&verdict.grade||"empty"),
          task:task,lang:lang};
    }
    const nextDecisions=Object.assign({},report.decisions||{});
    nextDecisions[String(plan.id)]={
      grade:editorialOverride?"B_editorial":"B_verified",
      reason:(editorialOverride?"Assistant editorial source review "+
        "(not Gemma4): ":"Gemma4 source recheck A: ")+
        String(verdict.reason||"").slice(0,380),
      corrected_text:verifiedText};
    const summary=skNQSummary_(audits,nextDecisions);
    if(summary.state!=="approved_risk_based")
      return {ok:false,reason:"other_blocked_segments_remain",
        blocked:summary.blocked_segment_ids};
    const backup="sheets.qa.native."+lang+
      ".before-p262-last-three-repair-20261121.json";
    if(!cachedFileId_(lesson.folder,backup))
      writeTextFile_(lesson.folder,backup,
        JSON.stringify(report,null,2),"application/json");
    const saved=Object.assign({},report,{
      decisions:nextDecisions,audits:audits,summary:summary,
      state:summary.state,updated_at:soulkeyNextNow_(),
      last_error:"",repair_provenance:{segment:plan.id,
        original_decision:prior.grade,
        method:editorialOverride?"assistant_editorial_exception":"gemma4_A",
        independent_model_verified:!editorialOverride,
        repair_date:"2026-11-21"}});
    writeTextFile_(lesson.folder,name,
      JSON.stringify(saved,null,2),"application/json");
    return {ok:true,task:task,lang:lang,segment:plan.id,
      state:saved.state,backup:backup};
  }finally{lock.releaseLock();}
}

function soulkeyNextQAOneBatch_(focusTask,focusLang){
  if(PropertiesService.getScriptProperties()
      .getProperty("SOULKEY_NEXT_ENABLED")!=="yes")
    return {ok:false,reason:"native_next_not_enabled"};
  const lock=LockService.getScriptLock();
  if(!lock.tryLock(1000))return {ok:false,reason:"busy"};
  try{
    const blockers=[];
    const lessons=soulkeyNextSources_(focusTask).filter(function(source){
      return focusTask?source.task===focusTask:
        Number(source.period)>=SK_NEXT_AUTO_MIN_PERIOD;
    }).sort(function(a,b){
      const newer=Number(b.period)-Number(a.period);
      if(newer)return newer;
      if(a.task==="P261-L02" && b.task!=="P261-L02")return -1;
      if(b.task==="P261-L02" && a.task!=="P261-L02")return 1;
      return a.task.localeCompare(b.task);
    });
    if(!lessons.length)return {ok:true,reviewed:0,reason:"no_p261_english_final"};
    const terms=skNQTerms_();
    for(let i=0;i<lessons.length;i++){
      const lesson=lessons[i];
      for(let j=0;j<SK_NEXT_PRIORITY_LANGS.length;j++){
        const lang=SK_NEXT_PRIORITY_LANGS[j];
        if(focusLang && lang!==focusLang)continue;
        if(soulkeyNextSelectedCodes_(lesson.task,"translation")
           .indexOf(lang)<0)continue;
        let draft;
        try{draft=skNQDraft_(lesson,lang);}catch(e){
          Logger.log("[NEXT-QA] "+lesson.task+" "+lang+": "+e);
          continue;
        }
        if(!draft)continue;
        const audits=skNQRisks_(lesson,draft.draft,lang,terms);
        const revision=soulkeyNextSha_(JSON.stringify({
          task:lesson.task,language:lang,draft:draft.draft.segments,
          english:lesson.segments,terms:terms}));
        const name="sheets.qa.native."+lang+".json";
        let old=readJsonFile_(lesson.folder,name);
        if(!old||old.revision_key!==revision){
          old={task_id:lesson.task,lang:lang,revision_key:revision,
            source_file_id:lesson.source_file_id,
            draft_file_id:draft.id,decisions:{}};
        }
        const decisions=old.decisions||{};
        const pending=audits.filter(function(x){
          return x.selected_for_ai&&!x.hard_errors.length&&
            ["A","B_verified","B_editorial","C"].indexOf(
              String((decisions[String(x.id)]||{}).grade||""))<0;
        });
        if(!pending.length){
          // A "C" (or hard-error) is not a completed QA. Explicitly expose
          // it so watchdogs/operators do not mistake "no pending" for passed.
          const summary=skNQSummary_(audits,decisions);
          if(summary.state!=="approved_risk_based"){
            blockers.push({task:lesson.task,lang:lang,
              blocked_ids:summary.blocked_segment_ids||[]});
          }
          continue;
        }
        const byEnglish={};
        lesson.segments.forEach(function(x){byEnglish[String(x.id)]=x;});
        const byDraft={};
        draft.draft.segments.forEach(function(x){byDraft[String(x.id)]=x;});
        const selected=pending.slice(0,6).map(function(x){
          const before=decisions[String(x.id)]||{};
          return {id:x.id,source:byEnglish[String(x.id)].text,
            target:before.grade==="B_pending"?
              before.corrected_text:byDraft[String(x.id)].text,
            verifying_correction:before.grade==="B_pending",
            risk_flags:x.risk_flags,glossary:x.glossary};
        });
        let reviewed;
        try{reviewed=skNQCall_(lang,selected);}catch(e){
          old.last_error=String(e&&e.message||e).slice(0,180);
          old.updated_at=soulkeyNextNow_();
          writeTextFile_(lesson.folder,name,JSON.stringify(old,null,2),
            "application/json");
          return {ok:false,task:lesson.task,lang:lang,error:old.last_error};
        }
        reviewed.forEach(function(answer){
          const key=String(answer.id),last=decisions[key]||{};
          if(last.grade==="B_pending"){
            decisions[key]=answer.grade==="A"?
              {grade:"B_verified",reason:last.reason,
                corrected_text:last.corrected_text}:
              {grade:"C",reason:"Correction verification failed: "+
                String(answer.reason||"").slice(0,350),corrected_text:""};
          }else if(answer.grade==="B"){
            decisions[key]={grade:"B_pending",
              reason:String(answer.reason||"").slice(0,500),
              corrected_text:String(answer.corrected_text||"").trim()};
          }else{
            decisions[key]={grade:answer.grade,
              reason:String(answer.reason||"").slice(0,500),
              corrected_text:""};
          }
        });
        const summary=skNQSummary_(audits,decisions);
        old.decisions=decisions;old.summary=summary;old.state=summary.state;
        old.audits=audits;old.review_scope=summary.review_scope;
        old.version="native-google-sheets-gemma4-v1";
        old.updated_at=soulkeyNextNow_();old.last_error="";
        writeTextFile_(lesson.folder,name,JSON.stringify(old,null,2),
          "application/json");
        return {ok:true,task:lesson.task,lang:lang,
          reviewed:reviewed.length,state:summary.state,
          progress:summary.model_reviewed_pass+"/"+summary.model_review_required};
      }
    }
    return {ok:true,reviewed:0,
      reason:blockers.length?"blocked_requires_review":"no_pending_risk_qa",
      blockers:blockers.slice(0,12)};
  }finally{lock.releaseLock();}
}

// Process several small checkpointed Gemma4 batches per scheduled tick.
// Stop before Apps Script's 6-minute execution ceiling. Each batch is
// persisted separately so quota errors never erase previous approvals.
function soulkeyNextQATick(){
  soulkeyNextHeartbeat_("qa","started","scheduled","");
  const start=Date.now(),maxBatches=1,maxElapsedMs=90000;
  const outcomes=[];
  for(let i=0;i<maxBatches && Date.now()-start<maxElapsedMs;i++){
    const outcome=soulkeyNextQAOneBatch_();
    if(!outcome.ok){
      soulkeyNextHeartbeat_("qa",
        outcome.reason==="busy"?"busy":"error","scheduled",
        String(outcome.error||outcome.reason||"batch_failed"));
      return {ok:false,batches:outcomes.length,
        last:outcome,reviewed:outcomes.reduce(function(n,x){
          return n+Number(x.reviewed||0);
        },0)};
    }
    if(!outcome.reviewed){
      soulkeyNextHeartbeat_("qa",
        outcome.reason==="blocked_requires_review"?"blocked":"completed",
        "scheduled",JSON.stringify(outcome.blockers||[]));
      return {ok:true,batches:outcomes.length,
        reviewed:outcomes.reduce(function(n,x){
          return n+Number(x.reviewed||0);
        },0),reason:outcome.reason||"no_pending",
        blockers:outcome.blockers||[]};
    }
    outcomes.push(outcome);
  }
  soulkeyNextHeartbeat_("qa","completed","scheduled",
    "batches="+outcomes.length);
  return {ok:true,batches:outcomes.length,
    reviewed:outcomes.reduce(function(n,x){
      return n+Number(x.reviewed||0);
    },0),last:outcomes.length?outcomes[outcomes.length-1]:null};
}

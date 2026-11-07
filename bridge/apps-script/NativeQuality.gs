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
    "When rechecking a proposed correction, return A only if the corrected "+
    "text faithfully conveys the entire English meaning. If unsure use C. "+
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
  let response=request();
  if(response.getResponseCode()===400){
    delete body.generationConfig.responseSchema;
    body.contents[0].parts[0].text+="\nSchema: "+JSON.stringify(schema);
    response=request();
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
    return ["A","B_verified"].indexOf(
      String((decisions[String(a.id)]||{}).grade||""))<0;
  });
  const hard=audits.filter(function(a){return a.hard_errors.length;});
  const ok=!incomplete.length&&!hard.length;
  return {state:ok?"approved_risk_based":"needs_review",
    review_scope:"all_segments_structural_plus_risk_based_gemma4_sample",
    all_structural_checked:audits.length,model_review_required:selected.length,
    model_reviewed_pass:selected.length-incomplete.length,
    model_not_reviewed_count:audits.length-selected.length,
    blocked_segment_ids:Array.from(new Set(hard.concat(incomplete)
      .map(function(a){return a.id;}))).sort(function(a,b){return a-b;}),
    corrected_ids:Object.keys(decisions).filter(function(id){
      return decisions[id].grade==="B_verified";
    }).map(Number)};
}
function soulkeyNextQATick(){
  if(PropertiesService.getScriptProperties()
      .getProperty("SOULKEY_NEXT_ENABLED")!=="yes")
    return {ok:false,reason:"native_next_not_enabled"};
  const lock=LockService.getScriptLock();
  if(!lock.tryLock(1000))return {ok:false,reason:"busy"};
  try{
    const lessons=soulkeyNextSources_();
    if(!lessons.length)return {ok:true,reviewed:0,reason:"no_p261_english_final"};
    const terms=skNQTerms_();
    for(let i=0;i<lessons.length;i++){
      const lesson=lessons[i];
      for(let j=0;j<SK_NEXT_LANGS.length;j++){
        const lang=SK_NEXT_LANGS[j];
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
            ["A","B_verified","C"].indexOf(
              String((decisions[String(x.id)]||{}).grade||""))<0;
        });
        if(!pending.length)continue;
        const byEnglish={};
        lesson.segments.forEach(function(x){byEnglish[String(x.id)]=x;});
        const byDraft={};
        draft.draft.segments.forEach(function(x){byDraft[String(x.id)]=x;});
        const selected=pending.slice(0,3).map(function(x){
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
    return {ok:true,reviewed:0,reason:"no_pending_risk_qa"};
  }finally{lock.releaseLock();}
}

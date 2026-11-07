/**
 * SoulKey period 261+ Google Sheets-first translation recovery.
 *
 * Runs entirely INSIDE the authorized Apps Script project via an installable
 * clock trigger, not the currently blocked public /exec webhook.
 * Never overwrites P260 or its existing official outputs.
 * Independent Gemma 4 QA and official audio remain separate stages.
 */
const SK_NEXT_SHEET_ID = "1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8";
const SK_NEXT_LANGS = ["th","es","id","vi","hi","ta","ja","ko",
  "km","bn","ne","lo","my","it","pt"];
const SK_NEXT_TAB = "AppsScript初譯";
const SK_NEXT_JOBS_TAB = "AppsScript初譯任務";
const SK_NEXT_LIMIT_PER_TICK = 85;
const SK_NEXT_MAX_MS = 190000;
const SK_NEXT_DAILY_LIMIT = 3800;

function soulkeyNextSha_(value) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
      String(value),Utilities.Charset.UTF_8)
    .map(function(b){return ("0"+(b&255).toString(16)).slice(-2);}).join("");
}
function soulkeyNextNow_() {
  return Utilities.formatDate(new Date(),"Asia/Taipei","yyyy-MM-dd HH:mm:ss");
}
function soulkeyNextSources_(){
  const tasks=readTasks_().filter(function(t){
    return Number(t.period)>=261 && t.en==="完成" &&
      /^P\d+-L\d+$/.test(t.id);
  }).sort(function(a,b){
    return a.period-b.period || a.id.localeCompare(b.id);
  }).slice(0,24);
  const sources=[];
  tasks.forEach(function(task){
    try{
      const folders=lessonFolders_(task.id);
      const enId=cachedFileId_(folders.translation,"en.final.json");
      if(!enId) return;
      const en=readJsonFile_(folders.translation,"en.final.json");
      if(!en || !Array.isArray(en.segments) || !en.segments.length)
        return;
      const seen={};
      const segments=en.segments.map(function(x){
        const id=Number(x.id),start=Number(x.start),end=Number(x.end);
        const text=String(x.text||"").trim();
        if(!Number.isInteger(id)||seen[id]||!Number.isFinite(start)||
           !Number.isFinite(end)||end<=start||!text)
          throw new Error("invalid_en_segment:"+x.id);
        seen[id]=true;
        return {id:id,start:start,end:end,text:text,
          source_hash:soulkeyNextSha_(text)};
      });
      segments.sort(function(a,b){return a.id-b.id;});
      sources.push({task:task.id,period:task.period,lesson:task.lesson,
        source_file_id:enId,folder:folders.translation,segments:segments});
    }catch(e){
      Logger.log("[NEXT-SHEETS] "+task.id+" "+String(e&&e.message||e));
    }
  });
  return sources;
}
function soulkeyNextEnsureRows_(sources){
  const spreadsheet=SpreadsheetApp.openById(SK_NEXT_SHEET_ID);
  const tab=spreadsheet.getSheetByName(SK_NEXT_TAB);
  if(!tab) throw new Error("missing AppsScript initial translation worksheet");
  const width=25;
  const all=tab.getLastRow()>1?
    tab.getRange(2,1,tab.getLastRow()-1,width).getValues():[];
  const index={};
  all.forEach(function(r,i){
    const task=String(r[0]||""),id=Number(r[1]);
    if(/^P\d+-L\d+$/.test(task)&&Number.isInteger(id))
      index[task+":"+id]={row:i+2,data:r};
  });
  let added=0,invalidated=0;
  const append=[];
  sources.forEach(function(source){
    source.segments.forEach(function(seg){
      const key=source.task+":"+seg.id;
      const saved=index[key];
      const data=[source.task,seg.id,seg.start,seg.end,seg.text,
          seg.source_hash].concat(Array(15).fill(""),
          [0,"待Gemma QA",soulkeyNextNow_(),""]);
      if(!saved){
        append.push(data); added++;
      }else if(String(saved.data[5]||"")!==seg.source_hash ||
          String(saved.data[4]||"")!==seg.text ||
          Number(saved.data[2])!==seg.start ||
          Number(saved.data[3])!==seg.end){
        // English was edited. Only invalidate this segment's 15 languages;
        // the previously approved English revision must never be mixed in.
        tab.getRange(saved.row,1,1,width).setValues([data]);
        invalidated++;
      }
    });
  });
  if(append.length)
    tab.getRange(tab.getLastRow()+1,1,append.length,width).setValues(append);
  return {added:added,invalidated:invalidated};
}
function soulkeyNextQuota_(){
  const p=PropertiesService.getScriptProperties();
  const day=Utilities.formatDate(new Date(),"Asia/Taipei","yyyy-MM-dd");
  const prev=String(p.getProperty("SOULKEY_NEXT_SHEETS_DAY")||"");
  if(prev!==day){
    p.setProperty("SOULKEY_NEXT_SHEETS_DAY",day);
    p.setProperty("SOULKEY_NEXT_SHEETS_USED","0");
  }
  return {props:p,used:Number(p.getProperty("SOULKEY_NEXT_SHEETS_USED")||0)};
}
function soulkeyNextExport_(sources,allRows){
  const files=[];
  sources.forEach(function(source){
    const lessonRows=allRows.filter(function(r){
      return String(r[0]||"")===source.task;
    });
    if(lessonRows.length!==source.segments.length) return;
    const byId={};
    lessonRows.forEach(function(row){byId[String(row[1])]=row;});
    let draftsFolder;
    SK_NEXT_LANGS.forEach(function(lang,langIndex){
      const rows=source.segments.map(function(seg){return byId[String(seg.id)];});
      if(rows.some(function(row,i){return !row ||
          String(row[5]||"")!==source.segments[i].source_hash ||
          !String(row[6+langIndex]||"").trim();})) return;
      if(!draftsFolder){
        const existing=source.folder.getFoldersByName("AppsScript初譯-待QA");
        draftsFolder=existing.hasNext()?existing.next():
          source.folder.createFolder("AppsScript初譯-待QA");
      }
      const filename=source.task+"-"+lang+"-google-translate-DRAFT.json";
      const payload={
        task_id:source.task,language:lang,engine:"LanguageApp.translate",
        status:"pending_Gemma4_QA",
        source:"approved English human final",
        source_file_id:source.source_file_id,
        generated_at:soulkeyNextNow_(),
        segments:rows.map(function(r){
          return {id:Number(r[1]),start:Number(r[2]),end:Number(r[3]),
            text:String(r[6+langIndex]),source_hash:String(r[5])};
        })
      };
      const existing=draftsFolder.getFilesByName(filename);
      if(existing.hasNext()){
        const file=existing.next();
        try{
          const old=JSON.parse(file.getBlob().getDataAsString("UTF-8"));
          if(old.source_file_id===payload.source_file_id &&
             JSON.stringify(old.segments)===JSON.stringify(payload.segments)){
            return;
          }
        }catch(_){}
        file.setContent(JSON.stringify(payload,null,2));
      }else{
        draftsFolder.createFile(filename,JSON.stringify(payload,null,2),
          MimeType.PLAIN_TEXT);
      }
      files.push({task:source.task,lang:lang});
    });
  });
  return files;
}
function soulkeyNextUpdateJobs_(sources,rows){
  const tab=SpreadsheetApp.openById(SK_NEXT_SHEET_ID)
    .getSheetByName(SK_NEXT_JOBS_TAB);
  if(!tab) return;
  const existing=tab.getLastRow()>1?
    tab.getRange(2,1,tab.getLastRow()-1,12).getValues():[];
  const index={};
  existing.forEach(function(x,i){index[String(x[0])]=i+2;});
  sources.forEach(function(s){
    const items=rows.filter(function(r){return String(r[0])===s.task;});
    let count=0;
    items.forEach(function(r){
      for(let i=0;i<15;i++)if(String(r[6+i]||"").trim()) count++;
    });
    const expected=s.segments.length*15;
    const row=[s.task,soulkeyNextSha_(JSON.stringify(
      s.segments.map(function(x){return [x.id,x.start,x.end,x.text];}))),
      s.segments.length,count,expected,
      count===expected?"待Gemma QA":count?"翻譯中":"待翻譯",
      soulkeyNextNow_(),"",s.source_file_id,
      "full",count===expected?"待QA":"翻譯中",
      "P261+ Sheets-first automatic job; not a semantic QA approval"];
    const pos=index[s.task]||tab.getLastRow()+1;
    tab.getRange(pos,1,1,12).setValues([row]);
  });
}
function soulkeyNextTick(){
  const props=PropertiesService.getScriptProperties();
  if(props.getProperty("SOULKEY_NEXT_ENABLED")!=="yes")
    return {ok:false,reason:"native_next_not_enabled"};
  const lock=LockService.getScriptLock();
  if(!lock.tryLock(5000))return {ok:false,reason:"busy"};
  try{
    const start=Date.now();
    const sources=soulkeyNextSources_();
    if(!sources.length)return {ok:true,lessons:0,note:"Awaiting P261+ English Final"};
    const seeded=soulkeyNextEnsureRows_(sources);
    const active={};
    sources.forEach(function(s){active[s.task]=s;});
    const book=SpreadsheetApp.openById(SK_NEXT_SHEET_ID);
    const tab=book.getSheetByName(SK_NEXT_TAB);
    const quota=soulkeyNextQuota_();
    const rows=tab.getLastRow()>1?
      tab.getRange(2,1,tab.getLastRow()-1,25).getValues():[];
    let translated=0,failed=0,requests=0;
    for(let i=0;i<rows.length;i++){
      if(requests>=SK_NEXT_LIMIT_PER_TICK||
         quota.used>=SK_NEXT_DAILY_LIMIT||
         Date.now()-start>SK_NEXT_MAX_MS) break;
      const row=rows[i],s=active[String(row[0]||"")];
      if(!s)continue;
      const original=s.segments.find(function(x){return x.id===Number(row[1]);});
      if(!original||String(row[5])!==original.source_hash)continue;
      let changed=false,issue="";
      for(let langIndex=0;langIndex<15;langIndex++){
        if(requests>=SK_NEXT_LIMIT_PER_TICK||
           quota.used>=SK_NEXT_DAILY_LIMIT||
           Date.now()-start>SK_NEXT_MAX_MS)break;
        if(String(row[6+langIndex]||"").trim())continue;
        requests++;quota.used++;
        // Reserve quota before the external request. A failed call is still a call.
        quota.props.setProperty("SOULKEY_NEXT_SHEETS_USED",String(quota.used));
        try{
          const result=String(LanguageApp.translate(String(row[4]),
            "en",SK_NEXT_LANGS[langIndex])||"").trim();
          if(result.length<2)throw new Error("empty_translation");
          row[6+langIndex]=result;
          translated++;changed=true;
        }catch(e){
          failed++;
          issue=SK_NEXT_LANGS[langIndex]+":"+String(e&&e.message||e).slice(0,140);
          if(failed>=6)break;
        }
      }
      if(changed||issue){
        row[21]=SK_NEXT_LANGS.reduce(function(n,l,j){
          return n+(String(row[6+j]||"").trim()?1:0);
        },0);
        row[22]=Number(row[21])===15?"待Gemma QA":"翻譯中";
        row[23]=soulkeyNextNow_();row[24]=issue;
        tab.getRange(i+2,7,1,19).setValues([row.slice(6,25)]);
      }
      if(failed>=6)break;
    }
    SpreadsheetApp.flush();
    const refreshed=tab.getLastRow()>1?
      tab.getRange(2,1,tab.getLastRow()-1,25).getValues():[];
    const exported=soulkeyNextExport_(sources,refreshed);
    soulkeyNextUpdateJobs_(sources,refreshed);
    return {ok:failed===0,active_lessons:sources.map(function(x){return x.task;}),
      seeded:seeded,requests:requests,translated:translated,failed:failed,
      exported_languages:exported,quota_used:quota.used};
  }finally{lock.releaseLock();}
}
function soulkeyNextInstall(){
  const props=PropertiesService.getScriptProperties();
  props.setProperty("SOULKEY_NEXT_ENABLED","yes");
  const others=ScriptApp.getProjectTriggers().filter(function(x){
    return x.getHandlerFunction()==="soulkeyNextTick";
  });
  if(!others.length){
    ScriptApp.newTrigger("soulkeyNextTick").timeBased()
      .everyMinutes(15).create();
  }else if(others.length>1){
    others.slice(1).forEach(function(x){ScriptApp.deleteTrigger(x);});
  }
  const reviewTriggers=ScriptApp.getProjectTriggers().filter(function(x){
    return x.getHandlerFunction()==="soulkeyNextQATick";
  });
  if(!reviewTriggers.length){
    ScriptApp.newTrigger("soulkeyNextQATick").timeBased()
      .everyMinutes(15).create();
  }else if(reviewTriggers.length>1){
    reviewTriggers.slice(1).forEach(function(x){ScriptApp.deleteTrigger(x);});
  }
  return {ok:true,trigger:"translation + Gemma QA every_15_min",
    mode:"Google internal only; no public webhook",
    lessons:soulkeyNextSources_().map(function(x){return x.task;})};
}
function soulkeyNextStop(){
  PropertiesService.getScriptProperties()
    .setProperty("SOULKEY_NEXT_ENABLED","no");
  ScriptApp.getProjectTriggers().filter(function(x){
    return ["soulkeyNextTick","soulkeyNextQATick"]
      .indexOf(x.getHandlerFunction())>=0;
  }).forEach(function(x){ScriptApp.deleteTrigger(x);});
  return {ok:true,enabled:false};
}
function soulkeyNextStatus(){
  const p=PropertiesService.getScriptProperties();
  const src=soulkeyNextSources_();
  const rows=SpreadsheetApp.openById(SK_NEXT_SHEET_ID)
    .getSheetByName(SK_NEXT_JOBS_TAB).getDataRange().getDisplayValues();
  return {enabled:p.getProperty("SOULKEY_NEXT_ENABLED")==="yes",
    trigger_count:ScriptApp.getProjectTriggers().filter(function(x){
      return x.getHandlerFunction()==="soulkeyNextTick";
    }).length,
    registered_lessons:src.map(function(x){return x.task;}),
    jobs:rows.slice(1).filter(function(x){
      return /^P\d+-L\d+$/.test(String(x[0])) &&
        Number((String(x[0]).match(/^P(\d+)/)||[])[1])>=261;
    }).map(function(x){return {task:x[0],translated:x[3],total:x[4],
      state:x[5],updated:x[6]};})};
}

/**
 * SoulKey 第260期：Google Apps Script LanguageApp 初譯測試。
 * 安全邊界：只寫入「AppsScript初譯」與「AppsScript初譯任務」兩個測試工作表；
 * 不修改任務佇列、人工定稿、既有 Gemma 翻譯或 TTS。
 *
 * 使用順序：
 *  1. soulkeyP260Seed()
 *  2. soulkeyP260Pilot()     // 四堂 × 前3段 × th/vi/km
 *  3. soulkeyP260StartFull() // 四堂 × 全段 × 15語，建立10分鐘觸發器
 *  4. soulkeyP260Status()
 *  5. soulkeyP260ExportDrafts() // 只產生獨立的「待QA」檔案
 *
 * 所有段落以已確認的英文人工定稿 JSON 為準；id/start/end 原封不動。
 */
const SK260 = Object.freeze({
  book: "1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8",
  dataTab: "AppsScript初譯",
  jobsTab: "AppsScript初譯任務",
  langs: ["th","es","id","vi","hi","ta","ja","ko","km","bn","ne","lo","my","it","pt"],
  pilotLangs: ["th","vi","km"],
  dailyLimit: 4200, // 保留配額餘裕；Google 一般帳號官方上限5,000次/日
  maxCallsPerTick: 70,
  maxMillisPerTick: 240000,
  lessons: [
    {task:"P260-L01",source:"17HLPxB4223SOvipcnygtrjTaWK8TkG26"},
    {task:"P260-L02",source:"1-JJwe1PkS-Knu0eQSD440Rhoq7YwXoTd"},
    {task:"P260-L03",source:"1DTKoTlP3ePAYVGdB0IEZ1-7R3dCHELl_"},
    {task:"P260-L04",source:"1IVnlZY6eEe1v1_ielp5SXqGmCXIWPQs2"}
  ]
});
const SK260_HEADERS = ["task_id","segment_id","start","end","en_final","source_hash",
 "th","es","id","vi","hi","ta","ja","ko","km","bn","ne","lo","my","it","pt",
 "completed_count","qa_status","updated_at","issue"];
const SK260_JOB_HEADERS = ["task_id","source_revision","total_segments",
 "translated_cells","target_cells","status","updated_at","last_error",
 "source_drive_file_id","enabled","qa_status","note"];

function sk260Book_() { return SpreadsheetApp.openById(SK260.book); }
function sk260Now_() { return Utilities.formatDate(new Date(), "Asia/Taipei", "yyyy-MM-dd HH:mm:ss"); }
function sk260Sha_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
    String(text), Utilities.Charset.UTF_8)
    .map(function(b) { return ("0" + (b & 255).toString(16)).slice(-2); }).join("");
}
function sk260EnsureTabs_() {
  const book=sk260Book_();
  [[SK260.dataTab,SK260_HEADERS],[SK260.jobsTab,SK260_JOB_HEADERS]].forEach(function(item){
    let tab=book.getSheetByName(item[0]);
    if(!tab) tab=book.insertSheet(item[0]);
    const current=tab.getRange(1,1,1,item[1].length).getDisplayValues()[0];
    if(current.every(function(x){return !String(x).trim();})){
      tab.getRange(1,1,1,item[1].length).setValues([item[1]]);
      tab.setFrozenRows(1);
    } else if(JSON.stringify(current)!==JSON.stringify(item[1])){
      throw new Error("測試表欄位與預期不符，拒絕修改："+item[0]);
    }
  });
  return book;
}
function sk260Source_(item) {
  const sourceFile=DriveApp.getFileById(item.source);
  const parsed=JSON.parse(sourceFile.getBlob().getDataAsString("UTF-8"));
  const list=parsed.segments;
  if(!Array.isArray(list)||!list.length) throw new Error(item.task+" 英文定稿缺少 segments");
  const used={};
  const segments=list.map(function(s){
    const id=Number(s.id),start=Number(s.start),end=Number(s.end);
    const text=String(s.text||"").trim();
    if(!Number.isInteger(id)||used[id]||!isFinite(start)||!isFinite(end)||end<start||!text){
      throw new Error(item.task+" 英文定稿有無效或重複段落 "+String(s.id));
    }
    used[id]=true;
    return {id:id,start:start,end:end,text:text,hash:sk260Sha_(text)};
  });
  const revision=sk260Sha_(JSON.stringify(segments.map(function(s){
    return [s.id,s.start,s.end,s.text];
  })));
  return {segments:segments,revision:revision,source:item.source};
}
/**
 * 種入第260期四堂英文定稿，已翻譯且來源hash未變的不重做。
 * 如英文修改，僅清除該段原有譯文（本測試表內），避免舊譯文被誤用。
 */
function soulkeyP260Seed() {
  const book=sk260EnsureTabs_(), tab=book.getSheetByName(SK260.dataTab);
  const jobTab=book.getSheetByName(SK260.jobsTab);
  const existing=tab.getLastRow()>1?
    tab.getRange(2,1,tab.getLastRow()-1,SK260_HEADERS.length).getValues():[];
  const byKey={};
  existing.forEach(function(r,i){
    const k=String(r[0])+":"+String(r[1]);
    if(k!=="undefined:undefined") byKey[k]={row:i+2,values:r};
  });
  let added=0,refreshed=0,preserved=0;
  const allStatus=[];
  SK260.lessons.forEach(function(item){
    const source=sk260Source_(item);
    const newRows=[];
    source.segments.forEach(function(s){
      const key=item.task+":"+s.id;
      const previous=byKey[key];
      const row=[item.task,s.id,s.start,s.end,s.text,s.hash].concat(
        Array(15).fill(""),[0,"待QA",sk260Now_(),""]);
      if(!previous) {
        newRows.push(row);
        added++;
      } else if(!String(previous.values[5]||"").trim() &&
                String(previous.values[4]||"").trim()===s.text &&
                Number(previous.values[2])===s.start &&
                Number(previous.values[3])===s.end) {
        // 手動匯入的 Google Translate 試譯：內容未變時只補上hash，不抹除翻譯。
        tab.getRange(previous.row,6).setValue(s.hash);
        preserved++;
      } else if(String(previous.values[5])!==s.hash ||
                Number(previous.values[2])!==s.start ||
                Number(previous.values[3])!==s.end) {
        // 翻譯源或時間軸變更，原譯文失效；只重設此測試資料列。
        tab.getRange(previous.row,1,1,SK260_HEADERS.length).setValues([row]);
        refreshed++;
      } else {
        preserved++;
      }
    });
    if(newRows.length) {
      const begin=tab.getLastRow()+1;
      if(begin+newRows.length-1>tab.getMaxRows()) {
        tab.insertRowsAfter(tab.getMaxRows(), begin+newRows.length-1-tab.getMaxRows());
      }
      tab.getRange(begin,1,newRows.length,SK260_HEADERS.length).setValues(newRows);
    }
    allStatus.push({task:item.task,revision:source.revision,
      segments:source.segments.length,source:item.source});
  });
  sk260RefreshJobs_(allStatus);
  return {ok:true,added:added,refreshed:refreshed,preserved:preserved,
    source_segments:allStatus.map(function(s){return [s.task,s.segments];}),
    data_tab:SK260.dataTab};
}
function sk260RefreshJobs_(sources) {
  const book=sk260Book_(),tab=book.getSheetByName(SK260.dataTab);
  const jobs=book.getSheetByName(SK260.jobsTab);
  const values=tab.getLastRow()>1?
    tab.getRange(2,1,tab.getLastRow()-1,SK260_HEADERS.length).getValues():[];
  const old=jobs.getLastRow()>1?
    jobs.getRange(2,1,jobs.getLastRow()-1,SK260_JOB_HEADERS.length).getValues():[];
  const byTask={};
  old.forEach(function(row,i){byTask[String(row[0])]={row:i+2,values:row};});
  const results=[];
  sources.forEach(function(item){
    const related=values.filter(function(r){return r[0]===item.task;});
    let count=0;
    related.forEach(function(r){SK260.langs.forEach(function(_,i){
      if(String(r[6+i]||"").trim()) count++;
    });});
    const full=related.length===item.segments &&
      count===item.segments*SK260.langs.length;
    const previous=byTask[item.task];
    const enabled=PropertiesService.getScriptProperties().getProperty("SK260_PHASE")==="full"
      ?"full":(previous?String(previous.values[9]||"").toLowerCase():"pilot");
    const state=full?"待Gemma QA":count?"初譯中":"等待初譯";
    const row=[item.task,item.revision,item.segments,count,
      item.segments*SK260.langs.length,state,sk260Now_(),
      previous?String(previous.values[7]||""):"",item.source,
      enabled,full?"待QA":"未開始","不覆蓋正式多語、人工定稿或配音"];
    const pos=previous?previous.row:jobs.getLastRow()+1;
    jobs.getRange(pos,1,1,SK260_JOB_HEADERS.length).setValues([row]);
    results.push({task:item.task,segments:item.segments,cells:count,
      expected:row[4],state:state});
  });
  return results;
}
function sk260ReadRows_() {
  const tab=sk260Book_().getSheetByName(SK260.dataTab);
  return tab.getLastRow()>1?
    tab.getRange(2,1,tab.getLastRow()-1,SK260_HEADERS.length).getValues()
    .map(function(x,i){return {row:i+2,v:x};}):[];
}
function sk260QuotaState_() {
  // Google 官方：配額在首次請求後約24小時重設，不是台灣時間午夜。
  const now=Date.now(), props=PropertiesService.getScriptProperties();
  const started=Number(props.getProperty("SK260_QUOTA_WINDOW_START")||0);
  if(!started||now-started>=86400000) {
    props.setProperties({"SK260_QUOTA_WINDOW_START":String(now),"SK260_USED":"0"});
    return {started_at:now,used:0,props:props};
  }
  return {started_at:started,used:Number(props.getProperty("SK260_USED")||0),props:props};
}
function sk260Translate_(options) {
  const lock=LockService.getScriptLock();
  if(!lock.tryLock(5000)) return {ok:false,reason:"busy"};
  try {
    const start=Date.now(), opts=options||{},langs=opts.langs||SK260.langs;
    const maxCalls=Math.max(1,Math.min(120,Number(opts.maxCalls||SK260.maxCallsPerTick)));
    const maxMilliseconds=Math.min(250000,Number(opts.maxMillis||SK260.maxMillisPerTick));
    const maxSegments=opts.pilot?3:Infinity;
    const selected={};
    SK260.lessons.forEach(function(l){selected[l.task]=0;});
    const rows=sk260ReadRows_(),tab=sk260Book_().getSheetByName(SK260.dataTab);
    const quota=sk260QuotaState_();
    let calls=0,success=0,failed=0;
    const errors=[];
    const touched={};
    for(let i=0;i<rows.length;i++) {
      const item=rows[i],r=item.v,task=String(r[0]||"");
      if(!Object.prototype.hasOwnProperty.call(selected,task)) continue;
      // PILOT：四堂都各翻前3個英文定稿段落
      if(opts.pilot && selected[task]>=maxSegments) continue;
      selected[task]++;
      const english=String(r[4]||"").trim();
      if(!english||String(r[5]||"")!==sk260Sha_(english)) continue;
      for(let li=0;li<langs.length;li++) {
        const lang=langs[li],idx=SK260.langs.indexOf(lang);
        if(idx<0||String(r[6+idx]||"").trim()) continue;
        if(calls>=maxCalls||Date.now()-start>maxMilliseconds||
           quota.used>=SK260.dailyLimit) break;
        // 在呼叫前就佔額度，意外中斷也不超額。
        quota.used++;
        quota.props.setProperty("SK260_USED",String(quota.used));
        calls++;
        try {
          // 不合併段落以免漏字、錯位；定稿單段目前都少於1000字元。
          const translated=String(LanguageApp.translate(english,"en",lang)||"").trim();
          if(!translated||translated.length<2) throw new Error("空白翻譯");
          tab.getRange(item.row,7+idx).setValue(translated);
          r[6+idx]=translated;
          const done=SK260.langs.reduce(function(n,l,j){
            return n+(String(r[6+j]||"").trim()?1:0);
          },0);
          tab.getRange(item.row,22,1,4).setValues([[
            done,done===15?"待Gemma QA":"初譯中",sk260Now_(),""
          ]]);
          success++;
          touched[task]=true;
        } catch(e) {
          failed++;
          const err=String(e&&e.message||e).slice(0,220);
          errors.push(task+"/"+r[1]+"/"+lang+": "+err);
          tab.getRange(item.row,25).setValue(lang+": "+err);
          if(errors.length>=6) break;
        }
      }
      if(calls>=maxCalls||Date.now()-start>maxMilliseconds||
         quota.used>=SK260.dailyLimit||errors.length>=6) break;
    }
    SpreadsheetApp.flush();
    const statuses=sk260RefreshJobs_(SK260.lessons.map(function(l){
      const x=sk260Source_(l);
      return {task:l.task,revision:x.revision,segments:x.segments.length,source:l.source};
    }));
    return {ok:failed===0,calls:calls,success:success,failed:failed,
      quota_used_today:quota.used,daily_safety_limit:SK260.dailyLimit,
      elapsed_seconds:Math.round((Date.now()-start)/1000),
      statuses:statuses,errors:errors.slice(0,6)};
  } finally { lock.releaseLock(); }
}
/** 第一次先少量翻譯四堂 × 三段 × 泰／越／柬 = 36格。 */
function soulkeyP260Pilot() {
  soulkeyP260Seed();
  return sk260Translate_({pilot:true,langs:SK260.pilotLangs,maxCalls:36,maxMillis:240000});
}
/** 每次執行一批，依來源hash自動跳過已完成的格子。 */
function soulkeyP260Tick() {
  if(PropertiesService.getScriptProperties().getProperty("SK260_PHASE")!=="full"){
    return {ok:false,reason:"not_enabled"};
  }
  let result;
  try {
    result=sk260Translate_({pilot:false});
  } catch(e) {
    const reason=String(e&&e.stack||e).slice(0,500);
    // 在試驗工作表留下錯誤，避免僅在 Apps Script 執行紀錄才看得到。
    const sheet=sk260Book_().getSheetByName(SK260.jobsTab);
    if(sheet&&sheet.getLastRow()>1){
      const ids=sheet.getRange(2,1,sheet.getLastRow()-1,1).getValues();
      ids.forEach(function(row,i){
        if(/^P260-L0[1-4]$/.test(String(row[0]||""))){
          sheet.getRange(i+2,6).setValue("測試執行錯誤");
          sheet.getRange(i+2,7).setValue(sk260Now_());
          sheet.getRange(i+2,8).setValue(reason);
        }
      });
    }
    console.error(reason);
    throw e;
  }
  if(result.statuses&&result.statuses.every(function(s){return s.cells===s.expected;})){
    // 完成後自動輸出到隔離的待QA資料夾；輸出失敗時下次觸發器會重試。
    try {
      const exportResult=soulkeyP260ExportDrafts();
      result.exported_drafts=exportResult.exported;
      result.all_drafts_ready_for_QA=true;
      soulkeyP260Stop();
    } catch(err) {
      result.ok=false;
      result.export_error=String(err&&err.message||err).slice(0,240);
    }
  }
  return result;
}
/** 四堂全文15語測試：啟動10分鐘續跑觸發器，不會啟動配音。 */
function soulkeyP260StartFull() {
  soulkeyP260Seed();
  const props=PropertiesService.getScriptProperties();
  props.setProperty("SK260_PHASE","full");
  ScriptApp.getProjectTriggers().forEach(function(t){
    if(t.getHandlerFunction()==="soulkeyP260Tick") ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger("soulkeyP260Tick").timeBased().everyMinutes(10).create();
  // 首次授權可能還在進行，不在同一次6分鐘限額內再跑長批翻譯。
  return {ok:true,trigger:"every_10_min",status:soulkeyP260Status()};
}
function soulkeyP260Stop() {
  PropertiesService.getScriptProperties().setProperty("SK260_PHASE","paused");
  ScriptApp.getProjectTriggers().forEach(function(t){
    if(t.getHandlerFunction()==="soulkeyP260Tick") ScriptApp.deleteTrigger(t);
  });
  return {ok:true,stopped:true};
}
/** 執行狀態（不計入翻譯額度）。 */
function soulkeyP260Status() {
  const book=sk260Book_(),tab=book.getSheetByName(SK260.jobsTab);
  const rows=tab&&tab.getLastRow()>1?
    tab.getRange(2,1,tab.getLastRow()-1,SK260_JOB_HEADERS.length).getValues():[];
  const quota=sk260QuotaState_();
  return {phase:PropertiesService.getScriptProperties().getProperty("SK260_PHASE")||"pilot",
    quota_used_today:quota.used,
    lessons:rows.filter(function(r){return /^P260-L0[1-4]$/.test(String(r[0]));})
      .map(function(r){return {task:r[0],segments:r[2],cells:r[3],expected:r[4],
        state:r[5],updated_at:r[6],last_error:r[7]};})};
}
/**
 * 只把完整初譯輸出到各堂 02_翻譯稿/AppsScript初譯-待QA/，不寫正式翻譯檔。
 * 僅供後續 Gemma4 / 人工審核，不直接送 TTS。
 */
function soulkeyP260ExportDrafts() {
  const rows=sk260ReadRows_(),out=[];
  SK260.lessons.forEach(function(lesson){
    const group=rows.filter(function(x){return x.v[0]===lesson.task;});
    const parent=DriveApp.getFileById(lesson.source).getParents().next();
    let dest;
    const folders=parent.getFoldersByName("AppsScript初譯-待QA");
    dest=folders.hasNext()?folders.next():parent.createFolder("AppsScript初譯-待QA");
    SK260.langs.forEach(function(lang,idx){
      if(!group.length||group.some(function(x){return !String(x.v[6+idx]||"").trim();})) return;
      const payload={task_id:lesson.task,language:lang,engine:"LanguageApp.translate",
        status:"pending_Gemma4_QA",source:"approved English human final",
        source_file_id:lesson.source,generated_at:sk260Now_(),
        segments:group.map(function(item){const r=item.v;
          return {id:Number(r[1]),start:Number(r[2]),end:Number(r[3]),
            text:String(r[6+idx]),source_hash:String(r[5])};
        })};
      const filename=lesson.task+"-"+lang+"-google-translate-DRAFT.json";
      const content=JSON.stringify(payload,null,2);
      const existing=dest.getFilesByName(filename);
      if(existing.hasNext()) existing.next().setContent(content);
      else dest.createFile(filename,content,MimeType.PLAIN_TEXT);
      out.push({task:lesson.task,lang:lang,segments:group.length});
    });
  });
  return {ok:true,exported:out.length,items:out};
}
function soulkeyP260Smoke() {
  return {translate_th:LanguageApp.translate("May everyone find peace.","en","th"),
          translate_vi:LanguageApp.translate("May everyone find peace.","en","vi"),
          translate_km:LanguageApp.translate("May everyone find peace.","en","km")};
}

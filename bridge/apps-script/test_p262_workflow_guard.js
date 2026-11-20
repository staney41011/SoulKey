"use strict";
const fs=require("fs"),vm=require("vm"),assert=require("assert");
const path=require("path"),dir=__dirname;
const next=fs.readFileSync(path.join(dir,"NativeNext.gs"),"utf8");
const bridge=fs.readFileSync(path.join(dir,"Code.gs"),"utf8");
const ui=fs.readFileSync(path.join(dir,"../../studio/app-20260923-48.js"),"utf8");
assert(ui.includes('String(data.task_id||"")!==String(selectedTaskId)) return;'),
 "late JSONP review responses must be discarded on lesson switch");
assert(ui.includes('if(selectedTaskId!==taskId) return;'),
 "late async cache must not mutate the new lesson");
assert(bridge.includes('nativeSheetsAction==="repair_p262_l02"'));
assert(bridge.includes('original_backup:backupName'));
assert(bridge.includes('english_final_changed_check_manually'));
const start=next.indexOf("function soulkeyNextSources_(){");
const end=next.indexOf("function soulkeyNextEnsureRows_(",start);
assert(start>=0&&end>start);
let corrupted=true;
const tasks=[
 {id:"P262-L01",period:262,lesson:"第1堂",en:"完成"},
 {id:"P262-L02",period:262,lesson:"第2堂",en:"完成"},
 {id:"P262-L03",period:262,lesson:"第3堂",en:"完成"},
 {id:"P262-L04",period:262,lesson:"第4堂",en:"完成"}
];
const context={
 readTasks_:()=>tasks,
 lessonFolders_:t=>({translation:{task:t}}),
 cachedFileId_:()=> "file-id",
 readJsonFile_:f=>({segments:[{
   id:1,start:0,end:5,
   text:f.task==="P262-L02"&&corrupted?
     "But when she was fleeing and reached Xi'an, a bowl of porridge.":
     "This lecture explores the heart and our choices."
 }]}),
 soulkeyNextSha_:s=>String(s.length),
 Logger:{log:()=>{}}
};
vm.createContext(context);
vm.runInContext(next.slice(start,end),context);
let sources=context.soulkeyNextSources_();
assert.deepEqual(Array.from(sources,x=>x.task),["P262-L01","P262-L03","P262-L04"]);
corrupted=false;
sources=context.soulkeyNextSources_();
assert.deepEqual(Array.from(sources,x=>x.task),tasks.map(x=>x.id));
const ensureStart=next.indexOf("function soulkeyNextEnsureRows_(");
const ensureEnd=next.indexOf("function soulkeyNextQuota_(",ensureStart);
assert(ensureStart>0 && ensureEnd>ensureStart);
let maxRows=1000,inserted=0,written=0;
const sheet={
  getLastRow:()=>860,
  getMaxRows:()=>maxRows,
  insertRowsAfter:(row,count)=>{
    assert.equal(row,maxRows); assert(count>=25);
    inserted+=count; maxRows+=count;
  },
  getRange:(row,col,height,width)=>({
    getValues:()=>Array.from({length:height},()=>Array(width).fill("")),
    setValues:values=>{
      assert(row+height-1<=maxRows,"must grow grid before append");
      written+=values.length;
    }
  })
};
const growthCtx={
  SK_NEXT_SHEET_ID:"test-sheet",SK_NEXT_TAB:"AppsScript初譯",
  SpreadsheetApp:{openById:()=>({getSheetByName:()=>sheet})},
  soulkeyNextNow_:()=>"2026-11-20 18:00:00",
  soulkeyNextSheetLiteral_:x=>x
};
vm.createContext(growthCtx);
vm.runInContext(next.slice(ensureStart,ensureEnd),growthCtx);
const extra=Array.from({length:165},(_,i)=>({
 id:i,start:i*5,end:i*5+4,text:"Course-local English "+i,source_hash:"h"+i
}));
const growth=growthCtx.soulkeyNextEnsureRows_([{task:"P262-L02",segments:extra}]);
assert.equal(growth.added,165);
assert.equal(written,165);
assert(inserted>=25);
const jobsStart=next.indexOf("function soulkeyNextUpdateJobs_(");
const jobsEnd=next.indexOf("function soulkeyNextTick(",jobsStart);
assert(jobsStart>0 && jobsEnd>jobsStart);
let savedJob=null;
const jobTab={
 getLastRow:()=>1,
 getRange:()=>({setValues:values=>{savedJob=values[0];}})
};
const jobCtx={
 SK_NEXT_SHEET_ID:"test",SK_NEXT_JOBS_TAB:"jobs",
 SK_NEXT_LANGS:["th","es","id","vi","hi","ta","ja","ko",
                "km","bn","ne","lo","my","it","pt"],
 SpreadsheetApp:{openById:()=>({getSheetByName:()=>jobTab})},
 soulkeyNextSelectedCodes_:()=>["es","id","km","vi","th"],
 soulkeyNextSha_:s=>String(s.length),
 soulkeyNextNow_:()=>"2026-11-20 18:35:00"
};
vm.createContext(jobCtx);
vm.runInContext(next.slice(jobsStart,jobsEnd),jobCtx);
const src=[{task:"P262-L01",segments:[{id:0},{id:1}],source_file_id:"final-id"}];
const rows=[Array(25).fill(""),Array(25).fill("")];
rows.forEach((r,i)=>{r[0]="P262-L01";r[1]=i;});
rows[0][7]="Spanish row 0";
rows[0][8]="Indonesian row 0";
jobCtx.soulkeyNextUpdateJobs_(src,rows);
assert.equal(savedJob[3],2);
assert.equal(savedJob[4],10,"only 2 segments * 5 selected languages");
rows.forEach(r=>[0,1,2,3,8].forEach(k=>r[6+k]="translated"));
jobCtx.soulkeyNextUpdateJobs_(src,rows);
assert.equal(savedJob[3],10);
assert.equal(savedJob[4],10);
assert(savedJob[5].includes("Gemma"),"all 5 selected languages should advance to QA");


const signedRoutes=fs.readFileSync(__dirname+"/Code.gs","utf8");
assert(signedRoutes.includes('nativeSheetsAction==="p262_progress"'));
assert(signedRoutes.includes('nativeSheetsAction==="qa_tick"'));
assert(signedRoutes.includes('results.en={'));
assert(signedRoutes.includes('enCopy.review==="approved_english_final"'));
const completion=fs.readFileSync(__dirname+"/../../scripts/soulkey_p262_complete.py","utf8");
assert(completion.includes('TASKS = ["P262-L01", "P262-L02", "P262-L03", "P262-L04"]'));
assert(completion.includes('native_sheets_action=action'));
assert(completion.includes('native_audio_task=task'));
assert(completion.includes('lane.get("formal_copied")'));
const runner=fs.readFileSync(__dirname+"/../../.github/workflows/soulkey_p262_completion.yml","utf8");
assert(runner.includes('soulkey_p262_complete.py'));
assert(runner.includes("*/30 * * * *"));

console.log("PASS: P262 source isolation, Sheets quota, six-language QA/audio recovery and cron worker");

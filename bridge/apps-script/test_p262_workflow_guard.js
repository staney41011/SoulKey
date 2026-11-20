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
console.log("PASS: P262 cross-course English quarantine, auto-unblock and stale UI response gate");

"use strict";
const assert=require("node:assert/strict"),vm=require("node:vm"),fs=require("node:fs"),path=require("node:path");
const app=fs.readFileSync(path.join(__dirname,"..","app-20260923-48.js"),"utf8");
function between(start,end){
 const a=app.indexOf(start),b=app.indexOf(end,a+start.length);
 if(a<0||b<0)throw Error("Missing function: "+start);
 return app.slice(a,b);
}
const code=between("function syncCompletedFromRemote(task){","function taskProgressHtml(task){")+
  between("function stageState(task,index){","function normalizedLanguagePlan(task){");
const workflow=[
 {key:"zh",label:"中文定稿"},{key:"en-review",label:"英文定稿"},
 {key:"multi",label:"各國語言翻譯"},{key:"tts",label:"各國語言音檔"}
];
const sandbox={workflow,normalizeTask:x=>x,
 remoteStageStatus:(task,key)=>task.remoteStages[key]||null};
vm.runInNewContext(code,sandbox,{timeout:1000});
function lesson(status){
 return {completedStep:2,remoteStages:{
  zh:{status:"done"}, "en-review":{status:"done"},
  multi:{status},tts:null
 }};
}
for(const status of ["queued","running","delayed","error","stale","needs_review"]){
 const t=lesson(status);
 assert.equal(sandbox.nextStageFor(t)?.key,"multi",
  "multi "+status+" must not advance to TTS");
 assert.equal(t.completedStep,1);
 assert.equal(sandbox.stageState(t,2),status==="delayed"?"running":
  status==="needs_review"?"needs-review":status);
 assert.equal(sandbox.stageState(t,3),"locked");
}
const completed=lesson("done");
assert.equal(sandbox.nextStageFor(completed)?.key,"tts");
assert.equal(completed.completedStep,2);
assert.equal(sandbox.stageState(completed,3),"current");
// It must also protect already-advanced local TTS when upstream is rerun.
const erroneous={completedStep:3,remoteStages:{
 zh:{status:"done"},"en-review":{status:"done"},
 multi:{status:"running"},tts:{status:"done"}
}};
assert.equal(sandbox.nextStageFor(erroneous)?.key,"multi");
assert.equal(erroneous.completedStep,1);
assert(app.includes("nextRemote && nextRemote.status===\"running\" ? \"工作執行中\""));
assert(app.includes("remoteStatusText(remote.status)+remoteProgressText(remote)"));
assert(app.includes("previousBtn.disabled=task.completedStep < 0 ||"));
assert(app.includes("The legacy Bridge sets 1% when translation is claimed"));
console.log("PASS: supplemental translation queued/running/delayed blocks TTS even after stale local completion");

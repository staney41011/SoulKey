"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const app=fs.readFileSync(path.join(root,"app-20260923-48.js"),"utf8");
const bridge=fs.readFileSync(path.resolve(root,"../bridge/apps-script/Code.gs"),"utf8");
function method(source,name){
 const at=source.indexOf("function "+name+"(");
 assert(at>=0,name+" missing");
 const next=source.indexOf("\nfunction ",at+8);
 return source.slice(at,next<0?undefined:next);
}
assert.match(method(app,"openEnglishReview"),/requestReviewData\(taskId,"en",0\)/,
 "Must require an authenticated lesson-specific Bridge manuscript before allowing English Final");
assert.doesNotMatch(method(app,"openEnglishReview"),/fetchReviewPayload\(/,
 "Cached GitHub English may not be shown in a different lesson");
assert.ok(app.includes("englishReviewDirtyIds.add(Number(item.id))"));
assert.ok(app.includes("ENGLISH_UNCONFIRMED_BACKUP_PREFIX+selectedTaskId"));
assert.ok(app.includes("const dirty=new Map(currentEnglishReview"));
assert.ok(app.includes("englishDraftSavedSnapshot.confirmed_segment_ids=ids"));
assert.ok(app.includes("showEnglishDraftRecovery(taskId)"));
assert.ok(app.includes("list.innerHTML=currentEnglishReview.map"),
 "Screen must render actual cloud-overlaid edits, not old grouped items");
assert.ok(app.includes("if(!edit||englishReviewDirtyIds.has(id)"),
 "Unsent edits have priority over late cloud results");
assert.ok(app.includes('method:"POST",mode:"cors",credentials:"omit"'),
 "English writes must use CORS and a direct verified acknowledgement");
assert.ok(app.includes('finishEnglishReviewDraftSave(data)'),
 "Cloud ACK must complete the current save");
assert.ok(app.includes('.filter(x=>selected.has(Number(x.id)))'));
assert.ok(app.includes("已載入現有中英稿；Drive 尚未有整堂 JSON"),
 "Missing full JSON is not a reason to hide usable editor");
const context={};
vm.createContext(context);
vm.runInContext(method(app,"englishReviewDisplayChinese"),context);
const zh="因為你不知道。誰會藉著你的善良，走出了絕望。";
assert.equal(context.englishReviewDisplayChinese(zh+zh),zh);
assert.equal(context.englishReviewDisplayChinese(zh+"故事尚未結束"),zh+"故事尚未結束");
assert.ok(bridge.includes("en.review.edits.json"));
// Verified Sheet Final must unlock the multilingual stage, not reopen
// the English editor or require a Google Drive export.
assert.match(method(app,"completeEnglishFinalizeUi"),/openTaskDetail\(taskId\)/);
assert.ok(app.includes("markVerifiedEnglishStage(String(data.task_id),\"sheet\")"),
 "Sheet Final load must refresh the local stage completion");
assert.match(method(app,"syncEnglishFinalizeButton"),/✓ 已定稿・進入下一步/);
const finalTask={id:"P259-L01",completedStep:0,
 remoteStages:{zh:{status:"done"}}};
const stageContext={
 tasks:[finalTask],STORE:{tasks:"test"},save:()=>{},
 renderTasks:()=>{},remoteStageStatus:(task,key)=>task.remoteStages?.[key]
};
vm.createContext(stageContext);
vm.runInContext(method(app,"markVerifiedEnglishStage"),stageContext);
stageContext.markVerifiedEnglishStage("P259-L01","sheet");
assert.equal(finalTask.completedStep,1);
assert.equal(finalTask.remoteStages["en-review"].status,"done");
assert.match(finalTask.remoteStages["en-review"].message,/Drive 待同步/);
console.log("SOULKEY_ENGLISH_DRIVE_AUTHORITY_AND_UNSAVED_EDIT_PROTECTION_OK");

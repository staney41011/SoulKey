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
assert.match(app,/requestReviewData\(taskId,"en",0\);\s*return;/,
 "Must reconcile Drive after cached English manuscript");
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
console.log("SOULKEY_ENGLISH_DRIVE_AUTHORITY_AND_UNSAVED_EDIT_PROTECTION_OK");

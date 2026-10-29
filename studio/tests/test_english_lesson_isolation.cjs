"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const app=fs.readFileSync("studio/app-20260923-48.js","utf8");
const begin=app.indexOf("async function openEnglishReview(taskId){");
const end=app.indexOf("\nfunction mergeEnglishTextParts(",begin);
assert(begin>=0&&end>begin);
const openFn=app.slice(begin,end).trim();
const elements={
 "en-review-share-state":{textContent:""},
 "en-review-task-context":{innerHTML:""},
 "en-review-list":{innerHTML:""},
 "finalize-en":{dataset:{finalized:"0"}}
};
const calls=[];
const context={
 bridgeAuthenticated:true,selectedTaskId:"P259-L03",
 englishDraftSavePendingId:null,
 englishReviewDirtyIds:new Set(),
 englishDraftSaveQueuedIds:new Set(),
 currentEnglishReview:[{id:0,en:"WRONG THIRD LESSON TEXT"}],
 englishCanonicalLoadedTaskId:"P259-L03",
 tasks:[{id:"P259-L03",period:259,lesson:"第3堂",url:"https://youtu.be/third"},
        {id:"P259-L04",period:259,lesson:"第4堂",url:"https://youtu.be/fourth"}],
 document:{getElementById:id=>elements[id]||null},
 setDashboardBridgeState:()=>{throw Error("unexpected auth failure")},
 showView:v=>calls.push(["view",v]),
 showEnglishDraftRecovery:()=>{},
 requestEnglishCloudOverrides:()=>true,
 syncEnglishFinalizeButton:()=>{},
 requestReviewData:(task,kind)=>{calls.push(["review",task,kind]);return true;},
 escapeHtml:String,console,alert:()=>{throw Error("unexpected warning")}
};
vm.createContext(context);
vm.runInContext(openFn,context);
(async()=>{
 await context.openEnglishReview("P259-L04");
 assert.equal(context.selectedTaskId,"P259-L04");
 assert.equal(context.currentEnglishReview.length,0,
  "previous lesson English must be erased before new lesson loads");
 assert.equal(context.englishCanonicalLoadedTaskId,"",
  "unverified new lesson must not be allowed to finalize");
 assert(calls.some(c=>c[0]==="review"&&c[1]==="P259-L04"&&c[2]==="en"));
 assert(!calls.some(c=>c[0]==="review"&&c[1]==="P259-L03"));
 assert.match(elements["en-review-list"].innerHTML,/禁止使用其他堂/);
 assert(!openFn.includes("fetchReviewPayload("),
  "must not use unverified GitHub or browser English previews");
 assert(!openFn.includes("readReviewCache("));
 assert.match(app,/englishCanonicalLoadedTaskId!==task\.id/);
 console.log("PASS: switching to fourth lesson drops third English; authenticated source is mandatory");
})().catch(err=>{console.error(err);process.exitCode=1});

const assert=require("node:assert/strict"),fs=require("fs"),vm=require("vm"),path=require("path");
const app=fs.readFileSync(path.resolve(__dirname,"../app-20260923-48.js"),"utf8");
const start=app.indexOf("async function openEnglishReview(taskId)");
const end=app.indexOf("  const shareState=",start);
const ctx={bridgeAuthenticated:true,englishReviewOwner:"P263-L01",selectedTaskId:"P263-L02",currentEnglishReview:[{en:"old lesson"}],englishReviewDirtyIds:new Set(),englishDraftSavePendingId:null,tasks:[],alert(){},setDashboardBridgeState(){},showView(){}};
vm.createContext(ctx);vm.runInContext(app.slice(start,end)+"}",ctx);
(async()=>{
await ctx.openEnglishReview("P263-L02");
assert.equal(ctx.currentEnglishReview.length,0);
assert.equal(ctx.englishReviewOwner,"P263-L02");
assert.ok(app.includes('englishReviewOwner===String(data.task_id||"")'));
assert.ok(app.includes('englishReviewOwner===taskId'));
assert.ok(app.includes('String(pendingDriveAck.task_id||"")===String(taskId)'));
console.log("ENGLISH_LESSON_ISOLATION_OK");
})().catch(e=>{console.error(e);process.exitCode=1;});

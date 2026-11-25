const fs=require("fs"),assert=require("node:assert/strict"),vm=require("vm"),path=require("path");
const s=fs.readFileSync(path.resolve(__dirname,"../app-20260923-48.js"),"utf8");
const a=s.indexOf("const englishTranslationWatchers=new Map()");
const b=s.indexOf("function dispatchAiEnglishTranslation",a);
let remote={status:"queued",progress:"0"}, polls=0;
const button={isConnected:true,disabled:false}, status={isConnected:true};
const ctx={Map,bridgeAuthenticated:true,tasks:[{id:"P263-L02"}],remoteStageStatus:()=>remote,requestTaskStatuses:()=>polls++,requestReviewData:()=>true,remoteStatusText:x=>x,setTimeout:(fn)=>{button.isConnected=false;fn();}};
vm.createContext(ctx); vm.runInContext(s.slice(a,b),ctx);
(async()=>{
await ctx.waitForAiEnglishTranslation("P263-L02",button,status);
assert.equal(button.disabled,true);
assert.equal(polls,1);
assert.ok(!status.textContent.includes("/72"));
assert.equal(ctx.englishTranslationActive({status:"queued"}),true);
assert.equal(ctx.englishTranslationActive({status:"error"}),false);
assert.ok(s.includes("if(englishTranslationActive(remoteStageStatus(current"));
console.log("ENGLISH_QUEUE_STATUS_OK");
})().catch(e=>{console.error(e);process.exitCode=1;});

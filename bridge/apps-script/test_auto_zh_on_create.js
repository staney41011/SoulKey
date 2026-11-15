"use strict";
const fs=require("node:fs");
const vm=require("node:vm");
const assert=require("node:assert/strict");
const source=fs.readFileSync(__dirname+"/Code.gs","utf8");
const begin=source.indexOf("function soulkeyAutoStartChineseReconcile_(");
const end=source.indexOf("\nfunction upsertTasks_(",begin);
assert(begin>=0 && end>begin);
const section=source.slice(begin,end);
const markers=new Map();
const prefix="SOULKEY_AUTO_ZH_PENDING_V1_";
const jobs=[];
const statuses=[];
let fail=false;
const repoTasks=[
  {id:"P263-L01",url:"https://youtu.be/new-lesson"},
  {id:"P263-L02",url:"https://youtu.be/retry-lesson"},
  {id:"P262-L04",url:"https://youtu.be/old-lesson"},
  {id:"P263-L03",url:"https://youtu.be/other"},
];
const ctx={
  PropertiesService:{getScriptProperties:()=>({
    getProperty:key=>key==="GITHUB_TOKEN"?"test-token":(markers.get(key)||""),
    getProperties:()=>Object.fromEntries(markers),
    setProperty:(key,value)=>{markers.set(key,value);return null;},
    deleteProperty:key=>markers.delete(key)
  })},
  readTasks_:()=>repoTasks,
  readLatestStatuses_:()=>({}),
  Logger:{log:()=>{}},
  dispatchWorkflowIdempotently_:(token,task,stage,lang,langs,url)=>{
    assert.equal(token,"test-token");
    assert.equal(stage,"zh");
    assert.equal(lang,"");
    assert.equal(langs,"");
    assert.ok(url.endsWith("/exec"));
    jobs.push({task,stage});
    return fail?{ok:false,error:"rate_limited"}:
      {ok:true,duplicate:false,nonce:"new-zh-nonce"};
  },
  appendExecutionStatus_:(...args)=>statuses.push(args),
};
vm.createContext(ctx);
vm.runInContext(section,ctx);
const save=(id,url)=>markers.set(prefix+id,JSON.stringify({url}));
save("P263-L01","https://youtu.be/new-lesson");
let response=ctx.soulkeyAutoStartChineseReconcile_(["P263-L01"]);
assert.equal(response.ok,true);
assert.equal(response.started,1);
assert.equal(response.pending,0);
assert.deepEqual(jobs.map(x=>x.task),["P263-L01"]);
assert.equal(statuses[0][0],"P263-L01");
assert.equal(statuses[0][1],"zh");
assert.equal(statuses[0][2],"queued");
assert.ok(!markers.has(prefix+"P263-L01"));
// Re-saving an existing task does not start anything.
response=ctx.soulkeyAutoStartChineseReconcile_(["P262-L04"]);
assert.equal(response.started,0);
assert.equal(jobs.length,1);
// Failure must leave retry marker; existing authenticated cron can retry.
save("P263-L02","https://youtu.be/retry-lesson");
fail=true;
response=ctx.soulkeyAutoStartChineseReconcile_(["P263-L02"]);
assert.equal(response.ok,false);
assert.equal(response.pending,1);
assert.ok(markers.has(prefix+"P263-L02"));
fail=false;
response=ctx.soulkeyAutoStartChineseReconcile_();
assert.equal(response.started,1);
assert.ok(!markers.has(prefix+"P263-L02"));
// Never dispatch a changed source that no longer matches creation time.
save("P263-L03","https://youtu.be/different-video");
response=ctx.soulkeyAutoStartChineseReconcile_();
assert.equal(response.started,0);
assert.equal(response.pending,0);
assert.ok(!markers.has(prefix+"P263-L03"));
// Existing queued/running tasks may not be started again.
save("P263-L01","https://youtu.be/new-lesson");
ctx.readLatestStatuses_=()=>({"P263-L01":{stages:{zh:{status:"running"}}}});
response=ctx.soulkeyAutoStartChineseReconcile_();
assert.equal(response.started,0);
assert.equal(response.duplicate,1);
assert.ok(!markers.has(prefix+"P263-L01"));
assert.equal(jobs.length,3);
// Integration contract: only newly created lessons dispatch; retry via existing webhook.
assert(source.includes("saved.filter(function(x){return x.created;})"));
assert(source.includes("autoZh=soulkeyAutoStartChineseReconcile_("));
assert(source.includes("try{autoZh=soulkeyAutoStartChineseReconcile_();}"));
assert(source.includes("SOULKEY_AUTO_ZH_PENDING_V1_"));
assert(source.includes('dispatchWorkflowIdempotently_(\n        token,id,"zh"'));
console.log("PASS: registration auto-start, no duplicate, failure retry, source guard");

"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../../studio/app-20260923-48.js"),"utf8");
const start=source.indexOf("function bridgeSyncRequestFailed(");
const end=source.indexOf("\nfunction completeEnglishFinalizeUi(",start);
assert(start>=0&&end>start,"Bridge JSONP handlers not found");
const elements={
 "dashboard-bridge-state":{className:"badge",textContent:"同步中",
   classList:{add(){}}},
 "dashboard-bridge-message":{textContent:"正在同步"},
 "status-sync-state":{textContent:""},
 "status-sync-text":{textContent:""},
 "api-state":{textContent:""},
};
const scripts=[];
let timeoutCallback=null;
const events=[];
const document={
 getElementById:id=>elements[id]||null,
 createElement:tag=>{const x={tag,remove(){x.removed=true;},onerror:null};scripts.push(x);return x;},
 head:{appendChild(x){x.appended=true;}}
};
const window={
 setTimeout:(callback,delay)=>{timeoutCallback=callback;return 1;},
 clearTimeout:()=>{timeoutCallback=null;},
 dispatchEvent:ev=>events.push(ev)
};
const ctx={
 window,document,URLSearchParams,Math,Date,
 MessageEvent:class{constructor(type,{data}){this.type=type;this.data=data;}},
 bridgeEndpointValue:()=> "https://script.google.com/macros/s/EXAMPLE/exec",
 bridgeKeyValue:()=> "LOCAL_TEST_ONLY",
 setDashboardBridgeState:(message,state)=>{
   elements["dashboard-bridge-state"].textContent=state==="error"?"連線失敗":message;
   elements["dashboard-bridge-message"].textContent=message;
 },
 bridgeAuthenticated:true
};
vm.createContext(ctx);
vm.runInContext(source.slice(start,end),ctx);
assert.equal(ctx.jsonpBridgeRequest({action:"status_health"}),true);
assert.equal(scripts.length,1);
assert.equal(typeof scripts[0].onerror,"function");
scripts[0].onerror();
assert.equal(elements["dashboard-bridge-state"].textContent,"連線失敗");
assert.match(elements["dashboard-bridge-message"].textContent,/拒絕存取/);
assert.equal(ctx.bridgeAuthenticated,false);
assert.equal(timeoutCallback,null);
assert.equal(scripts[0].removed,true);
assert.equal(events.length,0);
elements["dashboard-bridge-state"].textContent="同步中";
ctx.bridgeAuthenticated=true;
ctx.jsonpBridgeRequest({action:"tasks_get"});
assert.equal(typeof timeoutCallback,"function");
timeoutCallback();
assert.equal(elements["dashboard-bridge-state"].textContent,"連線失敗");
assert.match(elements["dashboard-bridge-message"].textContent,/逾時 45 秒/);
assert.equal(ctx.bridgeAuthenticated,false);
console.log("PASS: HTTP 403 script load error immediately stops sync spinner");
console.log("PASS: tasks_get timeout stops sync spinner and reports retry advice");
console.log("PASS: request handlers and timers are cleaned up");

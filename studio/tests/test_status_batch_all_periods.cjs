"use strict";

const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");

// Run the actual production function in a minimal environment, not a copy.
const source=fs.readFileSync(path.join(__dirname,"..","app-20260923-48.js"),"utf8");
const begin=source.indexOf("function requestTaskStatuses(){");
const end=source.indexOf("\nfunction requestStatusHealth()",begin);
assert(begin>=0 && end>begin,"requestTaskStatuses function must be present");
const fnSource=source.slice(begin,end);
const build=(count,period=258)=>{
  const calls=[];
  const tasks=Array.from({length:count},(_,i)=>({
    id:"P"+String(253+Math.floor(i/4))+"-L"+String(i%4+1).padStart(2,"0"),
    period:253+Math.floor(i/4)
  }));
  // Update final four rows to the selected period for realistic 24-task tests.
  if(count===24)tasks.slice(20).forEach((t,j)=>{t.period=period;t.id="P258-L0"+(j+1)});
  const context={
    tasks,
    bridgeAuthenticated:true,
    bridgeKeyValue:()=>"test-key",
    bridgeEndpointValue:()=>"https://example.invalid/bridge",
    tasksForSelectedPeriod:()=>tasks.filter(t=>t.period===period),
    jsonpBridgeRequest:call=>{calls.push(call);return true}
  };
  const request=vm.runInNewContext("("+fnSource+")",context);
  return {request,calls,context,tasks};
};
const test24=build(24);
assert.equal(test24.request(),true);
assert.equal(test24.calls.length,2,"24 tasks must use two batches");
const sent24=test24.calls.flatMap(c=>c.task_ids.split(","));
assert.equal(sent24.length,24);
assert.equal(new Set(sent24).size,24);
assert.deepEqual(sent24.slice(0,4),["P258-L01","P258-L02","P258-L03","P258-L04"],
                 "visible period should be prioritized");
assert.deepEqual(new Set(sent24),new Set(test24.tasks.map(t=>t.id)));
assert(test24.calls.every(c=>c.action==="status_batch" && c.task_ids.split(",").length<=20));
const test61=build(61,267);
assert.equal(test61.request(),true);
assert.equal(test61.calls.length,4);
const sent61=test61.calls.flatMap(c=>c.task_ids.split(","));
assert.equal(sent61.length,61);
assert.deepEqual(new Set(sent61),new Set(test61.tasks.map(t=>t.id)));
assert(test61.calls.every(c=>c.task_ids.split(",").length<=20));
const blocked=build(24);
blocked.context.bridgeAuthenticated=false;
assert.equal(blocked.request(),false);
assert.equal(blocked.calls.length,0);
console.log("STUDIO_STATUS_BATCH_ALL_PERIODS_OK",JSON.stringify({
  tasks24:sent24.length,batches24:test24.calls.length,
  tasks61:sent61.length,batches61:test61.calls.length,
  visibleFirst:sent24.slice(0,4)
}));

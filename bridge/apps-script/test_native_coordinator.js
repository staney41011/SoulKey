const fs=require("fs"),vm=require("vm"),assert=require("node:assert/strict"),path=require("path");
const s=fs.readFileSync(path.join(__dirname,"NativeNext.gs"),"utf8");
const props=new Map([["SOULKEY_NEXT_ENABLED","yes"]]);
const calls=[];
const heartbeats=[];
let busy=false;
const ctx=vm.createContext({Date,Number,String,JSON,
  PropertiesService:{getScriptProperties:()=>({getProperty:k=>props.get(k),setProperty:(k,v)=>props.set(k,v),deleteProperty:k=>props.delete(k)})},
  LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock(){}})},
  soulkeyNextNow_:()=>new Date().toISOString(),
  soulkeyNextHeartbeat_:(...args)=>heartbeats.push(args),
  soulkeyNextTick:()=>{assert.equal(props.get("SOULKEY_NEXT_COORDINATOR_PHASE"),"qa");calls.push("translation");return busy?{ok:false,reason:"busy"}:{ok:true};},
  soulkeyNextQATick:()=>{calls.push("qa");return {ok:true};},
  soulkeyNextAudioTick:()=>{calls.push("audio");return {ok:true};},
});
vm.runInContext(s.slice(s.indexOf("function soulkeyNextCoordinator(){"),s.indexOf("function soulkeyNextInstall(){")),ctx);
busy=true;ctx.soulkeyNextCoordinator();busy=false;
ctx.soulkeyNextCoordinator();ctx.soulkeyNextCoordinator();ctx.soulkeyNextCoordinator();
assert.deepEqual(calls,["translation","qa","audio","translation"]);
props.set("SOULKEY_NEXT_COORDINATOR_LEASE",String(Date.now()+60000));
assert.equal(ctx.soulkeyNextCoordinator().reason,"coordinator_busy");
assert.equal(calls.length,4);
// Simulate forced termination during QA: expired lease with phase precommitted.
props.set("SOULKEY_NEXT_COORDINATOR_LEASE",String(Date.now()-1000));
props.set("SOULKEY_NEXT_COORDINATOR_PHASE","audio");
props.set("SOULKEY_NEXT_COORDINATOR_CHECKPOINT",JSON.stringify({phase:"qa",state:"running",day:new Date().toISOString().slice(0,10)}));
ctx.soulkeyNextCoordinator();
assert.equal(calls[4],"audio");
assert.equal(props.get("SOULKEY_NEXT_COORDINATOR_PHASE"),"translation");
assert.equal(heartbeats[0][0],"qa");
assert.equal(heartbeats[0][1],"interrupted");
assert.equal(JSON.parse(props.get("SOULKEY_NEXT_COORDINATOR_RUNTIME")).estimated_timeout_ms,360000);
console.log("COORDINATOR_SERIAL_PHASES_AND_TIMEOUT_RECOVERY_OK");

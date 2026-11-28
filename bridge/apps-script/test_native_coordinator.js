const fs=require("fs"),vm=require("vm"),assert=require("node:assert/strict"),path=require("path");
const s=fs.readFileSync(path.join(__dirname,"NativeNext.gs"),"utf8");
const props=new Map([["SOULKEY_NEXT_ENABLED","yes"]]);
const calls=[];
let busy=false;
const ctx=vm.createContext({Date,Number,String,JSON,
  PropertiesService:{getScriptProperties:()=>({getProperty:k=>props.get(k),setProperty:(k,v)=>props.set(k,v),deleteProperty:k=>props.delete(k)})},
  LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock(){}})},
  soulkeyNextTick:()=>{calls.push("translation");return busy?{ok:false,reason:"busy"}:{ok:true};},
  soulkeyNextQATick:()=>{calls.push("qa");return {ok:true};},
  soulkeyNextAudioTick:()=>{calls.push("audio");return {ok:true};},
});
vm.runInContext(s.slice(s.indexOf("function soulkeyNextCoordinator(){"),s.indexOf("function soulkeyNextInstall(){")),ctx);
busy=true;ctx.soulkeyNextCoordinator();busy=false;
ctx.soulkeyNextCoordinator();ctx.soulkeyNextCoordinator();ctx.soulkeyNextCoordinator();
assert.deepEqual(calls,["translation","translation","qa","audio"]);
props.set("SOULKEY_NEXT_COORDINATOR_LEASE",String(Date.now()+60000));
assert.equal(ctx.soulkeyNextCoordinator().reason,"coordinator_busy");
assert.equal(calls.length,4);
console.log("COORDINATOR_SERIAL_PHASES_OK");

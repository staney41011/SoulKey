"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const file=path.join(__dirname,"..","Code.gs");
const s=fs.readFileSync(file,"utf8");
const a=s.indexOf("function firebaseStatusMirror_("),b=s.indexOf("\nfunction nowText_()",a);
assert(a>=0&&b>a,"Firebase mirror must be present in original Apps Script");
const src=s.slice(a,b);
function ctx(props={},reply=200){
  const requests=[];
  const globals={
    PropertiesService:{getScriptProperties:()=>({getProperty:name=>props[name]||""})},
    ScriptApp:{getOAuthToken:()=>"fake-short-lived-token"},
    UrlFetchApp:{fetch:(url,opts)=>{
      requests.push({url,opts});
      if(reply==="error")throw Error("Firebase unavailable");
      return {getResponseCode:()=>reply};
    }},
    console:{warn:()=>{}},Date,Number,String,JSON,encodeURIComponent
  };
  vm.createContext(globals);vm.runInContext(src,globals);
  return {run:globals.firebaseStatusMirror_,requests};
}
const off=ctx();
assert.equal(off.run("P259-L01","multi","done",100,"run","source","output"),false);
assert.equal(off.requests.length,0,"Default off must not call Firebase");
const invalid=ctx({FIREBASE_STATUS_MIRROR_ENABLED:"true",FIREBASE_DATABASE_URL:"http://unsafe.test"});
assert.equal(invalid.run("P259-L01","tts","running",22,"x","",""),false);
assert.equal(invalid.requests.length,0);
const good=ctx({FIREBASE_STATUS_MIRROR_ENABLED:"true",FIREBASE_DATABASE_URL:"https://soulkey-control-2026-default-rtdb.asia-southeast1.firebasedatabase.app/"});
assert.equal(good.run("P259-L01","tts","running",58,"job-1","sha-1","sha-2"),true);
assert.equal(good.requests.length,1);
assert.match(good.requests[0].url,/\/soulkey\/status_v1\/P259-L01\/tts\.json$/);
assert.equal(good.requests[0].opts.headers.Authorization,"Bearer fake-short-lived-token");
const posted=JSON.parse(good.requests[0].opts.payload);
assert.equal(posted.task_id,"P259-L01");assert.equal(posted.status,"running");
assert.equal(posted.progress,58);
assert(!JSON.stringify(posted).includes("manuscript"),"Never mirror lesson text");
const fail=ctx({FIREBASE_STATUS_MIRROR_ENABLED:"true",FIREBASE_DATABASE_URL:"https://soulkey-control-2026-default-rtdb.firebaseio.com"},"error");
assert.equal(fail.run("P259-L01","tts","error",0,"","",""),false,"RTDB failure must never block the original Sheets workflow");
assert.equal(fail.requests.length,1);
console.log("PASS: optional RTDB status mirror is default-off, private, scoped and fail-open for Sheets");

"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,"../..");
const gs=fs.readFileSync(path.join(root,"bridge/apps-script/Code.gs"),"utf8");
const start=gs.indexOf("function bridgeClientHtml_()"),section=gs.slice(start,gs.indexOf("function responseForAction_",start));
const script=section.match(/<script>([\s\S]*?)<\/script>/)[1];
const sent=[];let listener,success,received;
const context={window:{parent:{postMessage:(data,origin)=>sent.push({target:"parent",data,origin})},
  top:{postMessage:(data,origin)=>sent.push({target:"studio",data,origin})},
  addEventListener:(_name,fn)=>{listener=fn;}},google:{script:{run:{
    withSuccessHandler(fn){success=fn;return this;},withFailureHandler(){return this;},
    bridgeRequest(request){received=request;success({source:"soulkey-bridge",type:"status_health",ok:true});}
  }}}};
vm.runInNewContext(script,context);
assert(sent.some(x=>x.target==="studio"&&x.data.type==="ready"));
listener({data:{source:"soulkey-studio",type:"bridge_request",request:{action:"status_health"}}});
assert.equal(received.action,"status_health");
const response=sent.find(x=>x.target==="studio"&&x.data.type==="status_health");
assert(response?.data.ok);assert.equal(response.origin,"https://staney41011.github.io");
const app=fs.readFileSync(path.join(root,"studio/app-20260923-48.js"),"utf8");
const a=app.indexOf("function legacyBridgeRead("),b=app.indexOf("function jsonpBridgeRequest(",a);
let failure,timeout;
const ctx={firebaseSnapshotReadOnly:false,cfg:{},bridgeKeyValue:()=>"test-only-key",
  bridgeSyncRequestFailed:(action,message)=>{failure={action,message};},window:{SoulKeyBridgeRoutes:{
    readLegacy(_cfg,_key,_fields,options){timeout=options.timeoutMs;options.onError(new Error("read timeout"));return true;}}}};
vm.runInNewContext(app.slice(a,b),ctx);ctx.legacyBridgeRead({action:"status_health"});
assert.equal(timeout,30000);assert.equal(failure.action,"status_health");assert.equal(failure.message,"read timeout");
console.log("PASS: nested HtmlService sends ready/results to Studio; failed login reads report a bounded error");

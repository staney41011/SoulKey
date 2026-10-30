"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,"../.."),read=p=>fs.readFileSync(path.join(root,p),"utf8");
const context={window:{}};vm.runInNewContext(read("studio/config.js"),context);
const cfg=context.window.SOULKEY_CONFIG;
assert.equal(cfg.mode,"legacy-kaggle");
assert.match(cfg.bridgeEndpoint,/^https:\/\/script\.google\.com\/macros\/s\/[^/]+\/exec$/);
assert.equal(cfg.legacyKaggleBridgeEndpoint,cfg.bridgeEndpoint);
assert.equal(cfg.firebaseHostingUrl,"");
const routes=require("../bridge-routing.js");
assert.equal(routes.endpoint({...cfg,bridgeEndpoint:"https://retired.run.app"},{action:"review_save"}),"");
assert.equal(routes.endpoint(cfg,{action:"review_save"}),cfg.bridgeEndpoint);
for(const name of ["soulkey_translation_queue","soulkey_cc_queue","p259_translation_kickstart","soulkey_bridge_translation_capabilities_probe"]){
  const text=read(".github/workflows/"+name+".yml");
  assert(!text.includes("schedule:"),name+" must not schedule GCP calls");
  assert(!text.includes("run.app"),name+" must not contact Cloud Run");
  assert(!/id-token:\s*write/.test(text));
  assert(text.includes("GCP worker retired"));
}
const code=read("bridge/apps-script/Code.gs"),manifest=JSON.parse(read("bridge/apps-script/appsscript.json"));
assert(!code.includes("firebaseStatusMirror_("),"No active RTDB status hook");
assert(!manifest.oauthScopes.some(x=>/firebase\.database|userinfo\.email/.test(x)));
assert(!read("studio/index.html").includes("soulkey-control-2026.web.app"));
const app=read("studio/app-20260923-48.js");
const a=app.indexOf("function runYoutubeAudioGrab(){"),b=app.indexOf("function stageState(",a);
for(const mode of ["cc","audio"]){
  const sent=[],state={textContent:""};
  const ctx={youtubeCCQueueEnabled:true,youtubeAudioSelectedTask:()=>({id:"P259-L03",url:"https://youtu.be/source"}),
    youtubeCaptureMode:()=>mode,youtubeAudioRequestedLangs:()=>"ja",document:{getElementById:()=>state},
    bridgeKeyValue:()=>"test-key",bridgeEndpointValue:()=>cfg.bridgeEndpoint,
    bridgeProtocolVersion:9,REQUIRED_BRIDGE_PROTOCOL:9,pendingYoutubeCapture:null,
    submitBridgePost:fields=>{sent.push(fields);return true;},window:{setTimeout(){}}};
  vm.runInNewContext(app.slice(a,b),ctx);ctx.runYoutubeAudioGrab();
  assert.equal(sent.length,1,"Original Bridge must dispatch "+mode+" without a Cloud Run capability flag");
  assert.equal(sent[0].stage,"cc");
  if(mode==="audio"){assert.equal(sent[0].lang,"multi-audio");assert.equal(sent[0].langs,"ja");}
}
console.log("PASS: production stays on original Apps Script/Kaggle; GCP schedulers, fallback and OAuth scopes are retired");

"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const script=fs.readFileSync(path.join(root,"app-20260923-48.js"),"utf8");
const config=fs.readFileSync(path.join(root,"config.js"),"utf8");
const sections=[
  script.split("function startP259RescueAudio(){",2)[1]?.split('document.getElementById("p259-rescue-start")?.addEventListener',1)[0],
  script.split("function startP259RescueTranslation(){",2)[1]?.split('document.getElementById("p259-translation-start")?.addEventListener',1)[0]
];
assert.equal(sections.length,2);
for(const section of sections){
  assert(section,"Missing P259 rescue function");
  assert(section.includes("!bridgeAuthenticated"),"Must require verified central login");
  assert(section.includes("!LEGACY_KAGGLE_ENDPOINT"),"Must require configured Kaggle route");
  assert(section.includes("firebaseSnapshotReadOnly"),"Must block backup-only mode");
  assert(section.includes("confirmedRemoteTaskIds.has(id)"),"Must verify all four registered lessons");
  assert(!section.includes("!isAppsScriptBridge()"),"Cloud Run login must not block Kaggle launch");
  assert(section.includes('task_id:"P259-L01"'),"Requires single four-lesson dispatch anchor");
  assert(section.includes('lang:"central4"'),"Requires four-lesson worker");
}
assert(config.includes("legacyKaggleBridgeEndpoint:"));
assert(config.includes('bridgeEndpoint: "https://soulkey-bridge-'));
assert(script.includes('const endpoint=legacyMachineJob ? LEGACY_KAGGLE_ENDPOINT : bridgeEndpointValue()'));
console.log("PASS: verified Cloud Run login can dispatch four-lesson jobs to original Kaggle Apps Script");

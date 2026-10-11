"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const root=path.join(__dirname,"../..");
const read=(name)=>fs.readFileSync(path.join(root,name),"utf8");
const app=read("studio/app-20260923-48.js");
const quick=read("studio/review-editor.js");
const index=read("studio/index.html");
const html=read("studio/review.html");
const style=read("studio/styles.css");
const reviewStyle=read("studio/review-editor.css");

const codes=["en","th","es","id","vi","hi","ta","ja","ko","km"];
for (const [name,source] of [["Studio",app],["Quick Review",quick]]){
  for (const zh of ["英文","泰文","西班牙文","印尼文","越南文",
      "印地語","泰米爾文","日文","韓文","高棉文"]){
    assert.ok(source.includes(zh),name+" missing "+zh);
  }
}
assert.equal((html.match(/data-output-lang="/g)||[]).length,10);
assert.equal((html.match(/data-output-enabled/g)||[]).length,10);
assert.equal((html.match(/data-output-transcript/g)||[]).length,0);
assert.equal((html.match(/data-output-audio/g)||[]).length,0);
assert.ok(index.includes("各國語言輸出設定"));
assert.ok(index.includes("只要勾選需要的語言"));
assert.ok(!index.includes("<span>翻譯文稿</span><span>音檔</span>"));
assert.ok(style.includes(".language-plan-row:has([data-plan-enabled]:checked)"));
assert.ok(reviewStyle.includes(".output-row:has([data-output-enabled]:checked)"));
console.log("PASS: Both UIs have one checkbox per language and Chinese labels");

function extractFunction(src,name,next){
 const start=src.indexOf("function "+name+"(){");
 assert.ok(start>=0,"Missing "+name);
 const end=src.indexOf(next,start);
 assert.ok(end>start,"Missing terminator for "+name);
 return src.slice(start,end);
}
const studioCollector=extractFunction(app,"collectLanguagePlan","\nfunction saveLanguagePlanForSelectedTask");
const quickCollector=extractFunction(quick,"collectOutputPlan","\nfunction updateOutputSummary");
const languages=codes.map(code=>({code,name:code+"_local"}));
const selections=new Set(["ko","km","en"]);
const mockRows=attr=>codes.map(code=>({
 dataset:attr==="data-lang-plan"?{langPlan:code}:{outputLang:code},
 querySelector:(selector)=>selector==="[data-plan-enabled]"||selector==="[data-output-enabled]"
    ? {checked:selections.has(code)}:null
}));
const studioCtx={
 languageSettings:languages,
 document:{querySelectorAll:selector=>{
  assert.equal(selector,".language-plan-row");
  return mockRows("data-lang-plan");
 }}
};
vm.createContext(studioCtx);
vm.runInContext(studioCollector,studioCtx);
const studioPlan=studioCtx.collectLanguagePlan();
assert.equal(studioPlan.length,10);
for(const x of studioPlan){
 const chosen=selections.has(x.language_code);
 assert.equal(x.audio_enabled,chosen);
 assert.equal(x.transcript_enabled,x.language_code==="en"||chosen);
 assert.equal(x.audio_source,"tts");
 assert.equal(x.transcript_source,x.language_code==="en"?"human":"ai");
}
assert.equal(studioPlan.find(x=>x.language_code==="km").language_name,"km_local");
console.log("PASS: Studio serializes checked languages into BOTH outputs");

const quickCtx={
 LANG_NAMES:Object.fromEntries(codes.map(code=>[code,code+"_local"])),
 document:{querySelectorAll:selector=>{
  assert.equal(selector,".output-row");
  return mockRows("data-output-lang");
 }}
};
vm.createContext(quickCtx);
vm.runInContext(quickCollector,quickCtx);
const quickPlan=quickCtx.collectOutputPlan();
assert.equal(quickPlan.length,10);
assert.equal(JSON.stringify(quickPlan),JSON.stringify(studioPlan));
console.log("PASS: Quick Review sends exactly the same unified payload");

selections.clear();
assert.ok(studioCtx.collectLanguagePlan().every(
  x=>!x.audio_enabled && x.transcript_enabled===(x.language_code==="en")));
assert.ok(quickCtx.collectOutputPlan().every(
  x=>!x.audio_enabled && x.transcript_enabled===(x.language_code==="en")));
console.log("PASS: deselection suppresses new outputs but retains English Final");

const studioSection=app.slice(app.indexOf("function renderLanguagePlan("),
                             app.indexOf("function saveLanguagePlanForSelectedTask"));
assert.equal((studioSection.match(/data-plan-enabled/g)||[]).length,4);
assert.ok(!studioSection.includes("data-plan-audio"));
assert.ok(!studioSection.includes("data-plan-transcript"));
assert.ok(!quick.includes('const transcript=row.querySelector("[data-output-transcript]")'));
console.log("PASS: removed obsolete independent output controls and listeners");

const fs=require("fs"),vm=require("vm"),assert=require("assert"),path=require("path");
const root=path.join(__dirname,"../..");
const bridge=fs.readFileSync(path.join(root,"bridge/apps-script/Code.gs"),"utf8");
const frontend=fs.readFileSync(path.join(root,"studio/app-20260923-48.js"),"utf8");
const html=fs.readFileSync(path.join(root,"studio/index.html"),"utf8");
const start=bridge.indexOf("function loadReview_(taskId, kind, chunkIndex) {");
const end=bridge.indexOf("function saveReview_(taskId, kind, segments, learnedTerms) {",start);
assert(start>=0&&end>start);
const src=bridge.slice(start,end);
let english=null,chinese={
  language:"Traditional Chinese Final",
  segments:[{id:0,start:0,end:20,text:"修道要從心開始。"}]
};
const ctx=vm.createContext({
  Date,Math,Number,String,Array,JSON,
  lessonFolders_:()=>({transcript:"zh",translation:"tr",source:"src"}),
  readJsonFile_:(folder,name)=>{
    if(folder==="zh"&&name==="zh-TW.final.json")return chinese;
    if(folder==="tr"&&name==="en.final.json")return english;
    return null;
  },
  getSheetByName_:()=>({getDataRange:()=>({getDisplayValues:()=>[
    ["中文","分類","說明","English"],["修道","","","spiritual cultivation"]]})}),
  chineseFinalForEnglishTimeRange_:()=>chinese.segments[0].text,
  formatPlainTime_:()=> "00:00:00",
  alignEnglishCcToReviewItems_:()=>[]
});
new vm.Script(src).runInContext(ctx);
let result=ctx.loadReview_("P261-L01","en",0);
assert.equal(result.ok,false);
assert.equal(result.kind,"en");
assert.equal(result.task_id,"P261-L01");
assert.equal(result.error,"english_source_not_generated");
assert.equal(result.chinese_final_ready,true);
assert.equal(result.can_generate_english,true);
assert.equal(chinese.segments[0].text,"修道要從心開始。");
english={segments:[{id:0,start:0,end:20,text:"Spiritual cultivation begins in the heart."}]};
result=ctx.loadReview_("P261-L01","en",0);
assert.equal(result.ok,true);
assert.equal(result.kind,"en");
assert.equal(result.segments.length,1);
chinese=null;english=null;
result=ctx.loadReview_("P261-L01","en",0);
assert.equal(result.ok,false);
assert.equal(result.kind,"en");
assert.equal(result.error,"chinese_final_missing");
assert(frontend.includes('String(data.error||"")==="english_source_not_generated"'));
assert(frontend.includes('showNoEnglishCcFallback(data.task_id || selectedTaskId)'));
assert(frontend.includes('action:"run_stage",') && frontend.includes('stage:"en",'));
assert(html.includes("20261110-p261-english-source-fallback"));
console.log("PASS P261 English missing-source route, automatic source detection, one-click AI fallback and Chinese Final preservation");

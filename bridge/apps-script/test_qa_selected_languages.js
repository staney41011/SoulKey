"use strict";
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const code=fs.readFileSync(__dirname+"/Code.gs","utf8");
const begin=code.indexOf("function soulkeyAutoSheetQualityReconcile_(languages) {");
const end=code.indexOf("\nfunction soulkeyAutoSheetAudioRefresh_()",begin);
assert(begin>0 && end>begin);
const statuses=[],dispatches=[],cache=new Map();
const drafts=new Set(["es","km"]);
const ctx={
  PropertiesService:{getScriptProperties:()=>({
    getProperty:key=>key==="GITHUB_TOKEN"?"token":(cache.get(key)||""),
    setProperty:(key,value)=>cache.set(key,value),
  })},
  readTasks_:()=>[{id:"P262-L01",period:262,en:"完成"}],
  lessonFolders_:()=>({translation:{type:"translation"}}),
  cachedFileId_:(folder,name)=>{
    if(name==="en.final.json")return "english-file";
    const m=name.match(/P262-L01-([a-z]+)-google-translate-DRAFT\.json$/);
    return m&&drafts.has(m[1])?"draft-"+m[1]:null;
  },
  cachedChildFolder_:()=>({type:"draft"}),
  soulkeyNextSelectedCodes_:()=>["es","id","km","vi","th"],
  readJsonFile_:()=>null,
  dispatchWorkflowIdempotently_:(token,task,stage,lang,langs)=>{
    dispatches.push({task,stage,lang,langs});
    return {ok:true,duplicate:false,nonce:"signed"};
  },
  appendExecutionStatus_:(...args)=>statuses.push(args),
  Logger:{log:()=>{}}
};
vm.createContext(ctx);
vm.runInContext(code.slice(begin,end),ctx);
const all=["th","es","id","vi","hi","ta","ja","ko","km","bn","ne","lo","my","it","pt"];
let answer=ctx.soulkeyAutoSheetQualityReconcile_(all);
assert.equal(answer.ok,true);
assert.equal(answer.langs,"es,km");
assert.equal(dispatches.length,1);
assert.equal(dispatches[0].stage,"sheet_qa");
assert.equal(dispatches[0].langs,"es,km");
answer=ctx.soulkeyAutoSheetQualityReconcile_(all);
assert.equal(answer.queued,false,"no duplicate same-language hourly QA during cooldown");
assert.equal(dispatches.length,1);
drafts.add("vi");
answer=ctx.soulkeyAutoSheetQualityReconcile_(all);
assert.equal(answer.langs,"es,km,vi");
assert.equal(dispatches.length,2,"newly ready language should not wait for previous language cooldown");
assert.ok(!dispatches.some(x=>x.langs.includes("hi")||x.langs.includes("ja")));
console.log("PASS: hourly Gemma fallback only includes selected complete languages and independent cooldowns");

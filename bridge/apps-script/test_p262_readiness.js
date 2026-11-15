const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

function section(file, start, next) {
  const text = fs.readFileSync(__dirname + "/" + file, "utf8");
  const from = text.indexOf("function " + start + "(");
  assert(from >= 0, "missing production function " + start);
  const to = text.indexOf("\nfunction " + next + "(", from);
  assert(to > from, "missing next production function " + next);
  return text.slice(from, to);
}

const nextSrc = fs.readFileSync(__dirname + "/NativeNext.gs", "utf8");
const audioSrc = fs.readFileSync(__dirname + "/NativeAudio.gs", "utf8");
const pilotSrc = fs.readFileSync(__dirname + "/../../translation-system/google_sheet_pilot_tts_runner.py", "utf8");
const priority = ["es","id","km","vi","th","ja","ko","ta","hi",
                  "bn","ne","lo","my","it","pt"];
assert(nextSrc.includes('const SK_NEXT_DAILY_LIMIT = 4500;'));
assert(nextSrc.includes("Number(b.period)-Number(a.period)"));
assert(audioSrc.includes('Number(lesson.period)>=262 && lang!=="en"'));
assert(audioSrc.includes('requested.review!=="approved_risk_based_not_full"'));
assert(pilotSrc.includes("int(task_match.group(1))>=262 and not quality_key"));
assert(pilotSrc.includes('"state":"qa_pending"'));

// Real production source ordering, not a guessed fixture implementation.
const lesson = {segments:[{id:0,start:0,end:70,text:"Approved English"}]};
const sourceContext = vm.createContext({
  readTasks_: () => [{id:"P261-L02",period:261,en:"完成",lesson:"2"},
                     {id:"P262-L01",period:262,en:"完成",lesson:"1"}],
  lessonFolders_: () => ({translation:{}}),
  cachedFileId_: () => "english-final-id",
  readJsonFile_: () => lesson,
  soulkeyNextSha_: () => "en-hash",
  Logger:{log:()=>{}}
});
new vm.Script(section("NativeNext.gs","soulkeyNextSources_","soulkeyNextEnsureRows_"))
  .runInContext(sourceContext);
assert.deepStrictEqual(
  Array.from(sourceContext.soulkeyNextSources_(), x => x.task),
  ["P262-L01","P261-L02"]);

// Exercise the actual scheduled production reconcile with P262 and P261.
// A missing P262 QA must never queue its unapproved formal audio.
const code = section("Code.gs","soulkeyAutoSheetsInitialAudioReconcile_",
                     "soulkeyAutoAudioReconcile_");
let qaReady = false;
let queued = [];
const props = new Map();
const ctx = vm.createContext({
  SK_NEXT_PRIORITY_LANGS:priority,
  PropertiesService:{getScriptProperties:()=>({
    getProperty:k => k==="GITHUB_TOKEN"?"test-token":props.get(k),
    setProperty:(k,v) => props.set(k,v)
  })},
  readTasks_:()=>[
    {id:"P261-L02",period:261,en:"完成"},
    {id:"P262-L01",period:262,en:"完成"},
  ],
  lessonFolders_:id=>({
    translation:{type:"translation",id},
    lesson:{type:"lesson",id}
  }),
  cachedChildFolder_:(folder,name)=>({id:folder.id,type:name}),
  cachedFileId_:(folder,name)=>{
    if(name==="en.final.json")return "english";
    if(name.endsWith("-es-google-translate-DRAFT.json"))return "draft";
    if(name==="sheets.qa.approved.es.json")return qaReady?"approved":null;
    return null;
  },
  readJsonFile_:(folder,name)=>{
    if(name==="sheets.qa.es.json")return qaReady?{state:"approved_risk_based"}:null;
    return null;
  },
  dispatchWorkflowIdempotently_:(token,task,stage,lang,langs)=>{
    queued.push({task,stage,langs});
    return {ok:true,duplicate:false,workflow_run_id:"mock-id"};
  },
  appendExecutionStatus_:()=>{},
  Logger:{log:()=>{}}
});
new vm.Script(code).runInContext(ctx);
let result=ctx.soulkeyAutoSheetsInitialAudioReconcile_();
assert.equal(result.task_id,"P261-L02", "unapproved P262 must be skipped");
assert.equal(queued[0].task,"P261-L02");
qaReady=true;
result=ctx.soulkeyAutoSheetsInitialAudioReconcile_();
assert.equal(result.task_id,"P262-L01", "P262 should be first once reviewed");
assert.equal(result.langs,"es");
assert.equal(queued[1].task,"P262-L01");
assert.equal(queued[1].stage,"pilot_tts");
console.log("PASS P262 newer lesson priority, QA-gated TTS, 261 backward compatibility");

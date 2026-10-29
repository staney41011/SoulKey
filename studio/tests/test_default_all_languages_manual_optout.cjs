"use strict";
const assert=require("node:assert/strict"),vm=require("node:vm"),fs=require("node:fs"),path=require("node:path");
const src=fs.readFileSync(path.join(__dirname,"..","app-20260923-48.js"),"utf8");
const start=src.indexOf("function normalizedLanguagePlan(task){");
const end=src.indexOf("\nconst LANGUAGE_ZH_NAMES=",start);
if(start<0||end<=start)throw Error("normalizedLanguagePlan missing");
const fn=src.slice(start,end);
const settings=["en","th","es","id","vi","hi","ta","ja","ko","km","bn","ne","lo","my","it","pt"]
 .map(code=>({code,name:code}));
const normalize=(task)=>vm.runInNewContext(
 "const languageSettings="+JSON.stringify(settings)+";\n"+fn+
 "\nnormalizedLanguagePlan("+JSON.stringify(task)+")",
 {},{timeout:1000});
const initial=normalize({languagePlan:[]});
assert.equal(initial.length,16);
assert(initial.every(x=>x.audio_enabled));
assert(initial.every(x=>x.transcript_enabled));
assert.equal(initial.find(x=>x.language_code==="en").transcript_source,"human");
const revised=initial.map(x=>x.language_code==="ja"?{...x,
 audio_enabled:false,transcript_enabled:false}:x);
const persisted=normalize({languagePlan:revised});
assert.equal(persisted.find(x=>x.language_code==="ja").audio_enabled,false);
assert.equal(persisted.find(x=>x.language_code==="ja").transcript_enabled,false);
assert.equal(persisted.filter(x=>x.audio_enabled).length,15);
const extended=normalize({languagePlan:revised.filter(x=>x.language_code!=="pt")});
assert.equal(extended.find(x=>x.language_code==="pt").audio_enabled,false,
 "Existing plan must not unexpectedly enable a new language");
console.log("PASS: 16 languages selected initially; manual unchecks persist on reload");

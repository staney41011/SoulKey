const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const code=fs.readFileSync(path.resolve(__dirname,"../../bridge/apps-script/Code.gs"),"utf8");
let githubCopies=[];
const githubFiles={
  "studio-review-cache/P258-L02/zh.json":{task_id:"P258-L02",content:"Lower lesson"},
  "studio-review-cache/P258-L03/zh.json":{task_id:"P258-L03",content:"Upper lesson"}
};
const statuses=[["P258-L02"],["P258-L03"],["P258-L01"]];
const plans=[["P258-L03"],["P258-L02"],["P258-L04"]];
function sheet(data){
 return {getLastRow(){return data.length+1;},getRange(r,c,n,m){
  assert.equal(c,1);assert.equal(m,1);
  return {getValues(){return data.map(x=>x.slice());},
   setValues(rows){rows.forEach((a,i)=>data[i]=a.slice());}};
 }};
}
const rows={"執行狀態":sheet(statuses),"語言任務設定":sheet(plans)};
const sandbox={
 console,Set,
 Utilities:{
  newBlob(v){return {getBytes:()=>Buffer.from(v),getDataAsString:()=>Buffer.from(v).toString("utf8")}},
  base64Decode:s=>Buffer.from(s,"base64"),base64Encode:b=>Buffer.from(b).toString("base64")
 },
 PropertiesService:{getScriptProperties(){return {getProperty:()=>"test-token"}}},
 SpreadsheetApp:{openById(){return {getSheetByName:name=>rows[name]}}},
 githubPathEncode_:name=>name,
 UrlFetchApp:{fetch(url){
  const key=url.split("/contents/")[1].split("?")[0];
  return {getResponseCode:()=>githubFiles[key]?200:404,
   getContentText:()=>JSON.stringify({content:Buffer.from(JSON.stringify(githubFiles[key])).toString("base64")})};
 }},
 githubUpsertBase64_:(token,payloadPath,b64)=>{
  githubCopies.push({path:payloadPath,value:JSON.parse(Buffer.from(b64,"base64").toString("utf8"))});
  return {ok:true};
 },
 clearScheduleCaches_:()=>{}
};
vm.createContext(sandbox);
vm.runInContext(code,sandbox,{timeout:15000});
sandbox.githubUpsertBase64_=(token,payloadPath,b64)=>{githubCopies.push({path:payloadPath,value:JSON.parse(Buffer.from(b64,"base64").toString("utf8"))});return {ok:true};};
assert.equal(vm.runInContext("scheduledTaskId_(258,2)",sandbox),"P258-L02");
assert.equal(vm.runInContext("scheduledTaskId_(258,3)",sandbox),"P258-L03");
const mapping={"P258-L02":"P258-L03","P258-L03":"P258-L02"};
const refs=vm.runInContext("rekeyTaskReferenceSheets_("+JSON.stringify(mapping)+")",sandbox);
assert.equal(refs.status_rows,2);
assert.equal(refs.language_rows,2);
assert.deepEqual(JSON.parse(JSON.stringify(statuses)),[["P258-L03"],["P258-L02"],["P258-L01"]]);
assert.deepEqual(JSON.parse(JSON.stringify(plans)),[["P258-L02"],["P258-L03"],["P258-L04"]]);
const caches=vm.runInContext("rekeyGithubTaskCaches_("+JSON.stringify(mapping)+")",sandbox);
assert.equal(caches.updated_cache_files,2);
assert.equal(githubCopies.length,2);
assert.deepEqual(githubCopies.find(x=>x.path.endsWith("/P258-L02/zh.json")).value,
 {task_id:"P258-L02",content:"Upper lesson"});
assert.deepEqual(githubCopies.find(x=>x.path.endsWith("/P258-L03/zh.json")).value,
 {task_id:"P258-L03",content:"Lower lesson"});
// A legacy full formal name may have no SOULKEY_CANONICAL_NAME marker.
// It must nevertheless be renamed to the CURRENT lesson number.
let oldFilename="第255期_第4堂課_聖音法語解析 上_翁士琇_西班牙文CC字幕.srt";
const legacyFile={
 getName(){return oldFilename;},setName(value){oldFilename=value;},
 getDescription(){return "";},
};
function fakeFolder(files){return {getFiles(){let n=0;return {hasNext:()=>n<files.length,next:()=>files[n++]};}};}
sandbox.lessonFolders_=()=>({
 source:fakeFolder([legacyFile]),transcript:fakeFolder([]),translation:fakeFolder([]),
 lesson:fakeFolder([])
});
sandbox.cachedChildFolder_=()=>{throw new Error("not needed");};
sandbox.formalizableCanonicalName_=()=>false;
sandbox.formalOutputLabel_=name=>name;
sandbox.formalDriveName_=(id,name)=>"第255期_第2堂課_聖音法語解析 上_翁士琇_"+name;
sandbox.canonicalFromDescription_=()=>null;
const renamed=vm.runInContext("migrateOneLessonFormalNames_('P255-L02')",sandbox);
assert.equal(renamed.renamed,1);
assert.equal(oldFilename,"第255期_第2堂課_聖音法語解析 上_翁士琇_西班牙文CC字幕.srt");
console.log("SoulKey schedule identity swap + legacy formal rename: OK");

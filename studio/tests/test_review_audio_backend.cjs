"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const source=fs.readFileSync(path.resolve(__dirname,"../../bridge/apps-script/Code.gs"),"utf8");
const start=source.indexOf("function ttsShareLinks_(taskId) {");
const stop=source.indexOf("function courseFilesOverview_(taskId)",start);
assert(start>0&&stop>start);
function item(name,id){
  return {getName:()=>name,getId:()=>id,getSize:()=>1000,
    getUrl:()=>"https://drive.google.com/file/d/"+id+"/view"};
}
const official=item("en.mp3","1OfficialEnPreviewTest00000000");
const preview=item("en.preview.mp3","1ReviewEnPreviewTest000000000");
const folder={
 getFilesByName:name=>{
  const selected=name==="en.mp3"?[official]:name==="en.preview.mp3"?[preview]:[];
  return {hasNext:()=>selected.length>0,next:()=>selected[0]};
 }};
const context={
 lessonFolders_:()=>({lesson:{}}),
 cachedChildFolder_:()=>folder,
 formalDriveName_:(id,canonical)=>"formal_"+canonical
};
vm.createContext(context);
vm.runInContext(source.slice(start,stop),context);
const result=context.ttsShareLinks_("P258-L03");
assert.equal(result.ok,true);
const files=result.groups[0].files;
assert.equal(files.length,2,"Both review preview and older official are discoverable");
const old=files.find(x=>x.canonical_name==="en.mp3");
const review=files.find(x=>x.canonical_name==="en.preview.mp3");
assert.equal(old.needs_timing_review,false);
assert.equal(review.needs_timing_review,true);
assert.equal(review.audio_kind,"standalone_preview");
assert.ok(review.size>0&&review.url.includes(review.id));
assert.equal(context.ttsShareLinks_("../bad").ok,false);
console.log("SOULKEY_REVIEW_AUDIO_LOOKUP_OK");

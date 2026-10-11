"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const bridge=fs.readFileSync(path.join(__dirname,"../../bridge/apps-script/Code.gs"),"utf8");
const start=bridge.indexOf("function recoverFormalAudioCanonicalName_(");
const stop=bridge.indexOf("function formalizableCanonicalName_(",start);
assert(start>=0&&stop>start,"Canonical audio helper/overview missing");
const src=bridge.slice(start,stop);
const audioID="12-mxdr9nW3vJE9HluZQWwXfxFt_W43-S";
const file=(name,id,description="")=>({
  getName:()=>name,
  getId:()=>id,
  getDescription:()=>description,
  getUrl:()=> "https://drive.google.com/file/d/"+id+"/view",
  getSize:()=>id==="1RX_qP5JzUBGd8_fD7UCg2bII5QUrTLMG"?30738477:1155500,
  getLastUpdated:()=>new Date("2026-10-11T09:15:00Z")
});
function folder(id,files=[]){
  return {
    getId:()=>id,
    getFiles:()=>{let pos=0;return{hasNext:()=>pos<files.length,next:()=>files[pos++]};}
  };
}
const mp3=file("第257期_第2堂課_心態是最好的風水 上_李麗紅_高棉文TTS音檔.mp3","1RX_qP5JzUBGd8_fD7UCg2bII5QUrTLMG");
const short=file("第257期_第2堂課_心態是最好的風水 上_李麗紅_高棉文自然語音短試聽.mp3","preview-small");
const longPreview=file("第257期_第2堂課_心態是最好的風水 上_李麗紅_韓文自然試聽版.mp3","korean-full");
const previous=file("第257期_第2堂課_心態是最好的風水 上_李麗紅_英文TTS音檔.mp3","en-canonical","SOULKEY_CANONICAL_NAME:en.mp3");
const folders={
  "04_音檔":folder(audioID,[mp3,short,longPreview,previous]),
  "05_完成影片":folder("video")
};
const context={
 ensureTaskNamingMetadata_:()=>({period:257,lesson:"第2堂",title:"心態是最好的風水 上|李麗紅",lecturer:"李麗紅"}),
 lessonFolders_:()=>({lesson:folder("lesson"),source:folder("source"),transcript:folder("transcript"),translation:folder("translation")}),
 cachedChildFolder_:(root,name)=>folders[name],
 canonicalFromDescription_:s=>(/SOULKEY_CANONICAL_NAME:([^\n]+)/.exec(s)||[])[1]||"",
 formalizableCanonicalName_:name=>/^([a-z]{2})\.(mp3|preview\.mp3)$/.test(name),
 formalDriveName_:(taskId,name)=>"P257-L02_"+name
};
vm.createContext(context);
vm.runInContext(src,context);
const parse=context.recoverFormalAudioCanonicalName_;
assert.equal(parse(mp3.getName()),"km.mp3");
assert.equal(parse(short.getName()),"");
assert.equal(parse(longPreview.getName()),"ko.preview.mp3");
assert.equal(parse(previous.getName()),"en.mp3");
for(const lang of ["泰文","西班牙文","印尼文","越南文","印地語","泰米爾文","日文","韓文","高棉文"]){
 assert(parse("第258期_第1堂課_課名_講師_"+lang+"TTS音檔.mp3").endsWith(".mp3"));
}
const result=context.courseFilesOverview_("P257-L02");
assert.equal(result.ok,true);
const audio=result.groups.find(g=>g.key==="audio");
assert.equal(audio.folder_url,"https://drive.google.com/drive/folders/"+audioID);
assert.equal(audio.files.length,3,"formal Khmer, English, Korean preview all visible; teaser excluded");
const khmer=audio.files.find(x=>x.id==="1RX_qP5JzUBGd8_fD7UCg2bII5QUrTLMG");
assert(khmer,"Khmer formal MP3 must be in Studio course overview");
assert.equal(khmer.display_name,mp3.getName());
assert.equal(khmer.size,30738477);
const korean=audio.files.find(x=>x.id==="korean-full");
assert.equal(korean.needs_timing_review,true);
assert(!audio.files.some(x=>x.id==="preview-small"));
console.log("PASS: Chinese formal Khmer MP3 visible in actual course-files overview");
console.log("PASS: 30.7 MB/full ID preserved; short teaser excluded");
console.log("PASS: Long Korean preview flagged for timing review");
console.log("PASS: Existing English canonical MP3 unchanged");
console.log("PASS: Multi-language formal naming recognized");

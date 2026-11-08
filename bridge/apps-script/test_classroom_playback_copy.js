const fs=require("fs"),vm=require("vm"),assert=require("assert"),path=require("path");
const code=fs.readFileSync(path.join(__dirname,"NativePlayback.gs"),"utf8");
const files=new Map(),receipts=new Map(),logs=[];
let nextId=0,copyCount=0;
function iterator(a){
  let i=0;
  return {hasNext:()=>i<a.length,next:()=>a[i++]};
}
class Folder {
  constructor(name){
    this.name=name;this.id="folder"+(++nextId);this.folders=[];
    this.files=[];this.parent=null;
  }
  getId(){return this.id}
  getName(){return this.name}
  getUrl(){return "https://drive.google.com/drive/folders/"+this.id}
  getFoldersByName(name){return iterator(this.folders.filter(f=>f.name===name))}
  createFolder(name){const f=new Folder(name);f.parent=this;this.folders.push(f);return f}
  getFilesByName(name){return iterator(this.files.filter(f=>f.name===name))}
  getFiles(){return iterator(this.files)}
}
class File {
  constructor(name,folder,bytes=15000){
    this.name=name;this.id="file"+(++nextId);this.folder=folder;
    this.size=bytes;this.description="";this.trashed=false;
    folder.files.push(this);files.set(this.id,this);
  }
  getId(){return this.id}
  getName(){return this.name}
  setName(s){this.name=s;return this}
  getDescription(){return this.description}
  setDescription(s){this.description=s;return this}
  getSize(){return this.size}
  isTrashed(){return this.trashed}
  getParents(){return iterator([this.folder])}
  makeCopy(name,folder){
    copyCount++;
    const f=new File(name,folder,this.size);
    f.description=this.description;
    return f;
  }
}
const root=new Folder("所有口譯檔案");
const ctx=vm.createContext({
  DriveApp:{getFolderById:id=>{
      assert.equal(id,"1Z2BTD_WvMG08VSa3MSECFNj1yy_UuO66");
      return root;
    },getFileById:id=>{
      const file=files.get(id);
      if(!file)throw Error("Drive file missing");
      return file;
    }},
  readTasks_:()=>[],
  readJsonFile_:(folder,name)=>receipts.get(folder.name+"|"+name)||null,
  writeTextFile_:(folder,name,json)=>{
    receipts.set(folder.name+"|"+name,JSON.parse(json));
  },
  soulkeyNextNow_:()=>"2026-11-08T09:00:00+08:00",
  Logger:{log:t=>logs.push(t)},
  Date,JSON,Object,Array,Number,String,Math
});
new vm.Script(code,{filename:"NativePlayback.gs"}).runInContext(ctx);
const task={id:"P261-L01",period:261,lesson:"1",title:"心念的力量232",
  lecturer:"中和老師"};
const lesson={task:"P261-L01",period:261,lesson:"1",folder:{name:"translation261"}};
function makeReceipt(lang,sha,status){
  const original=new Folder("original lesson folder");
  const file=new File("P261-L01-"+lang+"-"+sha.slice(0,16)+
      (status==="done"?".mp3":".preview.mp3"),original,1881888);
  return {file,receipt:{
    status,release_tag:"release-"+lang+"-"+sha,
    source_sha256:sha,mp3_drive_id:file.getId()
  },requested:{tag:"release-"+lang+"-"+sha,sha,
    review:lang==="en"?"approved_english_final":"approved_risk_based_not_full"}};
}
const initial=makeReceipt("en","a".repeat(64),"needs_review");
let o=ctx.skPlaybackEnsure_(lesson,"en",initial.receipt,initial.requested,task);
assert(o.ok && o.created);
assert.equal(copyCount,1);
assert.equal(root.folders.length,1);
const period=root.folders[0],en=period.folders[0];
assert.equal(period.name,"261");
assert.equal(en.name,"英文");
const preview=en.files[0];
assert.equal(preview.getName(),
 "第261期_第1堂課_心念的力量232_中和老師_英文TTS音檔_待驗收.mp3");
assert.equal(initial.file.getName(),"P261-L01-en-aaaaaaaaaaaaaaaa.preview.mp3");
assert.equal(initial.file.folder.name,"original lesson folder");
const still=ctx.skPlaybackEnsure_(lesson,"en",initial.receipt,initial.requested,task);
assert(still.ok && !still.created && still.idempotent);
assert.equal(copyCount,1,"same source cannot produce duplicate");
const revised=makeReceipt("en","b".repeat(64),"done");
o=ctx.skPlaybackEnsure_(lesson,"en",revised.receipt,revised.requested,task);
assert(o.ok && o.created);
assert.equal(copyCount,2);
assert.equal(en.files.length,2,"old audio retained, never deleted");
assert.equal(en.files.filter(f=>f.name.endsWith("_舊版_aaaaaaaaaa.mp3")).length,1);
assert.equal(en.files.filter(f=>f.name==="第261期_第1堂課_心念的力量232_中和老師_英文TTS音檔.mp3").length,1);
assert.equal(revised.file.folder.name,"original lesson folder");
// Updating the class title must update only the new playback copy, not source.
task.title="更新後的課名";
const renamed=ctx.skPlaybackEnsure_(lesson,"en",revised.receipt,revised.requested,task);
assert(renamed.ok && renamed.created);
assert(renamed.name.includes("更新後的課名"));
assert(en.files.some(f=>f.name.includes("心念的力量232") && f.name.includes("_舊版_")));
assert.equal(revised.file.folder.name,"original lesson folder");
task.title="心念的力量232";
const missing=makeReceipt("th","c".repeat(64),"done");
missing.file.size=0;
assert.throws(()=>ctx.skPlaybackEnsure_(lesson,"th",missing.receipt,missing.requested,task),/source_mp3_missing/);
assert.equal(period.folders.length,1,"no target dirs for invalid audio");
const collision=makeReceipt("km","d".repeat(64),"done");
const khmer=period.createFolder("柬文");
const manualName="第261期_第1堂課_心念的力量232_中和老師_柬文TTS音檔.mp3";
const manual=new File(manualName,khmer);
o=ctx.skPlaybackEnsure_(lesson,"km",collision.receipt,collision.requested,task);
assert(o.ok && o.created);
assert.equal(manual.getName(),manualName);
assert(!manual.getDescription().startsWith("SoulKey-CLASSROOM-COPY|"));
assert(khmer.files.some(f=>f.name.includes("_系統副本_dddddddddd.mp3")));
const noQA=makeReceipt("es","e".repeat(64),"done");
noQA.requested.review="not_approved";
o=ctx.skPlaybackEnsure_(lesson,"es",noQA.receipt,noQA.requested,task);
assert(o.ok && o.name.includes("_待驗收.mp3"));
const beforeSemanticPromotion=copyCount;
noQA.requested.review="approved_risk_based_not_full";
o=ctx.skPlaybackEnsure_(lesson,"es",noQA.receipt,noQA.requested,task);
assert(o.ok && o.name.endsWith("西班牙TTS音檔.mp3"));
assert.equal(copyCount,beforeSemanticPromotion+1);
const esFolder=period.folders.find(x=>x.name==="西班牙");
assert(esFolder.files.some(x=>x.name.includes("_待驗收_舊版_")));
const wrong=makeReceipt("it","f".repeat(64),"done");
const bogus=ctx.skPlaybackEnsure_(lesson,"it",wrong.receipt,{tag:"not-the-same",sha:wrong.requested.sha},task);
assert.equal(bogus.ok,false);
assert.equal(period.folders.length,3);
assert(ctx.skPlaybackSafePart_("Bad/Name\\*?").indexOf("/")<0);
console.log("PASS separate original MP3, preview, formal, revision archiving, manual collision, idempotence and retry guard");

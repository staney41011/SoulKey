const fs=require("fs"),vm=require("vm"),assert=require("assert");
const path=require("path");
const src=fs.readFileSync(path.join(__dirname,"NativeAudio.gs"),"utf8");
const requested={tag:"P261-L01-es-0123456789abcdef",sha:"0123456789abcdef0123",
  review:"not_approved",payload:{segments:[]}};
const lesson={task:"P261-L01",folder:{}};
const created=[],receipts=[];
const ctx=vm.createContext({
  Utilities:{newBlob:(bytes)=>({
    getDataAsString:()=>Buffer.from(bytes).toString("utf8"),
    setName(name){this.name=name;return this}
  })},
  Number,String,Date,Array,Object,JSON,
  lessonFolders_:()=>({lesson:{}}),
  cachedChildFolder_:()=>({}),
  soulkeyNextNow_:()=>"2026-11-08 09:00:00"
});
new vm.Script(src,{filename:"NativeAudio.gs"}).runInContext(ctx);
let result;
ctx.skAudioAssetByName_=(_release,name)=>({name});
ctx.skAudioAsset_=(meta)=>Buffer.from(JSON.stringify(result),"utf8");
ctx.skAudioAssetChecked_=()=>Buffer.from("MP3_FILE_CONTENT_".repeat(1200),"utf8");
ctx.skAudioCanonicalFile_=(_folder,name,_blob,desc)=>{
  created.push({name,desc});
  return {getId:()=>name};
};
ctx.skAudioSaveReceipt_=(_lesson,_lang,receipt)=>{receipts.push(receipt)};
result={
  task_id:"P261-L01",language:"es",release_tag:requested.tag,
  source_sha256:requested.sha,status:"done",
  files:{"voice.mp3":{bytes:18000,sha256:"mock"}},
  wav_chunks:[],source_duration_seconds:100,timing:{}
};
const recovery=ctx.skAudioImport_(lesson,"es",requested,{assets:[]});
assert.equal(recovery.status,"needs_review");
assert(recovery.issue.includes("wav_import_failed"));
assert(recovery.mp3_drive_id.endsWith(".preview.mp3"));
assert(created.some(x=>x.name.endsWith(".mp3")));
assert(created.some(x=>x.name.endsWith(".preview.mp3")));
assert.equal(receipts.at(-1).status,"needs_review");
created.length=0;
result.status="needs_review";
result.files={"voice.preview.mp3":{bytes:18000,sha256:"mock"}};
const review=ctx.skAudioImport_(lesson,"es",requested,{assets:[]});
assert.equal(review.status,"needs_review");
assert(review.mp3_drive_id.endsWith(".preview.mp3"));
assert(!created.some(x=>x.name.endsWith(".wav")));
created.length=0;
result.status="done";
result.files={
  "voice.mp3":{bytes:18000,sha256:"mock"},
  "voice.wav.part001":{bytes:64,sha256:"mock_wav"}
};
result.wav_chunks=["voice.wav.part001"];
result.wav_bytes=64;
ctx.skAudioAssetByName_=(_release,name)=>({name,size:64});
ctx.skAudioUploadWav_=()=>{throw new Error("WAV must not block MP3 delivery");};
const formal=ctx.skAudioImport_(lesson,"es",requested,{assets:[]});
assert.equal(formal.status,"done");
assert.equal(formal.mp3_drive_id.endsWith(".mp3"),true);
assert.equal(formal.mp3_drive_id.endsWith(".preview.mp3"),false);
assert.equal(formal.wav_drive_id,null);
assert.equal(formal.wav_archived_release_tag,requested.tag);
assert.equal(formal.wav_archived_parts,1);
assert.equal(receipts.at(-1).status,"done");
assert(created.some(x=>x.name.endsWith(".mp3") && !x.name.endsWith(".preview.mp3")));
console.log("PASS MP3-first formal import, private WAV release archive and guarded preview");

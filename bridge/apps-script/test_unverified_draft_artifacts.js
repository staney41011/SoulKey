const fs=require("fs"),vm=require("vm"),assert=require("assert");
const path=require("path");
const code=fs.readFileSync(path.join(__dirname,"NativeNext.gs"),"utf8");
const files=new Map();
function makeFile(name,data){
  const f={
    name,data,getBlob(){return {getDataAsString:()=>this.data}},
    setContent(v){this.data=v;return this},
    getUrl(){return "https://drive.google.com/file/d/"+name+"/view"},
    getSize(){return this.data.length},isTrashed(){return false}
  };
  files.set(name,f);
  return f;
}
const drafts={
  getFilesByName(name){return {hasNext:()=>files.has(name),next:()=>files.get(name)}},
  createFile(name,value){return makeFile(name,value)}
};
const lessonFolder={
  getFoldersByName:()=>({hasNext:()=>true,next:()=>drafts}),
  createFolder:()=>drafts
};
const ctx=vm.createContext({
  Utilities:{
    computeDigest:()=>Array(32).fill(23),
    DigestAlgorithm:{SHA_256:"SHA256"},
    Charset:{UTF_8:"UTF8"},
    formatDate:()=>"2026-11-08 09:00:00"
  },
  Date,Number,String,Array,Object,JSON,
  MimeType:{PLAIN_TEXT:"text/plain"},
  readLanguagePlan_:()=>[{language_code:"es",transcript_enabled:true,
    transcript_source:"ai",audio_enabled:true,audio_source:"tts"}],
  Logger:{log:()=>{}}
});
new vm.Script(code,{filename:"NativeNext.gs"}).runInContext(ctx);
const source={task:"P261-L01",folder:lessonFolder,source_file_id:"source_en_1",
  segments:[
    {id:1,start:0,end:12,text:"Hello",source_hash:"hash1"},
    {id:2,start:12,end:28,text:"World",source_hash:"hash2"}
  ]};
const row=(seg)=>[source.task,seg.id,seg.start,seg.end,seg.text,
  seg.source_hash,...Array(19).fill("")];
const rows=source.segments.map(row);
rows[0][7]="Hola";
let result=ctx.soulkeyNextExport_([source],rows);
assert.equal(result.length,1);
assert.equal(result[0].complete,false);
const partialName="P261-L01-es-google-translate-PARTIAL";
assert(files.has(partialName+".json"));
assert(files.has(partialName+".txt"));
let draft=JSON.parse(files.get(partialName+".json").data);
assert.equal(draft.status,"partial_unverified");
assert.equal(draft.translated_segments,1);
assert.equal(draft.total_segments,2);
assert.equal(draft.unverified,true);
assert(!files.has("P261-L01-es-google-translate-DRAFT.json"));
rows[1][7]="Mundo";
result=ctx.soulkeyNextExport_([source],rows);
assert.equal(result.length,1);
assert.equal(result[0].complete,true);
const completeName="P261-L01-es-google-translate-DRAFT";
assert(files.has(completeName+".json"));
assert(files.has(completeName+".txt"));
draft=JSON.parse(files.get(completeName+".json").data);
assert.equal(draft.segments.length,2);
assert.equal(draft.complete,true);
assert.equal(draft.unverified,true);
assert(files.get(partialName+".json").data.includes("partial_unverified"));
console.log("PASS untranslated/QA-pending outputs keep partial and complete TXT+JSON files");

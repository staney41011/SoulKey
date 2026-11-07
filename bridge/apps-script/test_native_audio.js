const fs=require("fs"),vm=require("vm"),crypto=require("crypto"),
  zlib=require("zlib"),assert=require("assert");
const sha=s=>crypto.createHash("sha256").update(String(s),"utf8").digest("hex");
const ctx=vm.createContext({
  console,Math,Date,JSON,Number,String,Array,Object,Set,
  Utilities:{
    DigestAlgorithm:{SHA_256:"SHA_256"},Charset:{UTF_8:"UTF_8"},
    computeDigest:(a,s)=>Array.from(crypto.createHash("sha256")
      .update(String(s)).digest()).map(x=>x>127?x-256:x),
    gzip:b=>({getBytes:()=>Array.from(zlib.gzipSync(Buffer.from(b.text)))}),
    newBlob:(text)=>({text:String(text)}),
    base64EncodeWebSafe:b=>Buffer.from(b).toString("base64url"),
    formatDate:()=>"2026-11-07 14:00:00"
  },
  Logger:{log:()=>{}},
  PropertiesService:{getScriptProperties:()=>({getProperty:()=>null})}
});
for(const file of ["NativeNext.gs","NativeQuality.gs","NativeAudio.gs"])
  new vm.Script(fs.readFileSync(__dirname+"/"+file,"utf8"),
    {filename:file}).runInContext(ctx);
const segments=[
  {id:0,start:0,end:61.5,text:"Peace to every family.",source_hash:"a"},
  {id:1,start:61.5,end:120,text:"Cultivate kindness.",source_hash:"b"}
];
const lesson={task:"P261-L01",segments,source_file_id:"EN-ID",folder:{}};
const en=ctx.skAudioPayload_(lesson,"en",[]);
assert(en);
const raw=zlib.gunzipSync(Buffer.from(en.encoded,"base64url"));
const payload=JSON.parse(raw.toString("utf8"));
assert.equal(payload.task_id,"P261-L01");
assert.equal(payload.language,"en");
assert.equal(payload.segments.length,2);
// Golden SHA from Python tts_fingerprint.segments_fingerprint:
// Python serializes integral timestamps as 0.0 / 120.0, not 0 / 120.
const expected="1cc95c64bfe77a86fdd3b49e127385d61f2f56e5288be5e6a2fdd57a8f8c1fd3";
assert.equal(en.sha,expected);
assert.equal(en.review,"approved_english_final");
assert(!raw.toString().includes("GITHUB_TOKEN"));
const translated=segments.map((x,i)=>({
  id:x.id,start:x.start,end:x.end,source_hash:x.source_hash,
  text:i?"Cultiva la bondad.":"Paz para cada familia."
}));
const draft={task_id:"P261-L01",language:"es",source_file_id:"EN-ID",
  segments:translated};
ctx.skNQDraft_=()=>({draft,id:"DRAFT-ID"});
const revision=ctx.soulkeyNextSha_(JSON.stringify({
  task:lesson.task,language:"es",draft:translated,english:segments,terms:[]
}));
ctx.readJsonFile_=()=>({revision_key:revision,state:"approved_risk_based",
  decisions:{"0":{grade:"B_verified",
    corrected_text:"Que la paz llegue a todas las familias."}}});
const es=ctx.skAudioPayload_(lesson,"es",[]);
assert(es);
assert.equal(es.review,"approved_risk_based_not_full");
assert.equal(es.payload.segments[0].text,
  "Que la paz llegue a todas las familias.");
assert.notEqual(es.sha,ctx.skAudioFingerprint_(translated));
assert(es.tag.startsWith("P261-L01-es-"));
console.log("PASS next-period English + revised Sheets/Gemma4 private TTS payload");

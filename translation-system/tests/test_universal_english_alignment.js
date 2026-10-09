"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
function pick(source,name){
  const begin=source.indexOf("function "+name+"(");
  assert(begin>=0,"Function not found: "+name);
  const next=source.indexOf("\nfunction ",begin+9);
  return source.slice(begin,next>=0?next:undefined);
}
const script=fs.readFileSync("bridge/apps-script/Code.gs","utf8");
// Generated fixtures keep CI self-contained: 471 short Chinese sentences,
// 599 overlapping English caption cues with full stops every eighth cue.
const sampleZh={finalized_at:"2026-10-09T03:03:36Z",segments:Array.from(
  {length:471},(_,id)=>({
    id,start:4*id,end:4*id+2,text:"中文對照段落"+id+"。"
  })
)};
const sampleEn={video_id:"test-source-video",segments:Array.from(
  {length:599},(_,i)=>({
    start:3.05*i,end:3.05*i+2.8,
    text:"English caption fragment "+i+(i%8===7?".":"")
  })
)};
let published=null;
const box={
  Date,Math,Number,String,Array,Object,
  formatPlainTime_:sec=>String(sec),
  chineseFinalForEnglishTimeRange_:rows=>(rows||[]).map(x=>x.text).join(""),
  lessonFolders_:id=>({transcript:"zh",source:"src",translation:"en"}),
  readJsonFile_:(folder,name)=>{
    const values={
      "zh/zh-TW.final.json":sampleZh,
      "src/youtube.en.json":sampleEn
    };
    return values[folder+"/"+name]||null;
  },
  publishEnglishReviewCachePayload_:(id,data)=>{
    published=data;
    return {ok:true,count:data.total_segments};
  }
};
vm.createContext(box);
vm.runInContext(
  pick(script,"alignEnglishReviewParagraphs_")+"\n"+
  pick(script,"seedEnglishReviewCache_"),
  box
);
const result=box.seedEnglishReviewCache_("P257-L04");
assert.equal(result.ok,true);
assert.equal(published.alignment_method,"english_sentence_chinese_time_v1");
assert.equal(published.source_video_id,"test-source-video");
assert.ok(published.total_segments>=45&&published.total_segments<=110);
assert.equal(published.original_zh_segments,471);
assert.equal(published.original_en_cc_cues,599);
assert.equal(published.segments.map(x=>x.text).join(""),
  sampleZh.segments.map(x=>x.text.trim()).join(""));
assert.ok(published.segments.every(x=>x.source_en===x.en_text));
assert.equal(published.segments[0].zh_ids[0],0);
assert.equal(published.segments.at(-1).zh_ids.at(-1),470);
console.log("PASS: every Chinese Final segment retained exactly once, CC retained");
console.log("PASS: automatic first English open publishes one-to-one aligned cache",published.total_segments);

// Never overwrite human English Final, even when automatic CC is available.
let humanPublish=null;
const humanBox={
  ...box,
  readJsonFile_:(folder,name)=>{
    if(name==="en.final.json")
      return {finalized_at:"2026-10-09T03:00:00Z",segments:[
        {id:0,start:0,end:20,text:"Manually approved English paragraph."}
      ]};
    return box.readJsonFile_(folder,name);
  },
  publishEnglishReviewCachePayload_:(_id,data)=>{humanPublish=data;return {ok:true};}
};
vm.createContext(humanBox);
vm.runInContext(
  pick(script,"alignEnglishReviewParagraphs_")+"\n"+
  pick(script,"seedEnglishReviewCache_"),humanBox
);
assert.equal(humanBox.seedEnglishReviewCache_("P257-L04").ok,true);
assert.equal(humanPublish.segments.length,1);
assert.equal(humanPublish.segments[0].en_text,"Manually approved English paragraph.");
console.log("PASS: existing English Final takes precedence over auto-caption alignment");

// A fast-cache re-seed must always preserve the human Chinese Final, even
// when the underlying AI polish report still has older draft wording.
let republishedZh=null;
const chineseCtx={
  lessonFolders_:()=>({transcript:"zh",source:"src"}),
  readJsonFile_:(folder,name)=>{
    if(name==="segments.json") return {segments:[{id:0,start:0,end:10,text:"ASR raw"}]};
    if(name==="polish_report.json") return {segments:[{id:0,start:0,end:10,text:"AI polish"}]};
    if(name==="zh-TW.final.json") return {
      finalized_at:"2026-10-09T03:03:36Z",
      segments:[{id:0,start:0,end:10,text:"Human confirmed Chinese Final"}]
    };
    return null;
  },
  zhReviewItems_:()=>[{id:0,start:0,end:10,raw:"ASR raw",text:"AI polish",confirmed:false}],
  Utilities:{base64Encode:s=>s,Charset:{UTF_8:"UTF8"}},
  githubUpsertBase64_:(_token,_path,encoded)=>{
    republishedZh=JSON.parse(encoded);
    return {ok:true};
  },
  OWNER:"owner",REPO:"repo",REF:"main"
};
vm.createContext(chineseCtx);
vm.runInContext(pick(script,"seedReviewCache_"),chineseCtx);
assert.equal(chineseCtx.seedReviewCache_("P257-L04","test-token").ok,true);
assert.equal(republishedZh.segments[0].text,"Human confirmed Chinese Final");
assert.equal(republishedZh.segments[0].confirmed,true);
assert.equal(republishedZh.zh_finalized_at,"2026-10-09T03:03:36Z");
console.log("PASS: repeated Chinese cache seeding never restores stale AI polish");

const quick=fs.readFileSync("studio/review-editor.js","utf8");
const sandbox={
  englishAligned:[{
    id:0,zh_ids:[0,1],text:"繁體中文第一段。",source_en:"First English.",
    en_text:"First English.",start:0,end:20
  }],
  segments:[{id:0,text:"中文A",start:0,end:10},{id:1,text:"中文B",start:10,end:20}]
};
vm.createContext(sandbox);
vm.runInContext(pick(quick,"englishGroups")+"\n"+pick(quick,"writeEnglishGroup"),sandbox);
assert.equal(sandbox.englishGroups().length,1);
assert.equal(Array.from(sandbox.englishGroups()[0].ids).join(","),"0,1");
sandbox.writeEnglishGroup({id:0,ids:[0,1]},"Human edited English.");
assert.equal(sandbox.englishAligned[0].en_text,"Human edited English.");
assert.equal(sandbox.segments[0].text,"中文A");
assert.equal(sandbox.segments[1].text,"中文B");
console.log("PASS: Quick Review edits aligned English without altering the Chinese segments");

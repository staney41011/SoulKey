"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const {alignmentRows,clean}=require("../english-cc-alignment.js");

const zh=Array.from({length:67},(_,i)=>({
 id:i,start:i*18,end:(i+1)*18,text:"這是已人工定稿的中文段落 "+i
}));
const cc=Array.from({length:2750},(_,i)=>
 "English-"+i+(i%23===22?".":",")).join(" \n ");
const source={video_id:"w7rzYft4MeE",job_id:"valid-job"};
const review=alignmentRows(zh,cc,source);
assert.equal(review.length,67);
assert.deepEqual(review.map(x=>x.id),zh.map(x=>x.id));
assert.deepEqual(review.map(x=>x.start),zh.map(x=>x.start));
assert(review.every(x=>x.pre_aligned===true&&
 x.estimated_cc_alignment===true&&x.en_confirmed===false));
assert(review.every(x=>x.en && x.source_en===x.en));
assert.equal(review.map(x=>x.en).join(" "),clean(cc));
assert(review.every(x=>x.source_video_id==="w7rzYft4MeE"));
assert.throws(()=>alignmentRows(zh,cc,{video_id:"wrong"}),/source_video_not_verified/);
assert.throws(()=>alignmentRows(zh,"tiny text",source),/english_caption_text_too_short/);
const markup=fs.readFileSync(path.join(root,"index.html"),"utf8");
const app=fs.readFileSync(path.join(root,"app-20260923-48.js"),"utf8");
assert(markup.indexOf("english-cc-alignment.js")<
  markup.indexOf("app-20260923-48.js"));
for(const marker of [
 "recoverEnglishCcIntoEditor(data.task_id)",
 'action:"youtube_cc_content"',
 'action:"youtube_capture_files"',
 'action:"review_load",task_id:taskId,kind:"zh"',
 'englishCanonicalLoadedTaskId=taskId',
 'if(typeof options.onResult==="function")options.onResult(data)'
])assert(app.includes(marker),"Missing bridge/edit integration: "+marker);
console.log("PASS: 67 English CC review rows preserve all source text, video identity and original Chinese Final");

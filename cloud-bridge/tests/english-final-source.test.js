"use strict";
const assert=require("node:assert/strict");
const {loadEnglishFinalSource}=require("../english-final-source");
const taskId="P259-L04",videoId="w7rzYft4MeE";
const original=[{id:0,start:0,end:31,text:"中文人工定稿"}];
const cc={name:"en.transcript.txt",task_id:taskId,storage:"google-sheet",job_id:"verified-cc-job"};
function fixture(options={}){
 const calls=[];
 const deps={
  taskId,sourceVideoId:videoId,targetVideoId:videoId,
  chineseFinalStore:{read:async task=>{calls.push("zh:"+task);return options.zh===undefined?{manuscript:{segments:original}}:options.zh;}},
  youtubeCCQueue:{
   manifest:async task=>{calls.push("cc-manifest:"+task);return options.manifest===undefined?
    {video_id:videoId,cc_files:[cc]}:options.manifest;},
   transcript:async(task,job,lang)=>{calls.push("cc-content:"+task+":"+job+":"+lang);
    return options.transcript===undefined?
      {ok:true,task_id:task,lang:"en",content:"English lecture text. ".repeat(30)}:
      options.transcript;}
  },
  driveReview:{review:async p=>{calls.push("drive:"+p.task_id);return options.drive===undefined?
   {ok:false}:options.drive;}}
 };
 return {deps,calls};
}
async function run(){
 const v=fixture();
 const saved=await loadEnglishFinalSource(v.deps);
 assert.strictEqual(saved.original,original);
 assert.equal(saved.recoveredCC,cc);
 assert.deepEqual(v.calls,[
  "zh:P259-L04","cc-manifest:P259-L04",
  "cc-content:P259-L04:verified-cc-job:en"
 ]);
 const legacy=fixture({zh:null,drive:{ok:true,segments:[{id:0,start:0,end:15,text:"Drive English"}]}});
 const old=await loadEnglishFinalSource(legacy.deps);
 assert.equal(old.original.length,1);
 assert.equal(old.recoveredCC,null);
 assert.deepEqual(legacy.calls,["zh:P259-L04","drive:P259-L04"]);
 const absent=fixture({manifest:{video_id:videoId,cc_files:[]},drive:{ok:false}});
 await assert.rejects(loadEnglishFinalSource(absent.deps),/english_source_missing_for_this_lesson/);
 const mismatch=fixture();
 await assert.rejects(loadEnglishFinalSource({...mismatch.deps,sourceVideoId:"other"}),
   /english_final_source_video_mismatch/);
 assert.deepEqual(mismatch.calls,[],"wrong video cannot read a different lesson");
 const corrupt=fixture({transcript:{ok:true,task_id:taskId,lang:"en",content:"short"}});
 await assert.rejects(loadEnglishFinalSource(corrupt.deps),/english_cc_source_content_invalid/);
 assert(!corrupt.calls.some(x=>x.startsWith("drive:")),
   "bad CC must not silently fall back to another source");
 const quota=fixture();
 quota.deps.chineseFinalStore.read=async()=>{throw Error("429 quota exceeded");};
 await assert.rejects(loadEnglishFinalSource(quota.deps),/429 quota exceeded/);
 assert.deepEqual(quota.calls,[],"quota must not be hidden behind missing-source error");
 console.log("PASS: same-video central CC first, legacy Drive fallback, quota/source isolation");
}
run().catch(e=>{console.error(e);process.exitCode=1;});

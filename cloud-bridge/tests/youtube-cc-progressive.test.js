"use strict";
const assert=require("node:assert/strict");
const {createYoutubeCCQueue,TASK_HEAD,CONTENT_HEAD}=require("../youtube-cc-queue");
const sheets={
 "任務佇列":[["task_id","period","lesson","title","url"],
     ["P259-L04","259","第4堂","","https://youtu.be/w7rzYft4MeE"]],
 "執行狀態":[["task_id","stage","status"]]
};
const ensureTab=async(name,head)=>{sheets[name]??=[head];};
const get=async name=>sheets[name]||[];
const put=async(name,range,rows,append)=>{
 await ensureTab(name,name==="YouTube CC 任務"?TASK_HEAD:CONTENT_HEAD);
 if(append){sheets[name].push(...rows);return;}
 const m=range.match(/^D(\d+):([HI])\d+$/);
 if(!m)throw Error("unsupported_update_"+range);
 const target=sheets[name][Number(m[1])-1];
 if(!target)throw Error("missing_row");
 rows[0].forEach((value,i)=>target[3+i]=value);
};
(async()=>{
 const cc=createYoutubeCCQueue({get,put,ensureTab,
   now:()=>new Date("2026-10-29T13:45:00Z").toISOString()});
 const queued=await cc.enqueue({task_id:"P259-L04",stage:"cc"});
 const {job}=await cc.claim();
 assert.equal(job.progressive_visibility,true);
 assert.equal(job.video_id,"w7rzYft4MeE");
 assert.equal((await cc.manifest("P259-L04")).cc_files.length,0);
 await cc.part({job_id:queued.job_id,language:"en",part_index:0,part_count:2,
   content:"English verified segment one. ",source:"automatic:en"});
 assert.equal((await cc.manifest("P259-L04")).cc_files.length,0);
 await cc.part({job_id:queued.job_id,language:"en",part_index:1,part_count:2,
   content:"English verified segment two.",source:"automatic:en"});
 let listed=await cc.manifest("P259-L04");
 assert.deepEqual(listed.cc_files.map(x=>x.name),["en.transcript.txt"]);
 assert.equal((await cc.transcript("P259-L04",queued.job_id,"en")).content,
   "English verified segment one. English verified segment two.");
 await cc.part({job_id:queued.job_id,language:"es",part_index:0,part_count:2,
   content:"Incomplete translation",source:"automatic:es"});
 await cc.finish({job_id:queued.job_id,status:"error",
   message:"HTTP 429 on Spanish track"});
 listed=await cc.manifest("P259-L04");
 assert.deepEqual(listed.cc_files.map(x=>x.name),["en.transcript.txt"]);
 assert.equal((await cc.transcript("P259-L04",queued.job_id,"en")).content,
   "English verified segment one. English verified segment two.");
 await assert.rejects(()=>cc.transcript("P259-L04",queued.job_id,"es"),
   /caption_content_not_complete/);
 assert.equal(sheets["YouTube CC 任務"][1][3],"error");
 assert.match(sheets["YouTube CC 任務"][1][7],/已保存字幕 en/);
 assert.equal(sheets["執行狀態"].at(-1)[2],"error");
 assert(!sheets["執行狀態"].at(-1).join(" ").includes("100%"));
 // A changed video cannot display another video's checkpoint.
 sheets["任務佇列"][1][4]="https://youtu.be/ChangedABC1";
 assert.equal((await cc.manifest("P259-L04")).cc_files.length,0);
 await assert.rejects(()=>cc.transcript("P259-L04",queued.job_id,"en"),
   /caption_job_not_verified_for_lesson/);
 console.log("PASS: English CC immediately readable; partial/failure preserved; other-video blocked");
})().catch(e=>{console.error(e);process.exitCode=1});

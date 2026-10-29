"use strict";
const assert=require("node:assert/strict");
const {createYoutubeCCQueue,videoId,TASK_HEAD,CONTENT_HEAD}=require("../youtube-cc-queue");
const tables={
 "任務佇列":[["task_id","period","lesson","title","url"],
    ["P259-L03","259","第3堂","","https://youtu.be/ThirdABC123"],
    ["P259-L04","259","第4堂","","https://youtu.be/FourthABC12"]],
 "執行狀態":[["task_id","stage","status"]]
};
const ensureTab=async(name,head)=>{tables[name]??=[head];};
const get=async name=>tables[name]||[];
const put=async(name,range,rows,append)=>{
 await ensureTab(name,name==="YouTube CC 任務"?TASK_HEAD:CONTENT_HEAD);
 if(append){tables[name].push(...rows);return;}
 const m=range.match(/^D(\d+):([HI])\d+$/);
 if(!m)throw Error("bad update "+range);
 const idx=Number(m[1])-1;
 const row=tables[name][idx];
 if(!row)throw Error("no row "+idx);
 rows[0].forEach((cell,i)=>row[3+i]=cell);
};
(async()=>{
 assert.equal(videoId("https://youtu.be/FourthABC12"),"FourthABC12");
 assert.equal(videoId("https://youtube.com/watch?v=ThirdABC123&t=60"),"ThirdABC123");
 const cc=createYoutubeCCQueue({get,put,ensureTab,
   now:()=>"2026-10-29T11:11:00.000Z"});
 await assert.rejects(()=>cc.enqueue({task_id:"P259-L05",stage:"cc"}),/task_not_registered/);
 await assert.rejects(()=>cc.enqueue({task_id:"P259-L04",stage:"cc",lang:"multi-audio"}),/unsupported_capture_stage/);
 const first=await cc.enqueue({task_id:"P259-L04",stage:"cc"});
 assert(first.ok && first.status==="queued");
 assert.equal(tables["YouTube CC 任務"].length,2);
 const second=await cc.enqueue({task_id:"P259-L04",stage:"cc"});
 assert(second.duplicate);assert.equal(second.job_id,first.job_id);
 const claim=await cc.claim();
 assert.equal(claim.job.task_id,"P259-L04");
 assert.equal(claim.job.video_id,"FourthABC12");
 assert.deepEqual(claim.job.languages,["en"]);
 await cc.part({job_id:first.job_id,language:"en",part_index:"0",part_count:"2",
     content:"Fourth-lesson English CC part 1",source:"automatic:en"});
 await assert.rejects(()=>cc.finish({
   job_id:first.job_id,status:"done",languages:"en"
 }),/cc_parts_missing/);
 const saved=await cc.part({job_id:first.job_id,language:"en",part_index:"0",
   part_count:"2",content:"Fourth-lesson English CC part 1"});
 assert(saved.duplicate);
 await assert.rejects(()=>cc.part({job_id:first.job_id,language:"en",
   part_index:"0",part_count:"2",content:"THIRD LESSON LEAK"}),
   /caption_part_conflict/);
 await cc.part({job_id:first.job_id,language:"en",part_index:"1",part_count:"2",
   content:"Fourth-lesson English CC part 2"});
 // English must be available to reviewers without waiting for seven languages.
 const active=await cc.manifest("P259-L04");
 assert.equal(active.cc_files.length,1);
 assert.equal(active.cc_files[0].name,"en.transcript.txt");
 assert.equal((await cc.transcript("P259-L04",first.job_id,"en")).content,
   "Fourth-lesson English CC part 1Fourth-lesson English CC part 2");
 const done=await cc.finish({job_id:first.job_id,status:"done",languages:"en"});
 assert(done.ok);assert.equal(done.language_count,1);
 const manifest=await cc.manifest("P259-L04");
 assert.equal(manifest.cc_files.length,1);
 assert.equal(manifest.cc_files[0].task_id,"P259-L04");
 assert.equal(manifest.cc_files[0].name,"en.transcript.txt");
 assert.equal(manifest.cc_files[0].storage,"google-sheet");
 const doc=await cc.transcript("P259-L04",first.job_id,"en");
 assert.equal(doc.content,"Fourth-lesson English CC part 1Fourth-lesson English CC part 2");
 await assert.rejects(()=>cc.transcript("P259-L03",first.job_id,"en"),
   /caption_job_not_verified_for_lesson/);
 await assert.rejects(()=>cc.part({job_id:first.job_id,language:"th",
   part_index:"0",part_count:"1",content:"late data"}),/caption_job_not_running/);
 assert.equal(tables["執行狀態"].at(-1)[2],"done");
 console.log("PASS: YouTube fourth-lesson CC only; true queue ACK; no audio fake; exact task/video ID; verified parts");
})().catch(e=>{console.error(e);process.exitCode=1});

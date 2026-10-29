"use strict";
const assert=require("node:assert/strict");
const {createChineseFinalStore}=require("../chinese-final-store");
const HEADS={
 "中文人工定稿備存":["task_id","revision","part_index","part_count","json_part","saved_at","sha256"],
 "中文人工定稿索引":["task_id","revision","segment_count","saved_at","storage","publisher"]
};
const store={};
const ensureTab=async(tab,header)=>{store[tab]??=[header];};
const get=async tab=>store[tab]||[];
const put=async(tab,range,rows,append)=>{
 assert.equal(append,true);await ensureTab(tab,HEADS[tab]);store[tab].push(...rows);
};
const original={
 segments:Array.from({length:67},(_,id)=>({
  id,start:id*30,end:(id+1)*30,
  text:"第259期第四堂 圓融的思路：面對不同意見時，以體諒與善意對待他人。"
 }))
};
const config={get,put,ensureTab,readOriginal:async task=>
 task==="P259-L04"?original:task==="P259-L03"?{
  segments:[{id:0,start:0,end:10,text:"第三堂點燃心中的明燈"}]
 }:null};
const editor=createChineseFinalStore(config);
(async()=>{
 const payload={
  task_id:"P259-L04",kind:"zh",
  segments_json:JSON.stringify(original.segments.map(x=>({...x,text:x.text+"（人工校訂）"})))
 };
 const r=await editor.save(payload);
 assert.equal(r.ok,true);
 assert.equal(r.sheet_finalized,true);
 assert.equal(r.drive_saved,false);
 assert.equal(r.segment_count,67);
 const stored=await editor.read("P259-L04");
 assert.equal(stored.manuscript.segments[0].text,payload.segments_json?JSON.parse(payload.segments_json)[0].text:"");
 assert.equal(stored.manuscript.segments.length,67);
 const count=store["中文人工定稿備存"].length;
 const repeat=await editor.save(payload);
 assert.equal(repeat.revision,r.revision);
 assert.equal(store["中文人工定稿備存"].length,count);
 await assert.rejects(
  ()=>editor.save({...payload,task_id:"P259-L03"}),
  /chinese_source_timeline_mismatch/
 );
 await assert.rejects(
  ()=>editor.save({...payload,task_id:"P259-L05"}),
  /chinese_source_not_found_for_lesson/
 );
 const bad=JSON.parse(payload.segments_json);bad[0].start=999;
 await assert.rejects(
  ()=>editor.save({...payload,segments_json:JSON.stringify(bad)}),
  /chinese_source_timeline_mismatch/
 );
 const row=store["中文人工定稿備存"][1];row[4]="tampered";
 await assert.rejects(()=>editor.read("P259-L04"),/sha_mismatch/);
 console.log("PASS: Chinese P259-L04 Final protected against cross-lesson sources, corruption and duplicate writes");
})().catch(err=>{console.error(err);process.exitCode=1});

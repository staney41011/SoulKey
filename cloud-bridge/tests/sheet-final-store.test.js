"use strict";
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const {createSheetFinalStore}=require("../sheet-final-store");
const {createEnglishFinalBackup}=require("../english-final-backup");
const tables={};
let writes=0;
const HEADER={
 "英文定稿備存":["task_id","backup_id","part_index","part_count","payload_json_part","saved_at","sha256"],
 "英文定稿索引":["task_id","backup_id","segment_count","finalized_at","storage","publisher"]
};
const ensureTab=async(tab)=>{tables[tab]??=[HEADER[tab]];};
const get=async(tab)=>tables[tab]||[];
const put=async(tab,_range,rows,append)=>{
 assert.equal(append,true);
 await ensureTab(tab);
 tables[tab].push(...rows);
 writes++;
};
(async()=>{
 const backup=createEnglishFinalBackup({ensureTab,get,put,now:()=>"2026-10-29T01:00:00.000Z"});
 const final=createSheetFinalStore({ensureTab,get,put,now:()=>"2026-10-29T01:00:01.000Z"});
 const segments=Array.from({length:449},(_,id)=>({
  id,start:id*4,end:(id+1)*4,text:"English paragraph "+id+"—"+"長文本 testing ".repeat(60)
 }));
 const payload={task_id:"P259-L01",kind:"en",
  segments_json:JSON.stringify(segments),
  terms_json:JSON.stringify([{zh:"修道",en:"Dao cultivation"}])};
 const saved=await backup.save(payload);
 assert.equal(saved.backup_saved,true);
 assert.equal(saved.ok,false,"backup alone is not a formal final");
 const r=await final.finalize("P259-L01",saved.backup_id,449);
 assert.equal(r.ok,true);assert.equal(r.sheet_finalized,true);
 assert.equal(r.drive_saved,false);assert.equal(r.pending_drive,true);
 const loaded=await final.read("P259-L01");
 assert.equal(loaded.manuscript.segments.length,449);
 assert.equal(loaded.manuscript.learned_terms[0].en,"Dao cultivation");
 assert.equal(loaded.manuscript.segments[400].text,segments[400].text);
 const count=writes;
 const again=await final.finalize("P259-L01",saved.backup_id,449);
 assert.equal(again.backup_id,saved.backup_id);
 assert.equal(writes,count,"no duplicate index on retries");
 assert.equal(await final.read("P258-L01"),null);
 const part=tables["英文定稿備存"][1];
 part[4]="tampered";
 await assert.rejects(()=>final.read("P259-L01"),/hash_mismatch|missing_chunks/);
 console.log("PASS: complete Sheet Final has 449 segments, readback SHA, idempotent index and corruption detection");
})().catch(e=>{console.error(e);process.exitCode=1});

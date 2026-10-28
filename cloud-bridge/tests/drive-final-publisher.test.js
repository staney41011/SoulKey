"use strict";
const assert=require("node:assert/strict");
const {createDriveFinalPublisher,outputs}=require("../drive-final-publisher");
const files=new Map();let creates=0,patches=0,appends=0,termWrites=0;
const api={request:async({method,url,data})=>{
 if(url.includes("?alt=media")){
  const id=url.match(/\/files\/([^?]+)/)?.[1];
  if(!files.has(id))throw Error("missing_file");
  return {data:files.get(id).value};
 }
 if(url.includes("/upload/drive/v3/files")){
  const parts=Buffer.from(data).toString("utf8").split("\r\n\r\n");
  const meta=JSON.parse(parts[1].split("\r\n--")[0]);
  const value=parts[2].slice(0,parts[2].lastIndexOf("\r\n--"));
  const id=method==="PATCH"?url.match(/\/files\/([^?]+)/)?.[1]:"mock_drive_id_000000000"+(++creates);
  if(method==="PATCH")patches++;
  files.set(id,{name:meta.name,value,description:meta.description});
  return {data:{id,name:meta.name}};
 }
 if(url.includes("/drive/v3/files?")){
  return {data:{files:[...files.entries()].map(([id,v])=>({
   id,name:v.name,description:v.description
  }))}};
 }
 throw Error("Unexpected URL "+url);
}};
let table=[["task_id"],["P259-L01"]],status=[["task_id","stage","status","run_id","progress","message","finished_at","updated_at"]];
const get=async(tab)=>tab==="任務佇列"?table:tab==="專有名詞庫"?[["中文原詞","類別","說明","English"]]:status;
const put=async(tab,range,values,append)=>{
 if(tab==="任務佇列"){
  if(range==="J2")table[1][9]=values[0][0];
  if(range==="S2:T2"){table[1][18]=values[0][0];table[1][19]=values[0][1];}
  return;
 }
 if(tab==="專有名詞庫"){termWrites++;return;}
 if(tab==="執行狀態"&&append){appends++;status.push(values[0]);}
};
const pub=createDriveFinalPublisher({
 authFactory:()=>api,resolveFolders:async()=>({translation:"mock_folder_000000000000"}),
 get,put
});
(async()=>{
 const segments=Array.from({length:449},(_,i)=>({
  id:i,start:i*4,end:i*4+4,text:"Edited English "+i
 }));
 const r=await pub.publish("P259-L01",{segments,learned_terms:[{zh:"修道",en:"Dao cultivation"}]});
 assert.equal(r.ok,true);assert.equal(r.drive_saved,true);
 assert.equal(r.terms_synced,1);
 assert.equal(termWrites,1);
 assert.equal(Object.keys(r.files).length,3);
 assert.equal(files.size,3);
 assert.equal(table[1][9],"完成");
 assert.equal(status[1][2],"done");
 assert.equal(creates,3);
 assert.equal(appends,1);
 const second=await pub.publish("P259-L01",{segments});
 assert.equal(second.ok,true);
 assert.equal(files.size,3);
 assert.equal(appends,1);
 assert.equal(patches,1,"timestamped JSON gets version-updated, not duplicated");
 const json=[...files.values()].find(x=>x.name==="en.final.json");
 assert.equal(JSON.parse(json.value).segments.length,449);
 const disabled=createDriveFinalPublisher({
  authFactory:()=>null,resolveFolders:async()=>{throw Error("unexpected");},get,put
 });
 assert.equal(disabled.isConfigured(),false);
 console.log("PASS: three Drive Final files, readback verification, stable IDs, and final status only after success");
})().catch(err=>{console.error(err);process.exitCode=1});

"use strict";
const assert=require("node:assert/strict");
const {createSheetsRequest,isSheetsReadQuotaError}=require("../sheets-request");

const quota=()=>Object.assign(new Error("Quota exceeded for Read requests per minute per user"),{
 response:{status:429,data:{error:{message:"Quota exceeded"}}}
});
const denied=()=>Object.assign(new Error("Forbidden"),{response:{status:403}});
async function run(){
 assert.equal(isSheetsReadQuotaError(quota()),true);
 assert.equal(isSheetsReadQuotaError(denied()),false);
 let attempts=0;
 const delays=[];
 const request=createSheetsRequest({
  send:async()=>{
   attempts++;
   if(attempts<=2)throw quota();
   return {data:{ok:true}};
  },
  wait:async ms=>{delays.push(ms);},
  random:()=>0,
  logger:{warn(){}}
 });
 const options={method:"GET",url:"https://sheets.googleapis.com/v4/spreadsheets/test/values/A1"};
 const [first,second]=await Promise.all([request(options),request(options)]);
 assert.deepEqual(first,{data:{ok:true}});
 assert.strictEqual(first,second);
 assert.equal(attempts,3,"two callers must share one read + quota retries");
 assert.deepEqual(delays,[1000,2000]);
 await request(options);
 assert.equal(attempts,4,"settled reads are not cached as stale data");
 let writes=0;
 const noWriteRetry=createSheetsRequest({
  send:async()=>{writes++;throw quota();},
  wait:()=>{throw Error("writes must never backoff/retry");},
  logger:{warn(){}}
 });
 await assert.rejects(noWriteRetry({method:"POST",url:"test"}),/Quota exceeded/);
 assert.equal(writes,1,"append may never be retried automatically");
 let reads=0;
 const noAuthRetry=createSheetsRequest({
  send:async()=>{reads++;throw denied();},
  wait:()=>{throw Error("403 without quota must not retry");},
  logger:{warn(){}}
 });
 await assert.rejects(noAuthRetry({method:"GET",url:"test"}),/Forbidden/);
 assert.equal(reads,1);
 console.log("PASS: read-only 429 exponential backoff, concurrent coalescing, no write retries");
}
run().catch(e=>{console.error(e);process.exitCode=1;});

// Central Sheets API read protection: coalesce concurrent identical reads and
// retry only quota-limited GETs. Never automatically retry writes/append calls.
"use strict";

function isSheetsReadQuotaError(error) {
  const status=Number(error?.response?.status || error?.status || 0);
  if(status!==429 && status!==403) return false;
  if(status===429) return true;
  const detail=JSON.stringify(error?.response?.data || {})+" "+String(error?.message||"");
  return /quota|read.requests|rate.limit|RESOURCE_EXHAUSTED/i.test(detail);
}

function createSheetsRequest({
  send,
  wait=ms=>new Promise(resolve=>setTimeout(resolve,ms)),
  random=Math.random,
  maxRetries=6,
  logger=console
}) {
  if(typeof send!=="function")throw Error("sheets_send_required");
  const activeReads=new Map();
  return function request(options) {
    const method=String(options?.method||"GET").toUpperCase();
    const key=String(options?.url||"");
    if(method==="GET" && activeReads.has(key))
      return activeReads.get(key);
    const execute=(async()=>{
      for(let attempt=0;;attempt++) {
        try {
          return await send(options);
        } catch(error) {
          if(method!=="GET" || !isSheetsReadQuotaError(error) ||
             attempt>=maxRetries) throw error;
          const delay=Math.min(32000,1000*2**attempt)+
            Math.floor(Math.max(0,Math.min(1,Number(random())||0))*300);
          logger.warn("Sheets read quota backoff",attempt+1,"of",maxRetries);
          await wait(delay);
        }
      }
    })();
    if(method!=="GET")return execute;
    activeReads.set(key,execute);
    // Clean up after both success and failure, without a detached rejection.
    void execute.then(
      ()=>{if(activeReads.get(key)===execute)activeReads.delete(key);},
      ()=>{if(activeReads.get(key)===execute)activeReads.delete(key);}
    );
    return execute;
  };
}
module.exports={createSheetsRequest,isSheetsReadQuotaError};

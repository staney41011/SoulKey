/* Route each operation to the service that actually implements it.
 * The existing Sheet remains authoritative; machine work stays on Kaggle.
 */
(function(root){
  "use strict";
  const legacy=new Set([
    "review_cache_status","review_cache_seed","review_cache_seed_en",
    "review_share_draft_save","review_finish",
    "period_reorder","task_reschedule","drive_names_migrate",
    "worker_setup","worker_secret_test","smoke"
  ]);
  function usesLegacy(fields){
    if(fields?.action==="run_stage")
      return fields.stage!=="cc" || fields.lang==="multi-audio";
    if(fields?.action==="review_en_draft_save"){
      // Full quick-editor snapshots use the original GitHub draft contract.
      // Sentence saves with conflict receipts belong to the central store.
      try{return !JSON.parse(fields.payload_json||"{}").save_request_id;}
      catch(_){return false;}
    }
    return legacy.has(String(fields?.action||""));
  }
  function endpoint(config,fields){
    const target=String(usesLegacy(fields)
      ? config.legacyKaggleBridgeEndpoint||config.bridgeEndpoint||""
      : config.bridgeEndpoint||"").trim();
    if(config.mode==="legacy-kaggle" &&
       !/^https:\/\/script\.google\.com\/macros\/s\/[^/]+\/exec$/.test(target))return "";
    return target;
  }
  function protocol(value){return value==="cloud-recovery"?9:Number(value)||0;}
  function statusTime(value){
    const text=String(value||"").trim();
    // The original Apps Script writes Asia/Taipei wall-clock timestamps.
    // Cloud Run returns those unchanged alongside ISO UTC worker timestamps.
    // Interpret the original format explicitly, independent of browser zone.
    return Date.parse(/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$/.test(text)
      ? text.replace(" ","T")+"+08:00" : text);
  }
  function dispatchReceipt(pending,status){
    if(!pending || !status || !status.run_id)return false;
    if(!["queued","running","done","needs_review","error"].includes(status.status))return false;
    const at=statusTime(status.updated_at||status.started_at||"");
    return String(status.run_id)!==String(pending.previousRunId||"") &&
      Number.isFinite(at) && at>=pending.submittedAt-2000;
  }
  const api={usesLegacy,endpoint,protocol,statusTime,dispatchReceipt};
  // Read-only legacy operations use google.script.run. Short shared keys must
  // never be placed in JSONP URLs. Keep one request in flight for correlation
  // with the original, unmodified Apps Script response contract.
  if(root){
    let frame=null,peer=null,active=null,timer=0;
    const queue=[];
    function fail(message){
      const job=active;active=null;peer=null;
      root.clearTimeout(timer);
      if(frame){frame.remove();frame=null;}
      if(job?.options.onError)job.options.onError(new Error(message));
      pump();
    }
    function pump(){
      if(active||!queue.length)return;
      active=queue.shift();
      timer=root.setTimeout(()=>fail("原服務讀取逾時，請稍後重試"),active.options.timeoutMs||90000);
      if(peer){send();return;}
      frame=root.document.createElement("iframe");
      frame.hidden=true;frame.title="SoulKey legacy read bridge";
      frame.src=active.endpoint+"?view=client";
      root.document.body.appendChild(frame);
    }
    function send(){
      peer.postMessage({source:"soulkey-studio",type:"bridge_request",
        request:{...active.fields,bridge_key:active.key}},"*");
    }
    root.addEventListener("message",event=>{
      if(!active || !/^https:\/\/(?:script\.google\.com|[a-z0-9-]+\.googleusercontent\.com)$/.test(event.origin||""))return;
      const data=event.data||{};
      if(data.source==="soulkey-bridge-client"&&data.type==="ready"){
        if(peer)return;
        peer=event.source;send();return;
      }
      if(event.source!==peer||data.source!=="soulkey-bridge")return;
      const job=active;active=null;root.clearTimeout(timer);
      if(job.options.onResult)job.options.onResult(data);
      // The main event handler also receives the original response.
      root.setTimeout(pump,0);
    });
    api.readLegacy=(config,key,fields,options={})=>{
      const url=endpoint(config,fields);
      if(!key||!/^https:\/\/script\.google\.com\/macros\/s\//.test(url))return false;
      queue.push({endpoint:url,key,fields,options});pump();return true;
    };
  }
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  if(root)root.SoulKeyBridgeRoutes=api;
})(typeof window!=="undefined"?window:null);

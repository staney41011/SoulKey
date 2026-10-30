// Archived only. Not part of the active Apps Script deployment.
function firebaseStatusMirror_(taskId,stage,status,progress,runId,inputRevision,outputRevision) {
  const props=PropertiesService.getScriptProperties();
  if(String(props.getProperty("FIREBASE_STATUS_MIRROR_ENABLED")||"")!=="true")
    return false;
  const configured=String(props.getProperty("FIREBASE_DATABASE_URL")||"").trim();
  const root=configured.endsWith("/")?configured.slice(0,-1):configured;
  if(!/^https:\/\/[a-z0-9-]+\.(?:firebaseio\.com|[a-z0-9-]+\.firebasedatabase\.app)$/.test(root))
    return false;
  const id=String(taskId||""),phase=String(stage||"");
  if(!/^P\d+-L\d{2}(?:-R\d+)?$/.test(id) ||
     !/^[a-zA-Z0-9:_-]{1,44}$/.test(phase))return false;
  const stamp=new Date().toISOString();
  const number=Number(progress);
  const record={
    task_id:id,stage:phase,
    status:String(status||"").slice(0,32),
    progress:Number.isFinite(number)?Math.min(100,Math.max(0,number)):0,
    run_id:String(runId||"").slice(0,100),
    input_revision:String(inputRevision||"").slice(0,100),
    output_revision:String(outputRevision||"").slice(0,100),
    updated_at:stamp,
    source:"apps-script-status-mirror-v1"
  };
  const url=root+"/soulkey/status_v1/"+encodeURIComponent(id)+"/"+
    encodeURIComponent(phase)+".json";
  try{
    const reply=UrlFetchApp.fetch(url,{
      method:"put",contentType:"application/json",muteHttpExceptions:true,
      headers:{"Authorization":"Bearer "+ScriptApp.getOAuthToken()},
      payload:JSON.stringify(record)
    });
    const code=reply.getResponseCode();
    if(code<200||code>=300){
      console.warn("FIREBASE_STATUS_MIRROR_FAILED",id,phase,code);
      return false;
    }
    return true;
  }catch(error){
    console.warn("FIREBASE_STATUS_MIRROR_UNAVAILABLE",id,phase,
      String(error&&error.name||"error"));
    return false;
  }
}


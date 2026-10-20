(function(root,factory){
  const api=factory(root?.SoulKeyTTSShare);
  if(typeof module==="object" && module.exports) module.exports=api;
  if(root) root.SoulKeyLanguageDelivery=api;
})(typeof window!=="undefined"?window:globalThis,function(TTS){
  "use strict";
  const invalid=["stale","error","queued","running","delayed","needs_review"];
  const standard=(payload,key)=>Array.isArray(payload?.groups)
    ? (payload.groups.find(group=>group?.key===key)?.files||[]) : [];
  function verifiedDrive(file){
    if(!file || !(Number(file.size)>0)) return "";
    const id=String(file.id||"");
    const url=String(file.url||"");
    if(!/^[\w-]{12,}$/.test(id)) return "";
    try{
      const parsed=new URL(url);
      if(parsed.protocol!=="https:" || !["drive.google.com","www.drive.google.com"].includes(parsed.hostname)) return "";
      if(!parsed.pathname.includes("/file/d/"+id) && parsed.searchParams.get("id")!==id) return "";
    }catch(_){return "";}
    return "https://drive.google.com/file/d/"+id+"/view";
  }
  function canonical(file){
    const named=String(file?.canonical_name||"").trim();
    if(named) return named;
    return String(file?.name||"").trim();
  }
  function textCode(file){
    const key=canonical(file);
    const match=/^([a-z]{2})\.(final\.)?txt$/i.exec(key);
    if(match) return {code:match[1].toLowerCase(),priority:match[2]?2:1};
    // Recognize only specifically marked final transcript names.
    if(file?.canonical_name) return null;
    const full=/_([^_]+)(人工定稿|翻譯稿)(?:純逐字稿|逐字稿)?\.txt$/u.exec(key);
    const names={"英文":"en","泰文":"th","西班牙文":"es","印尼文":"id","越南文":"vi","印地語":"hi","泰米爾文":"ta","日文":"ja","韓文":"ko","高棉文":"km","孟加拉文":"bn","尼泊爾文":"ne","寮文":"lo","緬甸文":"my","義大利文":"it","葡萄牙文":"pt"};
    return full && names[full[1]]?{code:names[full[1]],priority:1}:null;
  }
  function resolve(task,code,coursePayload,sharePayload){
    const groupsVerified=Boolean(coursePayload?.ok);
    const shareVerified=Boolean(sharePayload?.ok);
    const transcript=standard(coursePayload,"transcript");
    let foundDoc=null,score=0;
    transcript.forEach(file=>{
      const parsed=textCode(file);
      if(parsed?.code!==code) return;
      const url=verifiedDrive(file);
      if(url && parsed.priority>score){foundDoc={url,label:parsed.priority===2?"開啟定稿":"開啟文稿"};score=parsed.priority;}
    });
    const stages=task?.remoteStages||{};
    const per=String(stages["tts:"+code]?.status||"").toLowerCase();
    const aggregate=String(stages.tts?.status||"").toLowerCase();
    const invalidated=invalid.includes(per) ||
      ((aggregate==="stale"||aggregate==="error") && per!=="done");
    const candidates=[...standard(coursePayload,"audio"),...standard(sharePayload,"audio")];
    let formal=null,preview=null;
    candidates.forEach(file=>{
      const name=canonical(file);
      const previewCode=/^([a-z]{2})\.preview\.mp3$/i.exec(name);
      if(previewCode){
        if(previewCode[1].toLowerCase()!==code || file?.needs_timing_review!==true) return;
        const url=TTS?.canonicalDriveUrl ? TTS.canonicalDriveUrl(file) : verifiedDrive(file);
        if(url) preview={url,label:"開啟試聽 MP3"};
        return;
      }
      const parsed=TTS?.canonicalMp3Code?.(file) ||
        (/^([a-z]{2})\.mp3$/i.exec(name)?.[1]||"").toLowerCase();
      if(parsed!==code || file?.needs_timing_review) return;
      const url=TTS?.canonicalDriveUrl ? TTS.canonicalDriveUrl(file) : verifiedDrive(file);
      if(url) formal={url,label:"開啟正式 MP3"};
    });
    const reason=TTS?.reviewReason
      ? TTS.reviewReason(task,code)
      : "尚未完成配音品質及時長驗收";
    const doc=foundDoc
      ? {status:"ready",label:foundDoc.label,url:foundDoc.url}
      : {status:"pending",label:groupsVerified?"待產生":"尚未查詢",url:""};
    const voice=per==="needs_review"
      ? (preview
        ? {status:"review",label:preview.label,url:preview.url,reason}
        : {status:"pending",label:"待驗收（目前尚無可取得的試聽 MP3）",url:"",reason})
      : (formal&&!invalidated
        ? {status:"ready",label:formal.label,url:formal.url}
        : (preview
          ? {status:"review",label:preview.label,url:preview.url,reason}
          : {status:"pending",label:invalidated?"待驗收":(
              groupsVerified||shareVerified?"待產生":"尚未查詢"),url:"",
              ...(invalidated?{reason}:{})}));
    return {doc,audio:voice};
  }
  return {resolve,verifiedDrive,textCode};
});

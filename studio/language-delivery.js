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
    let audio=null,hasPreview=false;
    candidates.forEach(file=>{
      if(file?.needs_timing_review ||
         /\.preview\.mp3$/i.test(canonical(file)) ||
         /自然試聽版\.mp3$/i.test(String(file?.name||""))){
        const previewCode=/^([a-z]{2})\.preview\.mp3$/i.exec(canonical(file));
        const aliases={en:"英文",th:"泰文",es:"西班牙文",id:"印尼文",vi:"越南文",hi:"印地語",ta:"泰米爾文",ja:"日文",ko:"韓文",km:"高棉文",bn:"孟加拉文",ne:"尼泊爾文",lo:"寮文",my:"緬甸文",it:"義大利文",pt:"葡萄牙文"};
        if(previewCode?.[1]?.toLowerCase()===code ||
           String(file?.name||"").endsWith("_"+(aliases[code]||code)+"自然試聽版.mp3")) hasPreview=true;
        return;
      }
      const name=canonical(file);
      const parsed=TTS?.canonicalMp3Code?.(file) ||
        (/^([a-z]{2})\.mp3$/i.exec(name)?.[1]||"").toLowerCase();
      if(parsed!==code || invalidated) return;
      const url=TTS?.canonicalDriveUrl ? TTS.canonicalDriveUrl(file) : verifiedDrive(file);
      if(url) audio={url,label:"開啟 MP3"};
    });
    const doc=foundDoc
      ? {status:"ready",label:foundDoc.label,url:foundDoc.url}
      : {status:"pending",label:groupsVerified?"待產生":"尚未查詢",url:""};
    const voice=audio
      ? {status:"ready",label:audio.label,url:audio.url}
      : {status:"pending",label:invalidated||hasPreview||per==="needs_review"?"待驗收":
          (groupsVerified||shareVerified?"待產生":"尚未查詢"),url:""};
    return {doc,audio:voice};
  }
  return {resolve,verifiedDrive,textCode};
});

const cfg=window.SOULKEY_CONFIG||{};
const BRIDGE_ENDPOINT=String(cfg.bridgeEndpoint||"").trim();
const REVIEW_CACHE_BASE=String(
  cfg.reviewCacheBaseUrl||
  "https://raw.githubusercontent.com/staney41011/SoulKey/main/studio-review-cache"
).replace(/\/$/,"");
const RENDER_BATCH=80;

const params=new URLSearchParams(location.search);
const taskId=String(params.get("task")||"").trim();
const videoId=String(params.get("video")||"").trim();

let payload=null;
let segments=[];
let dirty=false;
let activeFilter="all";
let zhVisibleCount=RENDER_BATCH;
let enVisibleCount=RENDER_BATCH;
let player=null;
let playerReady=false;
let pendingSeek=null;
let revision=0;
let lastSavedRevision=0;
let saveInFlight=false;
let saveQueued=false;
let saveRevisionInFlight=0;
let autoSaveTimer=null;
let currentStep=1;
let finishQueued=false;

const $=id=>document.getElementById(id);
const esc=value=>String(value??"")
  .replace(/&/g,"&amp;")
  .replace(/</g,"&lt;")
  .replace(/>/g,"&gt;")
  .replace(/"/g,"&quot;")
  .replace(/'/g,"&#039;");

function setStatus(text,state=""){
  const el=$("save-status");
  if(!el) return;
  el.textContent=text;
  el.className="status-pill"+(state?" "+state:"");
}

function clock(seconds){
  const total=Math.max(0,Math.floor(Number(seconds)||0));
  const h=String(Math.floor(total/3600)).padStart(2,"0");
  const m=String(Math.floor((total%3600)/60)).padStart(2,"0");
  const s=String(total%60).padStart(2,"0");
  return h+":"+m+":"+s;
}

function repairTimings(items){
  const list=(items||[]).map((x,i)=>({
    ...x,
    id:Number(x.id!==undefined?x.id:i),
    confirmed:x.confirmed===true,
    source_en:String(x.source_en||""),
    en_text:String(x.en_text||x.source_en||""),
    en_confirmed:x.en_confirmed===true
  }));
  for(let i=0;i<list.length;i++){
    const cur=list[i],next=list[i+1];
    const start=Number(cur.start||0);
    let end=Number(cur.end||start);
    const nextStart=next?Number(next.start||0):0;
    if(next&&nextStart>start&&(end<start||((end-start)<2&&(nextStart-start)>5))){
      end=nextStart;
    }
    cur.start=start;
    cur.end=Math.max(start,end);
    cur.time=clock(start);
  }
  return list;
}

function maxAllowedStep(){
  if(finishQueued) return 4;
  if(payload?.en_finalized_at) return 3;
  if(payload?.zh_finalized_at) return 2;
  return 1;
}

function setStep(step,force=false){
  const max=maxAllowedStep();
  const target=force?Math.max(1,Math.min(4,Number(step)||1)):Math.max(1,Math.min(max,Number(step)||1));
  currentStep=target;

  document.querySelectorAll(".flow-step-panel").forEach((el,index)=>{
    el.classList.toggle("active",index===target-1);
  });
  document.querySelectorAll(".workflow-step").forEach((el,index)=>{
    const n=index+1;
    el.classList.toggle("active",n===target);
    el.classList.toggle("complete",n<max || (n===3&&finishQueued));
    el.disabled=n>max;
  });

  const guides={
    1:["STEP 1｜中文逐字稿","聽 YouTube 原音，核對 Taiwan Breeze 中文逐字稿與輕量 AI 校稿。按「確認此段」會立即同步 GitHub。"],
    2:["STEP 2｜中英對照","左側是中文 Final；右側直接使用 YouTube English auto-generated CC。只修英文即可，修改會自動同步 GitHub。"],
    3:["STEP 3｜選擇輸出","勾選需要的逐字稿與音檔。其他語言會從人工確認過的 English Final 直接翻譯。"],
    4:["STEP 4｜完成","工作已送到 Kaggle。翻譯完成後只替有勾音檔的語言執行 TTS。"]
  };
  $("guide-title").textContent=guides[target][0];
  $("guide-text").textContent=guides[target][1];
  window.scrollTo({top:0,behavior:"smooth"});
}

function filteredZhSegments(){
  if(activeFilter==="all") return segments;
  return segments.filter(x=>(x.flags||[]).includes(activeFilter));
}

function updateZhSummary(){
  const confirmed=segments.filter(x=>x.confirmed===true).length;
  const uncertain=segments.filter(x=>(x.flags||[]).includes("uncertain")).length;
  $("segment-summary").textContent=
    "已確認 "+confirmed+" / "+segments.length+" 段・待人工確認 "+uncertain+" 段";
}

function renderZh(){
  const list=$("zh-segment-list");
  const filtered=filteredZhSegments();
  const shown=filtered.slice(0,zhVisibleCount);
  updateZhSummary();

  if(!shown.length){
    list.innerHTML='<div class="card empty">沒有符合目前篩選條件的段落。</div>';
  }else{
    list.innerHTML=shown.map((s,i)=>`
      <article class="card segment-card ${(s.flags||[]).join(" ")} ${s.confirmed===true?"confirmed":""}" data-id="${esc(s.id??i)}" data-start="${esc(s.start)}">
        <div class="segment-meta">
          <b>#${esc((s.id??i)+1)}</b>
          <span>${esc(s.time||clock(s.start))}</span>
          <span class="segment-flags">${(s.flags||[]).map(x=>x==="uncertain"?"⚠ 待確認":"AI 已修改").join(" · ")}</span>
        </div>
        <div class="segment-grid">
          <div class="source">${esc(s.raw||"")}</div>
          <textarea class="final-text zh-final-text" ${payload?.zh_finalized_at?"disabled":""}>${esc(s.text||"")}</textarea>
        </div>
        <div class="segment-actions">
          <button class="play-segment" type="button">▶ 聽這段</button>
          <button class="confirm-segment ${s.confirmed===true?"confirmed":""}" type="button" ${payload?.zh_finalized_at?"disabled":""}>${s.confirmed===true?"✓ 已確認":"確認此段"}</button>
        </div>
      </article>
    `).join("");
  }

  const more=filtered.length-shown.length;
  $("load-more-zh").hidden=more<=0;
  if(more>0){
    $("load-more-zh").textContent="再顯示 "+Math.min(RENDER_BATCH,more)+" 段（尚有 "+more+" 段）";
  }
  bindZhRows();
}

function bindZhRows(){
  document.querySelectorAll("#zh-segment-list .segment-card").forEach(card=>{
    const id=Number(card.dataset.id);
    const textarea=card.querySelector(".zh-final-text");

    textarea?.addEventListener("input",()=>{
      const item=segments.find(x=>Number(x.id)===id);
      if(!item) return;
      item.text=textarea.value;
      item.confirmed=false;
      revision++;
      dirty=true;
      persistLocalDraft();
      setStatus("中文修改待同步","working");
      scheduleAutoSave();
    });

    card.querySelector(".play-segment")?.addEventListener("click",()=>{
      highlightPlaying(card);
      seekTo(Number(card.dataset.start||0),true);
    });

    card.querySelector(".confirm-segment")?.addEventListener("click",event=>{
      const item=segments.find(x=>Number(x.id)===id);
      if(!item) return;
      item.confirmed=item.confirmed!==true;
      revision++;
      dirty=true;
      persistLocalDraft();

      card.classList.toggle("confirmed",item.confirmed===true);
      event.currentTarget.classList.toggle("confirmed",item.confirmed===true);
      event.currentTarget.textContent=item.confirmed===true?"✓ 已確認":"確認此段";
      updateZhSummary();
      setStatus(item.confirmed?"同步確認狀態到 GitHub…":"同步取消確認到 GitHub…","working");
      requestDraftSave("confirm");
    });
  });
}

function updateEnglishSummary(){
  const available=segments.filter(x=>String(x.en_text||"").trim()).length;
  const changed=segments.filter(x=>String(x.en_text||"").trim()!==String(x.source_en||"").trim()).length;
  $("english-summary").textContent=
    "English CC 有內容 "+available+" / "+segments.length+" 段・人工修改 "+changed+" 段";

  const hasEnglishCc=payload?.english_cc_available===true ||
    segments.some(x=>String(x.source_en||"").trim());
  if(hasEnglishCc){
    $("cc-notice").className="cc-notice card ok";
    $("cc-notice").textContent=
      "已載入 YouTube English auto-generated CC（"+
      (payload.english_cc_language||"en")+
      "）。右側可直接修改成正式英文。";
  }else{
    $("cc-notice").className="cc-notice card warn";
    $("cc-notice").textContent=
      "這堂課沒有偵測到可用的 English auto-generated CC。可手動填英文，但快速流程建議先確認 YouTube 字幕來源。";
  }
}

function renderEn(){
  const list=$("en-segment-list");
  const shown=segments.slice(0,enVisibleCount);
  updateEnglishSummary();

  if(!shown.length){
    list.innerHTML='<div class="card empty">沒有可編輯的段落。</div>';
  }else{
    list.innerHTML=shown.map((s,i)=>`
      <article class="card segment-card en-card" data-id="${esc(s.id??i)}" data-start="${esc(s.start)}">
        <div class="segment-meta">
          <b>#${esc((s.id??i)+1)}</b>
          <span>${esc(s.time||clock(s.start))}</span>
          <span class="segment-flags">${s.source_en?"YouTube CC":"⚠ 無 English CC"}</span>
        </div>
        <div class="segment-grid">
          <div class="source final-zh-source">${esc(s.text||"")}</div>
          <textarea class="final-text en-final-text" ${payload?.en_finalized_at?"disabled":""} placeholder="English Final">${esc(s.en_text||"")}</textarea>
        </div>
        ${s.source_en?'<details class="cc-original"><summary>查看 English CC 原稿</summary><div>'+esc(s.source_en)+'</div></details>':""}
        <div class="segment-actions">
          <button class="play-segment" type="button">▶ 聽這段</button>
        </div>
      </article>
    `).join("");
  }

  const more=segments.length-shown.length;
  $("load-more-en").hidden=more<=0;
  if(more>0){
    $("load-more-en").textContent="再顯示 "+Math.min(RENDER_BATCH,more)+" 段（尚有 "+more+" 段）";
  }
  bindEnRows();
}

function bindEnRows(){
  document.querySelectorAll("#en-segment-list .segment-card").forEach(card=>{
    const id=Number(card.dataset.id);
    const textarea=card.querySelector(".en-final-text");

    textarea?.addEventListener("input",()=>{
      const item=segments.find(x=>Number(x.id)===id);
      if(!item) return;
      item.en_text=textarea.value;
      item.en_confirmed=false;
      revision++;
      dirty=true;
      persistLocalDraft();
      updateEnglishSummary();
      setStatus("英文修改待同步","working");
      scheduleAutoSave();
    });

    card.querySelector(".play-segment")?.addEventListener("click",()=>{
      highlightPlaying(card);
      seekTo(Number(card.dataset.start||0),true);
    });
  });
}

function highlightPlaying(card){
  document.querySelectorAll(".segment-card.playing").forEach(x=>x.classList.remove("playing"));
  card.classList.add("playing");
}

function persistLocalDraft(){
  localStorage.setItem("soulkey_shared_draft:"+taskId,JSON.stringify({
    task_id:taskId,
    saved_at:Date.now(),
    revision,
    zh_finalized_at:String(payload?.zh_finalized_at||""),
    en_finalized_at:String(payload?.en_finalized_at||""),
    segments
  }));
}

function scheduleAutoSave(){
  window.clearTimeout(autoSaveTimer);
  autoSaveTimer=window.setTimeout(()=>{
    if(dirty) requestDraftSave("auto");
  },2500);
}

function loadYouTubeApi(){
  if(window.YT&&window.YT.Player) return Promise.resolve();
  return new Promise((resolve,reject)=>{
    const prior=window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady=()=>{
      try{if(typeof prior==="function") prior();}catch(_){}
      resolve();
    };
    const script=document.createElement("script");
    script.src="https://www.youtube.com/iframe_api";
    script.async=true;
    script.onerror=()=>reject(new Error("YouTube API 載入失敗"));
    document.head.appendChild(script);
  });
}

async function mountPlayer(){
  if(!videoId){
    $("youtube-player").innerHTML='<div class="empty">這個分享連結沒有 YouTube 影片資訊。</div>';
    return;
  }
  try{
    await loadYouTubeApi();
    $("youtube-player").innerHTML='<div id="youtube-player-inner"></div>';
    player=new YT.Player("youtube-player-inner",{
      width:"100%",
      height:"100%",
      videoId,
      playerVars:{playsinline:1,rel:0,modestbranding:1},
      events:{
        onReady:()=>{
          playerReady=true;
          if(pendingSeek!==null){
            const sec=pendingSeek;
            pendingSeek=null;
            seekTo(sec,true);
          }
        }
      }
    });
  }catch(err){
    $("youtube-player").innerHTML='<div class="empty">'+esc(err.message||err)+'</div>';
  }
}

function seekTo(seconds,autoplay=true){
  const sec=Math.max(0,Number(seconds)||0);
  $("current-time").textContent=clock(sec);
  if(!playerReady||!player){
    pendingSeek=sec;
    return;
  }
  try{
    player.seekTo(sec,true);
    if(autoplay) player.playVideo();
  }catch(_){pendingSeek=sec}
}

function currentPayload(){
  return {
    version:5,
    task_id:taskId,
    zh_finalized_at:String(payload?.zh_finalized_at||""),
    en_finalized_at:String(payload?.en_finalized_at||""),
    english_cc_available:payload?.english_cc_available===true ||
      segments.some(x=>String(x.source_en||"").trim()),
    english_cc_language:String(payload?.english_cc_language||""),
    english_cc_source:String(payload?.english_cc_source||""),
    total_segments:segments.length,
    segments:segments.map(x=>({
      id:Number(x.id),
      start:Number(x.start||0),
      end:Number(x.end||0),
      time:String(x.time||clock(x.start)),
      raw:String(x.raw||""),
      text:String(x.text||""),
      flags:Array.isArray(x.flags)?x.flags:[],
      confirmed:x.confirmed===true,
      source_en:String(x.source_en||""),
      en_text:String(x.en_text||x.source_en||""),
      en_confirmed:x.en_confirmed===true
    }))
  };
}

function submit(fields){
  if(!BRIDGE_ENDPOINT){
    setStatus("後端連線不存在","error");
    return false;
  }
  const form=document.createElement("form");
  form.method="POST";
  form.action=BRIDGE_ENDPOINT;
  form.target="soulkey-share-target";
  form.style.display="none";
  for(const [name,value] of Object.entries(fields)){
    const input=document.createElement("input");
    input.type="hidden";
    input.name=name;
    input.value=String(value??"");
    form.appendChild(input);
  }
  document.body.appendChild(form);
  form.submit();
  setTimeout(()=>form.remove(),2000);
  return true;
}

function requestDraftSave(reason="manual"){
  window.clearTimeout(autoSaveTimer);
  if(saveInFlight){
    saveQueued=true;
    setStatus("GitHub 同步中・最新修改已排隊","working");
    return;
  }

  saveInFlight=true;
  saveQueued=false;
  saveRevisionInFlight=revision;
  setStatus(
    reason==="confirm"?"同步確認狀態到 GitHub…":
    reason==="auto"?"自動同步到 GitHub…":"儲存進度到 GitHub…",
    "working"
  );
  $("save-draft").disabled=true;

  const sent=submit({
    action:"review_share_draft_save",
    task_id:taskId,
    payload_json:JSON.stringify(currentPayload())
  });

  if(!sent){
    saveInFlight=false;
    $("save-draft").disabled=false;
  }
}

function finalizeZh(){
  const unconfirmed=segments.filter(x=>x.confirmed!==true).length;
  const extra=unconfirmed?"\n\n目前仍有 "+unconfirmed+" 段沒有按「確認此段」。仍要定稿嗎？":"";
  if(!confirm("確定完成中文逐字稿人工定稿？"+extra)) return;

  const p=currentPayload();
  setStatus("寫入中文 Final…","working");
  $("finalize-zh").disabled=true;
  submit({
    action:"review_share_finalize",
    task_id:taskId,
    payload_json:JSON.stringify(p),
    segments_json:JSON.stringify(p.segments.map(x=>({
      id:x.id,start:x.start,end:x.end,text:x.text
    })))
  });
}

function finalizeEnglish(){
  const missing=segments.filter(x=>!String(x.en_text||"").trim());
  if(missing.length){
    alert("還有 "+missing.length+" 段英文是空白，請補完後再定稿。");
    return;
  }
  if(!confirm("確定完成 English Final？\n\n之後其他語言會直接以這份英文定稿翻譯。")) return;

  const p=currentPayload();
  setStatus("寫入 English Final…","working");
  $("finalize-en").disabled=true;
  submit({
    action:"review_share_finalize_en",
    task_id:taskId,
    payload_json:JSON.stringify(p),
    segments_json:JSON.stringify(p.segments.map(x=>({
      id:x.id,start:x.start,end:x.end,text:x.en_text
    })))
  });
}

const LANG_NAMES={
  en:"English",
  th:"ภาษาไทย",
  es:"Español",
  id:"Bahasa Indonesia",
  vi:"Tiếng Việt",
  sd:"سنڌي",
  ta:"தமிழ்"
};

function collectOutputPlan(){
  return [...document.querySelectorAll(".output-row")].map(row=>{
    const code=row.dataset.outputLang;
    const transcript=!!row.querySelector("[data-output-transcript]")?.checked;
    const audio=!!row.querySelector("[data-output-audio]")?.checked;
    return {
      language_code:code,
      language_name:LANG_NAMES[code]||code,
      transcript_enabled:code==="en"?true:(transcript||audio),
      transcript_source:code==="en"?"human":"ai",
      audio_enabled:audio,
      audio_source:"tts"
    };
  });
}

function updateOutputSummary(){
  const plan=collectOutputPlan();
  const transcript=plan.filter(x=>x.transcript_enabled).map(x=>x.language_code);
  const audio=plan.filter(x=>x.audio_enabled).map(x=>x.language_code);
  $("output-summary").textContent=
    "逐字稿："+transcript.join(", ")+"；音檔："+(audio.join(", ")||"無");
}

function finishWorkflow(){
  if(!payload?.en_finalized_at){
    alert("請先完成 English Final。");
    return;
  }
  const plan=collectOutputPlan();
  const extra=plan.filter(x=>x.language_code!=="en"&&(x.transcript_enabled||x.audio_enabled));
  const audio=plan.filter(x=>x.audio_enabled);

  const msg=
    "確定開始最終輸出？\n\n"+
    "額外翻譯："+(extra.map(x=>x.language_code).join(", ")||"無")+"\n"+
    "音檔："+(audio.map(x=>x.language_code).join(", ")||"無");
  if(!confirm(msg)) return;

  $("finish-workflow").disabled=true;
  setStatus("送出最終輸出工作…","working");
  submit({
    action:"review_finish",
    task_id:taskId,
    plan_json:JSON.stringify(plan)
  });
}

window.addEventListener("message",event=>{
  const data=event.data||{};
  if(data.source!=="soulkey-bridge") return;

  if(data.type==="review_share_draft_saved"){
    saveInFlight=false;
    $("save-draft").disabled=false;
    if(data.ok){
      lastSavedRevision=Math.max(lastSavedRevision,saveRevisionInFlight);
      dirty=revision>lastSavedRevision;
      setStatus(
        saveQueued?"前一批已同步・繼續同步最新修改…":"已同步到 GitHub",
        saveQueued?"working":"ok"
      );
      if(saveQueued){
        saveQueued=false;
        window.setTimeout(()=>requestDraftSave("queued"),0);
      }
    }else{
      dirty=true;
      setStatus(data.message||data.error||"GitHub 同步失敗","error");
    }
  }

  if(data.type==="review_share_finalized"){
    if(data.ok){
      payload.zh_finalized_at=String(data.finalized_at||new Date().toISOString());
      payload.en_finalized_at="";
      dirty=false;
      persistLocalDraft();
      setStatus("中文定稿完成","ok");
      $("finalize-zh").disabled=true;
      renderZh();
      renderEn();
      setStep(2);
    }else{
      $("finalize-zh").disabled=false;
      setStatus(data.message||data.error||"中文定稿失敗","error");
    }
  }

  if(data.type==="review_share_en_finalized"){
    if(data.ok){
      payload.en_finalized_at=String(data.finalized_at||new Date().toISOString());
      dirty=false;
      persistLocalDraft();
      setStatus("英文定稿完成","ok");
      $("finalize-en").disabled=true;
      renderEn();
      $("finish-workflow").disabled=false;
      setStep(3);
    }else{
      $("finalize-en").disabled=false;
      setStatus(data.message||data.error||"英文定稿失敗","error");
    }
  }

  if(data.type==="review_finish_queued"){
    $("finish-workflow").disabled=false;
    if(data.ok){
      finishQueued=true;
      localStorage.setItem("soulkey_finish:"+taskId,JSON.stringify({
        queued_at:Date.now(),
        translate_langs:data.translate_langs||[],
        audio_langs:data.audio_langs||[],
        message:data.message||""
      }));
      $("done-message").textContent=data.message||"工作已送出。";
      $("done-detail").textContent=
        "翻譯："+((data.translate_langs||[]).join(", ")||"無")+
        "｜音檔："+((data.audio_langs||[]).join(", ")||"無");
      setStatus("最終工作已送出","ok");
      setStep(4,true);
    }else{
      setStatus(data.message||data.error||"最終工作送出失敗","error");
    }
  }
});

function restoreLocalIfNewer(){
  const localRaw=localStorage.getItem("soulkey_shared_draft:"+taskId);
  if(!localRaw) return;
  try{
    const local=JSON.parse(localRaw);
    const remoteSavedAt=Date.parse(String(payload.draft_saved_at||payload.generated_at||""))||0;
    const localSavedAt=Number(local.saved_at||0);
    if(
      localSavedAt>remoteSavedAt &&
      Array.isArray(local.segments) &&
      local.segments.length===segments.length
    ){
      const byId=new Map(local.segments.map(x=>[Number(x.id),x]));
      segments=segments.map(x=>{
        const d=byId.get(Number(x.id));
        return d?{
          ...x,
          text:String(d.text??x.text),
          confirmed:d.confirmed===true,
          source_en:String(d.source_en??x.source_en??""),
          en_text:String(d.en_text??x.en_text??x.source_en??""),
          en_confirmed:d.en_confirmed===true
        }:x;
      });
      if(local.zh_finalized_at) payload.zh_finalized_at=String(local.zh_finalized_at);
      if(local.en_finalized_at) payload.en_finalized_at=String(local.en_finalized_at);
      revision=Number(local.revision||1);
      lastSavedRevision=0;
      dirty=true;
      setStatus("已恢復此裝置較新的修改","working");
    }
  }catch(_){}
}

async function loadReview(){
  $("task-id").textContent=taskId||"無效課程";
  if(!/^P\d+-L\d+$/i.test(taskId)){
    setStatus("課程代號錯誤","error");
    return;
  }

  try{
    const url=REVIEW_CACHE_BASE+"/"+encodeURIComponent(taskId)+"/zh.json?_="+Date.now();
    const response=await fetch(url,{cache:"no-store",headers:{"Accept":"application/json"}});
    if(!response.ok) throw new Error("逐字稿讀取失敗 HTTP "+response.status);

    payload=await response.json();
    payload.zh_finalized_at=String(payload.zh_finalized_at||payload.finalized_at||"");
    payload.en_finalized_at=String(payload.en_finalized_at||"");
    segments=repairTimings(payload.segments||[]);
    restoreLocalIfNewer();

    renderZh();
    renderEn();
    $("save-draft").disabled=false;
    $("finalize-zh").disabled=!!payload.zh_finalized_at;
    $("finalize-en").disabled=!payload.zh_finalized_at||!!payload.en_finalized_at;
    $("finish-workflow").disabled=!payload.en_finalized_at;

    const finishRaw=localStorage.getItem("soulkey_finish:"+taskId);
    if(finishRaw){
      try{
        const info=JSON.parse(finishRaw);
        if(Date.now()-Number(info.queued_at||0)<24*60*60*1000){
          finishQueued=true;
          $("done-message").textContent=info.message||"工作已送出。";
          $("done-detail").textContent=
            "翻譯："+((info.translate_langs||[]).join(", ")||"無")+
            "｜音檔："+((info.audio_langs||[]).join(", ")||"無");
        }
      }catch(_){}
    }

    if(finishQueued) setStep(4,true);
    else if(payload.en_finalized_at) setStep(3);
    else if(payload.zh_finalized_at) setStep(2);
    else setStep(1);

    if(!dirty) setStatus("已載入最新工作稿","ok");
  }catch(err){
    setStatus(err.message||String(err),"error");
    $("zh-segment-list").innerHTML='<div class="card empty">'+esc(err.message||err)+'</div>';
  }
}

document.querySelectorAll("[data-filter]").forEach(btn=>{
  btn.addEventListener("click",()=>{
    document.querySelectorAll("[data-filter]").forEach(x=>x.classList.toggle("active",x===btn));
    activeFilter=btn.dataset.filter||"all";
    zhVisibleCount=RENDER_BATCH;
    renderZh();
  });
});

document.querySelectorAll("[data-go-step]").forEach(btn=>{
  btn.addEventListener("click",()=>setStep(Number(btn.dataset.goStep||1)));
});

document.querySelectorAll(".output-row").forEach(row=>{
  const transcript=row.querySelector("[data-output-transcript]");
  const audio=row.querySelector("[data-output-audio]");
  audio?.addEventListener("change",()=>{
    if(audio.checked&&transcript&&!transcript.checked){
      transcript.checked=true;
    }
    updateOutputSummary();
  });
  transcript?.addEventListener("change",updateOutputSummary);
});

$("load-more-zh").addEventListener("click",()=>{
  zhVisibleCount+=RENDER_BATCH;
  renderZh();
});
$("load-more-en").addEventListener("click",()=>{
  enVisibleCount+=RENDER_BATCH;
  renderEn();
});
$("save-draft").addEventListener("click",()=>requestDraftSave("manual"));
$("finalize-zh").addEventListener("click",finalizeZh);
$("finalize-en").addEventListener("click",finalizeEnglish);
$("finish-workflow").addEventListener("click",finishWorkflow);
$("back-to-output").addEventListener("click",()=>setStep(3,true));
$("back-5").addEventListener("click",()=>{
  if(playerReady&&player) seekTo(Math.max(0,Number(player.getCurrentTime()||0)-5),true);
});
$("forward-5").addEventListener("click",()=>{
  if(playerReady&&player) seekTo(Number(player.getCurrentTime()||0)+5,true);
});

window.addEventListener("beforeunload",event=>{
  if(dirty){
    event.preventDefault();
    event.returnValue="";
  }
});

updateOutputSummary();
mountPlayer();
loadReview();

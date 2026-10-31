const cfg=window.SOULKEY_CONFIG||{};
const BRIDGE_ENDPOINT=String(cfg.bridgeEndpoint||"").trim();
const BRIDGE_SESSION_KEY="soulkey_bridge_key_session_v1";
const REVIEW_CACHE_BASE=String(
  cfg.reviewCacheBaseUrl||
  "https://raw.githubusercontent.com/staney41011/SoulKey/main/studio-review-cache"
).replace(/\/$/,"");
const RENDER_BATCH=80;
const REQUIRED_BRIDGE_PROTOCOL=9;
let bridgeProtocolVersion=0;

const params=new URLSearchParams(location.search);
const taskId=String(params.get("task")||"").trim();
const videoId=String(params.get("video")||"").trim();
const requestedStep=String(params.get("step")||"").trim().toLowerCase();
const requestedStepNumber={
  zh:1,
  en:2,
  output:3,
  done:4
}[requestedStep]||0;

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
let finishPending=null;
let finishTarget="";
let driveFallbackZh=[];
let driveFallbackTotal=0;
let driveFallbackFinalizedAt="";
let driveFallbackReviewRevision="";
let driveFallbackFinalSource=false;
let englishBaseRequests={};
let legacyDraftBatchRequests=0;
let englishAligned=null; // separate English sentence-paired draft
let englishDriveLoaded=false;

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
    3:["STEP 3｜選擇語言","勾選需要的語言，每種語言都會同時生成文稿與自然語音音檔。"],
    4:["STEP 4｜完成","工作已送到 Kaggle，會為所選語言產生文稿與音檔。"]
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

function mergeEnglishTextParts(parts){
  const tokens=[];
  for(const raw of parts||[]){
    const text=String(raw||"").replace(/\s+/g," ").trim();
    if(!text) continue;
    const next=text.split(" ").filter(Boolean);
    if(!next.length) continue;

    let overlap=0;
    const max=Math.min(tokens.length,next.length,18);
    for(let size=max;size>0;size--){
      const left=tokens.slice(tokens.length-size).join(" ").toLowerCase();
      const right=next.slice(0,size).join(" ").toLowerCase();
      if(left===right){
        overlap=size;
        break;
      }
    }
    tokens.push(...next.slice(overlap));
  }
  return tokens.join(" ").replace(/\s+([,.;:!?])/g,"$1").trim();
}

function englishTokenKey(token){
  return String(token||"")
    .toLowerCase()
    .replace(/^[^a-z0-9]+|[^a-z0-9]+$/g,"");
}

function englishLeadingOverlapCount(previousText,nextText){
  const previous=String(previousText||"").replace(/\s+/g," ").trim().split(" ").filter(Boolean);
  const next=String(nextText||"").replace(/\s+/g," ").trim().split(" ").filter(Boolean);
  const max=Math.min(previous.length,next.length,40);

  for(let size=max;size>=3;size--){
    const left=previous.slice(previous.length-size).map(englishTokenKey);
    const right=next.slice(0,size).map(englishTokenKey);
    if(left.some(x=>!x) || right.some(x=>!x)) continue;
    const phrase=left.join(" ");
    if(phrase.length<12) continue;
    if(phrase===right.join(" ")) return size;
  }
  return 0;
}

function trimLeadingEnglishOverlap(previousText,nextText){
  const text=String(nextText||"").replace(/\s+/g," ").trim();
  if(!text) return "";
  const tokens=text.split(" ").filter(Boolean);
  const overlap=englishLeadingOverlapCount(previousText,text);
  return overlap ? tokens.slice(overlap).join(" ").trim() : text;
}

function dedupeEnglishRows(rows,textGetter){
  let history="";
  let lastEnd=null;
  return (rows||[]).map((item,index)=>{
    const start=Number(item.start||0);
    const end=Number(item.end||start);
    const raw=String(textGetter(item,index)||"").replace(/\s+/g," ").trim();
    const closeEnough=lastEnd===null || start-lastEnd<=3.5;
    const cleaned=closeEnough ? trimLeadingEnglishOverlap(history,raw) : raw;
    if(cleaned) history=mergeEnglishTextParts([history,cleaned]);
    else if(raw && !history) history=raw;
    lastEnd=end;
    return cleaned;
  });
}

function englishSentenceEnded(text){
  return /[.!?][\"'’”\)\]]*$/.test(String(text||"").trim());
}

function englishGroups(){
  if(Array.isArray(englishAligned) && englishAligned.length){
    return englishAligned.map((row,index)=>({
      ...row,
      ids:Array.isArray(row.zh_ids)&&row.zh_ids.length
        ? row.zh_ids.map(Number) : [Number(row.id??index)]
    }));
  }
  const baseRows=segments||[];
  const sourceCleaned=dedupeEnglishRows(baseRows,item=>item.source_en||"");
  const editedCleaned=dedupeEnglishRows(baseRows,item=>item.en_text||item.source_en||"");
  const rows=baseRows.map((item,index)=>({
    ...item,
    __sourceCleaned:sourceCleaned[index]||"",
    __editedCleaned:editedCleaned[index]||""
  }));
  const groups=[];
  let current=null;

  const flush=()=>{
    if(!current) return;
    current.source_en=mergeEnglishTextParts(current.sourceParts);
    current.en_text=mergeEnglishTextParts(current.enParts);
    current.text=current.zhParts.join("");
    delete current.sourceParts;
    delete current.enParts;
    delete current.zhParts;
    groups.push(current);
    current=null;
  };

  rows.forEach((item,index)=>{
    const source=String(item.__sourceCleaned||"").replace(/\s+/g," ").trim();
    const edited=String(item.__editedCleaned||source).replace(/\s+/g," ").trim();
    const start=Number(item.start||0);
    const end=Number(item.end||start);

    if(!current){
      current={
        id:Number(item.id??index),
        ids:[Number(item.id??index)],
        start,
        end,
        time:String(item.time||clock(start)),
        sourceParts:[source],
        enParts:[edited],
        zhParts:[String(item.text||"")]
      };
    }else{
      current.ids.push(Number(item.id??index));
      current.end=Math.max(current.end,end);
      current.sourceParts.push(source);
      current.enParts.push(edited);
      current.zhParts.push(String(item.text||""));
    }

    const sentence=mergeEnglishTextParts(current.sourceParts.length
      ? current.sourceParts
      : current.enParts);
    const next=rows[index+1];
    const nextGap=next ? Number(next.start||0)-current.end : Infinity;
    const duration=current.end-current.start;
    const shouldBreak=
      englishSentenceEnded(sentence) ||
      sentence.length>=900 ||
      duration>=60 ||
      nextGap>2.2 ||
      !next;

    if(shouldBreak) flush();
  });

  flush();
  return groups;
}

function writeEnglishGroup(group,text){
  if(Array.isArray(englishAligned)&&englishAligned.length){
    const row=englishAligned.find(x=>Number(x.id)===Number(group?.id));
    if(row){row.en_text=String(text||"").trim();row.en_confirmed=false;}
    return;
  }
  const ids=Array.isArray(group?.ids)?group.ids:[group?.id];
  const normalized=String(text||"").trim();
  ids.forEach(id=>{
    const item=segments.find(x=>Number(x.id)===Number(id));
    if(!item) return;
    // Keep the same edited sentence on every source fragment in the group.
    // mergeEnglishTextParts() collapses the repeated full sentence back to
    // one review sentence, while autosave/reload no longer resurrects the
    // original fragmented CC text.
    item.en_text=normalized;
    item.en_confirmed=false;
  });
}

function updateEnglishSummary(){
  const groups=englishGroups();
  const available=groups.filter(x=>String(x.en_text||"").trim()).length;
  const changed=groups.filter(x=>String(x.en_text||"").trim()!==String(x.source_en||"").trim()).length;
  $("english-summary").textContent=
    (payload?.en_finalized_at?"英文定稿 ":"English CC ")+available+" / "+groups.length+" 句・人工修改 "+changed+" 句";

  if(payload?.en_finalized_at){
    $("cc-notice").className="cc-notice card ok";
    $("cc-notice").textContent="已載入既有英文人工定稿，可直接選擇輸出語言。";
    return;
  }

  const hasEnglishCc=payload?.english_cc_available===true ||
    groups.some(x=>String(x.source_en||"").trim());
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
  const groups=englishGroups();
  const shown=groups.slice(0,enVisibleCount);
  updateEnglishSummary();

  if(!shown.length){
    list.innerHTML='<div class="card empty">沒有可編輯的英文句子。</div>';
  }else{
    list.innerHTML=shown.map((s,i)=>`
      <article class="card segment-card en-card" data-id="${esc(s.id??i)}" data-ids="${esc(s.ids.join(","))}" data-start="${esc(s.start)}" data-end="${esc(s.end)}">
        <div class="segment-meta">
          <b>句 ${esc(i+1)}</b>
          <span>${esc(s.time||clock(s.start))}</span>
          <span class="segment-flags">${s.source_en?"YouTube CC":"⚠ 無 English CC"}${s.ids.length>1?"・合併 "+s.ids.length+" 個原始片段":""}</span>
        </div>
        <div class="segment-grid">
          <div class="source final-zh-source">${esc(s.text||"")}</div>
          <textarea class="final-text en-final-text" ${payload?.en_finalized_at?"disabled":""} placeholder="English Final">${esc(s.en_text||"")}</textarea>
        </div>
        ${s.source_en?'<details class="cc-original"><summary>查看 English CC 原稿</summary><div>'+esc(s.source_en)+'</div></details>':""}
        <div class="segment-actions">
          <button class="play-segment" type="button">▶ 聽這句</button>
        </div>
      </article>
    `).join("");
  }

  const more=groups.length-shown.length;
  $("load-more-en").hidden=more<=0;
  if(more>0){
    $("load-more-en").textContent="再顯示 "+Math.min(RENDER_BATCH,more)+" 句（尚有 "+more+" 句）";
  }
  bindEnRows();
}

function bindEnRows(){
  document.querySelectorAll("#en-segment-list .segment-card").forEach(card=>{
    const ids=String(card.dataset.ids||card.dataset.id||"")
      .split(",").map(Number).filter(Number.isFinite);
    const group={
      id:Number(card.dataset.id),
      ids,
      start:Number(card.dataset.start||0),
      end:Number(card.dataset.end||0)
    };
    const textarea=card.querySelector(".en-final-text");

    textarea?.addEventListener("input",()=>{
      writeEnglishGroup(group,textarea.value);
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
    segments,
    english_aligned:englishAligned
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

function bridgeKeyValue(){
  try{
    return String(sessionStorage.getItem(BRIDGE_SESSION_KEY)||"").trim();
  }catch(_){
    return "";
  }
}

function jsonpBridgeRequest(fields){
  const key=bridgeKeyValue();
  if(!BRIDGE_ENDPOINT || !key) return false;
  if(/^https:\/\/script\.google\.com\//.test(BRIDGE_ENDPOINT) ||
     window.SoulKeyBridgeRoutes.usesLegacy(fields)){
    return window.SoulKeyBridgeRoutes.readLegacy(cfg,key,fields,{
      onError:error=>setStatus(error.message,"error")
    });
  }
  if(!/^https:\/\/script\.google\.com\//.test(BRIDGE_ENDPOINT)){
    fetch(BRIDGE_ENDPOINT,{
      method:"POST",mode:"cors",cache:"no-store",
      headers:{"Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"},
      body:new URLSearchParams({...fields,bridge_key:key})
    }).then(response=>response.json()).then(data=>{
      window.dispatchEvent(new MessageEvent("message",{data}));
    }).catch(()=>setStatus("控制中心讀取失敗，編輯內容仍保留在此裝置","error"));
    return true;
  }

  const callbackName="__soulkey_review_jsonp_"+Date.now()+"_"+Math.random().toString(36).slice(2);
  const script=document.createElement("script");
  const params=new URLSearchParams({
    ...Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,String(v??"")])),
    bridge_key:key,
    callback:callbackName,
    _t:String(Date.now())
  });

  const cleanup=()=>{
    try{delete window[callbackName];}catch(_){}
    script.remove();
  };

  window[callbackName]=(data)=>{
    cleanup();
    window.dispatchEvent(new MessageEvent("message",{data}));
  };
  script.onerror=()=>{
    cleanup();
    setStatus("Google Drive 備援讀取失敗","error");
  };

  const sep=BRIDGE_ENDPOINT.includes("?")?"&":"?";
  script.src=BRIDGE_ENDPOINT+sep+params.toString();
  document.head.appendChild(script);
  return true;
}

function requestDriveReview(kind,chunkIndex=0){
  return jsonpBridgeRequest({
    action:"review_load",
    task_id:taskId,
    kind,
    chunk_index:chunkIndex
  });
}

function applyReviewPayload(loaded){
  payload=loaded||{};
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

  if(requestedStepNumber){
    setStep(requestedStepNumber);
  }

  if(!dirty) setStatus("已載入最新工作稿","ok");
}

function submit(fields){
  if(!bridgeKeyValue()){
    setStatus("請先回工作台輸入原本的 6 碼，再開啟校稿頁","error");
    return false;
  }
  if(!BRIDGE_ENDPOINT){
    setStatus("後端連線不存在","error");
    return false;
  }
  const mutatingActions=new Set([
    "review_share_draft_save",
    "review_share_finalize",
    "review_share_finalize_en",
    "review_finish"
  ]);
  if(mutatingActions.has(String(fields?.action||""))){
    if(bridgeProtocolVersion<=0){
      setStatus("正在確認 Apps Script 控制中心版本，請稍候再送出。","working");
      return false;
    }
    if(bridgeProtocolVersion<REQUIRED_BRIDGE_PROTOCOL){
      setStatus(
        "Apps Script 控制中心版本過舊；請先回 Studio 重新部署 Code.gs。",
        "error"
      );
      return false;
    }
  }
  // Finalize into the new authoritative central store. Keep the old editor's
  // response names so the review flow advances only after verified readback.
  const finalTypes={review_share_finalize:"zh",review_share_finalize_en:"en"};
  const finalKind=finalTypes[fields.action];
  const outgoing=finalKind && !/^https:\/\/script\.google\.com\//.test(BRIDGE_ENDPOINT) ? {...fields,action:"review_save",kind:finalKind,
    source_video_id:videoId} : fields;
  const endpoint=window.SoulKeyBridgeRoutes.endpoint(cfg,outgoing);
  if(!endpoint){setStatus("原有服務連線尚未設定","error");return false;}
  if(!/^https:\/\/script\.google\.com\//.test(endpoint)){
    fetch(endpoint,{
      method:"POST",mode:"cors",cache:"no-store",
      headers:{"Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"},
      body:new URLSearchParams({...outgoing,bridge_key:bridgeKeyValue()})
    }).then(response=>response.json()).then(result=>{
      const data=finalKind ? {...result,type:finalKind==="zh"
        ?"review_share_finalized":"review_share_en_finalized"} : result;
      window.dispatchEvent(new MessageEvent("message",{data}));
    }).catch(()=>{
      if(finalKind)$(finalKind==="zh"?"finalize-zh":"finalize-en").disabled=false;
      setStatus("儲存未確認，內容仍保留在此裝置，請重試","error");
    });
    return true;
  }
  const target="soulkey-share-"+Date.now()+"-"+Math.random().toString(36).slice(2);
  const frame=document.createElement("iframe");
  frame.name=target;
  frame.style.display="none";
  frame.setAttribute("aria-hidden","true");

  const form=document.createElement("form");
  form.method="POST";
  form.action=endpoint;
  form.target=["run_stage","review_finish"].includes(fields.action) && finishTarget ? finishTarget : target;
  form.style.display="none";
  const authenticatedFields={
    ...outgoing,
    bridge_key:bridgeKeyValue()
  };
  for(const [name,value] of Object.entries(authenticatedFields)){
    const input=document.createElement("input");
    input.type="hidden";
    input.name=name;
    input.value=String(value??"");
    form.appendChild(input);
  }
  document.body.appendChild(frame);
  document.body.appendChild(form);
  form.submit();
  setTimeout(()=>{
    form.remove();
    frame.remove();
  },180000);
  return true;
}

async function centralReviewRequest(fields){
  if(/^https:\/\/script\.google\.com\//.test(BRIDGE_ENDPOINT)){
    const expected={review_en_draft_save:"english_review_draft_saved",
      language_plan_save:"language_plan_saved"}[fields.action];
    if(!expected)return new Promise((resolve,reject)=>{
      if(!window.SoulKeyBridgeRoutes.readLegacy(cfg,bridgeKeyValue(),fields,
        {onResult:resolve,onError:reject}))reject(new Error("原服務尚未連線"));
    });
    return new Promise((resolve,reject)=>{
      const requestId=fields.action==="review_en_draft_save"
        ? String(JSON.parse(fields.payload_json||"{}").save_request_id||""):"";
      const tracksDraft=fields.action==="review_en_draft_save";
      if(tracksDraft)legacyDraftBatchRequests++;
      let settled=false;
      const cleanup=()=>{
        if(settled)return;settled=true;
        clearTimeout(timer);window.removeEventListener("message",receive);
        if(tracksDraft)legacyDraftBatchRequests--;
      };
      const receive=event=>{
        const data=event.data||{};
        if(data.source!=="soulkey-bridge"||data.type!==expected||
           String(data.task_id||"")!==String(fields.task_id||""))return;
        if(requestId&&String(data.request_id||"")!==requestId)return;
        cleanup();resolve(data);
      };
      const timer=setTimeout(()=>{cleanup();reject(new Error("原服務儲存回執逾時，請核對後重試"));},90000);
      window.addEventListener("message",receive);
      if(!submit(fields)){cleanup();reject(new Error("原服務儲存未送出"));}
    });
  }
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),45000);
  try{
    const response=await fetch(BRIDGE_ENDPOINT,{
      method:"POST",mode:"cors",cache:"no-store",signal:controller.signal,
      headers:{"Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"},
      body:new URLSearchParams({...fields,bridge_key:bridgeKeyValue()})
    });
    return await response.json();
  }finally{clearTimeout(timer);}
}

async function saveCentralEnglishDraft(editPayload){
  const rows=editPayload.segments.filter(x=>x.en_confirmed===true);
  if(!rows.length)throw new Error("請先確認至少一句英文，再儲存");
  const current=await centralReviewRequest({action:"review_en_draft_status",task_id:taskId,include_edits:"1"});
  if(!current.ok)throw new Error(current.message||current.error||"無法核對英文版本");
  for(const row of rows){
    const server=current.edits?.[String(row.id)];
    if(server && String(server.request_id)!==String(englishBaseRequests[String(row.id)]||"") &&
       String(server.en_text)!==String(row.en_text))
      throw new Error("這句英文已由其他裝置更新，請保留本機修改並重新載入："+row.id);
  }
  for(let offset=0;offset<rows.length;offset+=25){
    const part=rows.slice(offset,offset+25);
    const requestId=Date.now()+"-"+offset+"-"+Math.random().toString(36).slice(2);
    const batch={...editPayload,save_request_id:requestId,
      confirmed_segment_ids:part.map(x=>x.id),segments:part.map(x=>({...x,
        base_request_id:String(current.edits?.[String(x.id)]?.request_id||"")}))};
    let result;
    try{
      result=await centralReviewRequest({action:"review_en_draft_save",task_id:taskId,
        payload_json:JSON.stringify(batch)});
    }catch(error){
      // A lost ACK may follow a committed write. Confirm the same request ID
      // before permitting a later attempt with a different revision.
      const receipt=await centralReviewRequest({action:"review_en_draft_status",task_id:taskId,request_id:requestId});
      if(!receipt.ok||!receipt.committed)throw error;
      result={ok:true};
    }
    if(!result.ok)throw new Error(result.message||result.error||"英文儲存未確認");
    for(const row of part)englishBaseRequests[String(row.id)]=requestId;
  }
  return {source:"soulkey-bridge",type:"english_review_draft_saved",ok:true,
    task_id:taskId,storage:"google-sheet"};
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

  const englishMode=currentStep===2 &&
    Array.isArray(englishAligned)&&englishAligned.length &&
    !!payload?.zh_finalized_at;
  const editPayload=englishMode ? {
    version:6,task_id:taskId,
    zh_finalized_at:String(payload.zh_finalized_at||""),
    english_cc_available:true,
    english_cc_language:"en",
    english_cc_source:"youtube_or_ai_review",
    segments:englishAligned.map(x=>({
      id:Number(x.id),
      start:Number(x.start||0),end:Number(x.end||0),
      time:String(x.time||clock(x.start)),
      raw:"",text:String(x.text||""),confirmed:true,
      source_en:String(x.source_en||""),
      en_text:String(x.en_text||x.source_en||""),
      en_confirmed:x.en_confirmed===true
    }))
  }:currentPayload();
  if(englishMode){
    saveCentralEnglishDraft(editPayload).then(data=>{
      window.dispatchEvent(new MessageEvent("message",{data}));
    }).catch(error=>window.dispatchEvent(new MessageEvent("message",{data:{
      source:"soulkey-bridge",type:"english_review_draft_saved",ok:false,
      task_id:taskId,message:error.message
    }})));
    return;
  }
  const sent=submit({
    action:"review_share_draft_save",
    task_id:taskId,
    payload_json:JSON.stringify(editPayload)
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
  const groups=englishGroups();
  const missing=groups.filter(x=>!String(x.en_text||"").trim());
  if(missing.length){
    alert("還有 "+missing.length+" 句英文是空白，請補完後再定稿。");
    return;
  }
  if(!confirm("確定完成 English Final？\n\n之後其他語言會直接以這份英文定稿翻譯。")) return;

  const p=currentPayload();
  const finalSegments=groups.map(x=>({
    id:x.id,
    start:x.start,
    end:x.end,
    text:String(x.en_text||"").trim()
  }));
  setStatus("寫入 English Final…","working");
  $("finalize-en").disabled=true;
  submit({
    action:"review_share_finalize_en",
    task_id:taskId,
    payload_json:JSON.stringify(p),
    segments_json:JSON.stringify(finalSegments)
  });
}

const LANG_NAMES={
  en:"English",
  th:"ภาษาไทย",
  es:"Español",
  id:"Bahasa Indonesia",
  vi:"Tiếng Việt",
  hi:"हिन्दी",
  ta:"தமிழ்",
  ja:"日本語",
  ko:"한국어",
  km:"ភាសាខ្មែរ",
  bn:"বাংলা",
  ne:"नेपाली",
  lo:"ພາສາລາວ",
  my:"မြန်မာဘာသာ",
  it:"Italiano",
  pt:"Português (Brasil)",
};

const LANG_NAMES_ZH={
  en:"英文",th:"泰文",es:"西班牙文",id:"印尼文",vi:"越南文",
  hi:"印地語",ta:"泰米爾文",ja:"日文",ko:"韓文",km:"高棉文",
  bn:"孟加拉文",ne:"尼泊爾文",lo:"寮文",my:"緬甸文",it:"義大利文",pt:"葡萄牙文"
};

function collectOutputPlan(){
  return [...document.querySelectorAll(".output-row")].map(row=>{
    const code=row.dataset.outputLang;
    const selected=!!row.querySelector("[data-output-enabled]")?.checked;
    return {
      language_code:code,
      language_name:LANG_NAMES[code]||code,
      transcript_enabled:code==="en"||selected,
      transcript_source:code==="en"?"human":"ai",
      audio_enabled:selected,
      audio_source:"tts"
    };
  });
}

function updateOutputSummary(){
  const selected=collectOutputPlan()
    .filter(x=>x.audio_enabled)
    .map(x=>LANG_NAMES_ZH[x.language_code]||x.language_code);
  $("output-summary").textContent=selected.length
    ? "已選 "+selected.length+" 種："+selected.join("、")+"。每種都會產生文稿＋自然語音音檔。"
    : "目前保留英文人工 Final；尚未選擇額外輸出。";
}

function finishWorkflow(){
  if(!payload?.en_finalized_at){
    alert("請先完成 English Final。");
    return;
  }
  const plan=collectOutputPlan();
  const extra=plan.filter(x=>x.language_code!=="en"&&x.audio_enabled);
  const audio=plan.filter(x=>x.audio_enabled);

  const msg=
    "確定開始最終輸出？\n\n"+
    "選擇語言："+(audio.map(x=>LANG_NAMES_ZH[x.language_code]||x.language_code).join("、")||"無")+"\n"+
    "所選語言都會生成文稿及自然語音 MP3，英文 Final 保留。";
  if(!confirm(msg)) return;

  $("finish-workflow").disabled=true;
  setStatus("送出最終輸出工作…","working");
  if(/iPad|iPhone|iPod/i.test(navigator.userAgent||"")){
    finishTarget="soulkey-finish-"+Date.now();
    window.open("about:blank",finishTarget);
  }
  const translateLangs=extra.map(x=>x.language_code);
  const audioLangs=audio.map(x=>x.language_code);
  finishPending={submittedAt:Date.now(),previousRunId:"",translateLangs,audioLangs};
  centralReviewRequest({action:"language_plan_save",task_id:taskId,
    plan_json:JSON.stringify(plan)}).then(result=>{
    if(!result.ok)throw new Error(result.message||result.error||"語言設定未儲存");
    const sent=submit(/^https:\/\/script\.google\.com\//.test(BRIDGE_ENDPOINT)
      ? {action:"review_finish",task_id:taskId,plan_json:JSON.stringify(plan)}
      : {action:"run_stage",task_id:taskId,stage:"finish",
         langs:translateLangs.join(","),lang:audioLangs.join(",")});
    if(!sent)throw new Error("派工未送出");
    setStatus("請求已送出，等待中央派工確認…","working");
    for(const wait of [3000,8000,15000,30000,60000])
      window.setTimeout(()=>jsonpBridgeRequest({action:"status",task_id:taskId}),wait);
  }).catch(error=>{
    finishPending=null;$("finish-workflow").disabled=false;
    setStatus(error.message,"error");
  });
}

window.addEventListener("message",event=>{
  const data=event.data||{};
  if(data.source!=="soulkey-bridge") return;
  if(finishPending && data.type==="status_result" && data.ok){
    const state=data.tasks?.[taskId]?.stages?.finish;
    if(window.SoulKeyBridgeRoutes.dispatchReceipt(finishPending,state)){
      window.dispatchEvent(new MessageEvent("message",{data:{
        source:"soulkey-bridge",type:"run_stage",ok:true,task_id:taskId,
        stage:"finish",run_id:state.run_id
      }}));
    }
  }
  if(finishPending && data.type==="run_stage" && data.task_id===taskId && data.stage==="finish"){
    const pending=finishPending;finishPending=null;
    window.dispatchEvent(new MessageEvent("message",{data:{...data,
      type:"review_finish_queued",translate_langs:pending.translateLangs,
      audio_langs:pending.audioLangs,
      message:data.ok?"中央已確認 Kaggle 派工；完成後請核對文稿及音檔":data.message
    }}));
  }

  if(data.type==="status_health" && data.ok){
    bridgeProtocolVersion=window.SoulKeyBridgeRoutes.protocol(data.bridge_protocol);
    if(bridgeProtocolVersion<REQUIRED_BRIDGE_PROTOCOL){
      setStatus(
        "控制中心版本過舊（v"+bridgeProtocolVersion+"）；可讀取 Drive，但已停用寫入與送出工作，請重新部署 Code.gs。",
        "error"
      );
      ["save-draft","finalize-zh","finalize-en","finish-workflow"].forEach(id=>{
        const el=$(id);
        if(el) el.disabled=true;
      });
    }
  }

  if(data.type==="review_cache_status" && data.ok &&
     String(data.task_id||"")===taskId && data.stale){
    setStatus("中文 Final 比 GitHub 快取更新・正在自動修復","working");
    submit({action:"review_cache_seed",task_id:taskId});
  }
  if(data.type==="review_cache_seeded" &&
     String(data.task_id||"")===taskId){
    if(data.ok){
      // The server has committed GitHub; raw-content propagation may lag.
      if(!dirty && currentStep===1){
        window.setTimeout(()=>loadReview(),950);
      }
    }else{
      setStatus("Google Drive 中文 Final 安全保留；GitHub 快取待修復","working");
    }
  }

  if(data.type==="review_data"){
    if(data.task_id && String(data.task_id)!==taskId) return;
    if(!data.ok){
      if(data.kind==="en"){
        // English may legitimately not exist before Chinese Final. Keep the
        // already-loaded Chinese review usable instead of turning the whole
        // quick editor into an error state.
        setStatus(
          "中文稿已載入；英文來源尚未建立，可先完成中文定稿。",
          "ok"
        );
        return;
      }
      setStatus(data.message||data.error||"Google Drive 備援讀取失敗","error");
      return;
    }

    if(data.kind==="zh"){
      const chunkIndex=Number(data.chunk_index||0);
      if(chunkIndex===0){
        driveFallbackZh=[];
        driveFallbackTotal=Number(data.total_segments||0);
        driveFallbackFinalSource=data.is_final===true && data.review_source==="zh-TW.final.json";
        driveFallbackFinalizedAt=driveFallbackFinalSource?String(data.zh_finalized_at||data.finalized_at||"drive-final"):"";
        driveFallbackReviewRevision=String(data.review_revision||"");
      }else if(driveFallbackReviewRevision!==String(data.review_revision||"") ||
               driveFallbackTotal!==Number(data.total_segments||0) ||
               driveFallbackFinalSource!==(data.is_final===true && data.review_source==="zh-TW.final.json")){
        setStatus("中文稿版本已變動，請重新載入；此裝置的修改仍保留","error");
        return;
      }
      driveFallbackZh.push(...(Array.isArray(data.segments)?data.segments:[]));

      if(data.has_more){
        setStatus(
          "GitHub 快取缺少・由 Drive 載入 "+
          driveFallbackZh.length+"/"+(driveFallbackTotal||"?")+" 段",
          "working"
        );
        requestDriveReview("zh",chunkIndex+1);
        return;
      }

      const fallbackPayload={
        version:5,
        task_id:taskId,
        generated_at:new Date().toISOString(),
        total_segments:driveFallbackZh.length,
        zh_finalized_at:driveFallbackFinalizedAt,
        segments:driveFallbackZh
      };
      applyReviewPayload(fallbackPayload);
      loadAlignedEnglish();

      // If an AI English draft already exists in Drive, merge it immediately
      // so Step 2 remains usable even though the GitHub cache was absent.
      requestDriveReview("en",0);
      return;
    }

    if(data.kind==="en"){
      const rows=Array.isArray(data.segments)?data.segments:[];
      // A successful English Drive response proves zh-TW.final.json exists,
      // because the Bridge refuses to return English review data otherwise.
      // Preserve that fact when GitHub cache is temporarily unavailable so a
      // shared ?step=en link still opens the English editor directly.
      if(!payload) payload={};
      if(!payload.zh_finalized_at){
        payload.zh_finalized_at="drive-final";
      }
      // English Final and Chinese ASR IDs describe different paragraph sets.
      // Keep the authenticated English rows and their time-aligned Chinese;
      // joining 59 English passages onto 449 ASR IDs silently loses content.
      if(!dirty){
        englishDriveLoaded=true;
        englishAligned=rows.map((row,index)=>({
          ...row,
          id:Number(row.id??index),
          text:String(row.original??row.text??""),
          source_en:String(row.source_en??""),
          en_text:String(row.en??row.en_text??row.source_en??""),
          en_confirmed:row.en_confirmed===true,
          zh_ids:Array.isArray(row.ids)?row.ids.map(Number):[]
        }));
        payload.en_finalized_at=String(data.finalized_at||
          (data.is_final===true && data.review_source==="en.final.json"?"drive-final":""));
        if(!payload.en_finalized_at) restoreEnglishDraftEdits(englishAligned).catch(()=>{
          setStatus("Drive 英文稿已載入；逐句修改回讀失敗，請重新整理核對","error");
        });
      }
      $("finalize-zh").disabled=true;
      $("finalize-en").disabled=!!payload.en_finalized_at;
      $("finish-workflow").disabled=!payload.en_finalized_at;
      renderZh();
      renderEn();
      setStep(requestedStepNumber||(payload.en_finalized_at?3:2));
      setStatus(dirty?"已讀取 Drive；保留此裝置尚未儲存的修改":
        payload.en_finalized_at?"已由 Google Drive 恢復中英文人工定稿":
        "GitHub 快取缺少・已由 Google Drive 恢復中英文稿","ok");
      return;
    }
  }

  if((data.type==="review_share_draft_saved" ||
      data.type==="english_review_draft_saved") &&
     !(data.type==="english_review_draft_saved" && legacyDraftBatchRequests>0)){
    saveInFlight=false;
    $("save-draft").disabled=false;
    if(data.ok){
      lastSavedRevision=Math.max(lastSavedRevision,saveRevisionInFlight);
      dirty=revision>lastSavedRevision;
      setStatus(
        saveQueued?"前一批已同步・繼續同步最新修改…":data.storage==="google-sheet"?"英文已寫入中央表並回讀驗證":"已同步到 GitHub",
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
      // The server publishes the source-aligned /en.json after saving
      // Chinese Final. Retry once after its separate GitHub update.
      window.setTimeout(()=>loadAlignedEnglish(true),1100);
      requestDriveReview("en",0);
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
      if(Array.isArray(local.english_aligned) && local.english_aligned.length){
        englishAligned=local.english_aligned;
      }
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

async function fastReviewJson(kind){
  const file=kind==="en"?"en.json":"zh.json";
  const path="/"+encodeURIComponent(taskId)+"/"+file+"?_="+Date.now();
  const sameOrigin=new URL("../studio-review-cache"+path,location.href).toString();
  const raw=REVIEW_CACHE_BASE+path;
  return Promise.any([sameOrigin,raw].map(async url=>{
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),5000);
    try{
      const response=await fetch(url,{
        cache:"no-store",signal:controller.signal,
        headers:{"Accept":"application/json"}
      });
      if(!response.ok) throw new Error("HTTP "+response.status);
      const data=await response.json();
      if(data.task_id && data.task_id!==taskId) throw Error("Task mismatch");
      if(!Array.isArray(data.segments)) throw Error("Missing segments");
      return data;
    }finally{clearTimeout(timer);}
  }));
}

async function restoreEnglishDraftEdits(alignedRows){
  const saved=await centralReviewRequest({action:"review_en_draft_status",task_id:taskId,include_edits:"1"});
  if(!saved.ok || dirty || payload?.en_finalized_at || englishAligned!==alignedRows) return;
  for(const row of alignedRows){
    const edit=saved.edits?.[String(row.id)];
    if(edit){row.en_text=String(edit.en_text);row.en_confirmed=true;
      englishBaseRequests[String(row.id)]=String(edit.request_id||"");}
  }
  renderEn();
}

async function loadAlignedEnglish(force=false){
  if(!payload?.zh_finalized_at || englishDriveLoaded || (englishAligned && !force)) return;
  try{
    const aligned=await fastReviewJson("en");
    if(englishDriveLoaded) return;
    if(!aligned.segments?.length) return;
    // Do not overwrite a newer unsaved English edit from this device.
    if(dirty && Array.isArray(englishAligned) && englishAligned.length) return;
    englishAligned=aligned.segments.map(x=>({
      ...x,id:Number(x.id),text:String(x.text||""),
      source_en:String(x.source_en||""),
      en_text:String(x.en_text||x.source_en||"")
    }));
    if(aligned.en_finalized_at){
      payload.en_finalized_at=String(aligned.en_finalized_at);
      $("finalize-en").disabled=true;
      $("finish-workflow").disabled=false;
    }
    if(!payload.en_finalized_at) await restoreEnglishDraftEdits(englishAligned);
    renderEn();
    setStep(requestedStepNumber||(payload.en_finalized_at?3:2));
    setStatus("中英段落已按中文 Final 時間軸對齊","ok");
  }catch(_){
    // Legacy lessons without an English cache retain the Drive fallback.
  }
}

async function loadReview(){
  $("task-id").textContent=taskId||"無效課程";
  if(!/^P\d+-L\d+$/i.test(taskId)){
    setStatus("課程代號錯誤","error");
    return;
  }

  try{
    const loaded=await fastReviewJson("zh");
    if(loaded?.segments?.length){
      applyReviewPayload(loaded);
      loadAlignedEnglish();
      if(loaded.zh_finalized_at){
        requestDriveReview("en",0);
      }
      return;
    }
    throw new Error("GitHub 快取內容為空");
  }catch(err){
    // Repair genuinely missing GitHub cache, but do not re-publish on every
    // open. The status check separately repairs mismatched Final revisions.
    submit({action:"review_cache_seed",task_id:taskId});
    if(requestDriveReview("zh",0)){
      setStatus("GitHub 讀取失敗・改由 Google Drive 載入…","working");
      return;
    }
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

document.querySelectorAll(".output-row [data-output-enabled]").forEach(toggle=>{
  toggle.addEventListener("change",updateOutputSummary);
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
jsonpBridgeRequest({action:"status_health"});
loadReview();
jsonpBridgeRequest({action:"review_cache_status",task_id:taskId});

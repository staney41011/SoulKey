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
let visibleCount=RENDER_BATCH;
let player=null;
let playerReady=false;
let pendingSeek=null;
let finalized=false;
let revision=0;
let lastSavedRevision=0;
let saveInFlight=false;
let saveQueued=false;
let saveRevisionInFlight=0;

const $=id=>document.getElementById(id);
const esc=value=>String(value??"")
  .replace(/&/g,"&amp;")
  .replace(/</g,"&lt;")
  .replace(/>/g,"&gt;")
  .replace(/"/g,"&quot;")
  .replace(/'/g,"&#039;");

function setStatus(text,state=""){
  const el=$("save-status");
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
  const list=(items||[]).map(x=>({...x}));
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

function filteredSegments(){
  if(activeFilter==="all") return segments;
  return segments.filter(x=>(x.flags||[]).includes(activeFilter));
}

function render(){
  const list=$("segment-list");
  const filtered=filteredSegments();
  const shown=filtered.slice(0,visibleCount);

  const confirmedCount=segments.filter(x=>x.confirmed===true).length;
  $("segment-summary").textContent=
    "已確認 "+confirmedCount+" / "+segments.length+" 段・待人工確認 "+
    segments.filter(x=>(x.flags||[]).includes("uncertain")).length+
    " 段";

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
          <textarea class="final-text" data-edit-id="${esc(s.id??i)}">${esc(s.text||"")}</textarea>
        </div>
        <div class="segment-actions">
          <button class="play-segment" type="button">▶ 聽這段</button>
          <button class="confirm-segment ${s.confirmed===true?"confirmed":""}" type="button">${s.confirmed===true?"✓ 已確認":"確認此段"}</button>
        </div>
      </article>
    `).join("");
  }

  const more=filtered.length-shown.length;
  $("load-more").hidden=more<=0;
  if(more>0){
    $("load-more").textContent="再顯示 "+Math.min(RENDER_BATCH,more)+" 段（尚有 "+more+" 段）";
  }

  bindRows();
}

function persistLocalDraft(){
  localStorage.setItem("soulkey_shared_draft:"+taskId,JSON.stringify({
    task_id:taskId,
    saved_at:Date.now(),
    revision,
    segments
  }));
}

function bindRows(){
  document.querySelectorAll(".segment-card").forEach(card=>{
    const id=Number(card.dataset.id);
    const textarea=card.querySelector(".final-text");
    textarea?.addEventListener("input",()=>{
      const item=segments.find(x=>Number(x.id)===id);
      if(item) item.text=textarea.value;
      revision++;
      dirty=true;
      setStatus("尚未儲存","working");
      persistLocalDraft();
    });

    card.querySelector(".play-segment")?.addEventListener("click",()=>{
      document.querySelectorAll(".segment-card.playing").forEach(x=>x.classList.remove("playing"));
      card.classList.add("playing");
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

      const confirmedCount=segments.filter(x=>x.confirmed===true).length;
      $("segment-summary").textContent=
        "已確認 "+confirmedCount+" / "+segments.length+" 段・待人工確認 "+
        segments.filter(x=>(x.flags||[]).includes("uncertain")).length+
        " 段";

      setStatus(item.confirmed===true?"同步確認狀態到 GitHub…":"同步取消確認到 GitHub…","working");
      requestDraftSave("confirm");
    });
  });
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
    version:4,
    task_id:taskId,
    total_segments:segments.length,
    segments:segments.map(x=>({
      id:Number(x.id),
      start:Number(x.start||0),
      end:Number(x.end||0),
      time:String(x.time||clock(x.start)),
      raw:String(x.raw||""),
      text:String(x.text||""),
      flags:Array.isArray(x.flags)?x.flags:[],
      confirmed:x.confirmed===true
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
  if(finalized) return;

  if(saveInFlight){
    saveQueued=true;
    setStatus("已有同步進行中・下一次變更已排隊","working");
    return;
  }

  saveInFlight=true;
  saveQueued=false;
  saveRevisionInFlight=revision;
  setStatus(reason==="confirm"?"同步確認狀態到 GitHub…":"儲存進度到 GitHub…","working");
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

function finalize(){
  if(finalized) return;
  if(!confirm("確定這堂課已完成中文逐字稿人工定稿？\n\n完成後會寫入 Google Drive Final。這個固定編輯連結之後仍可再次開啟。")) return;

  const p=currentPayload();
  setStatus("寫入正式 Final…","working");
  $("save-draft").disabled=true;
  $("finalize-review").disabled=true;

  submit({
    action:"review_share_finalize",
    task_id:taskId,
    payload_json:JSON.stringify(p),
    segments_json:JSON.stringify(p.segments.map(x=>({
      id:x.id,start:x.start,end:x.end,text:x.text
    })))
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

      if(!dirty){
        persistLocalDraft();
      }

      setStatus(
        saveQueued ? "前一批已同步・繼續同步最新變更…" : "已同步到 GitHub",
        saveQueued ? "working" : "ok"
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
      finalized=true;
      dirty=false;
      localStorage.removeItem("soulkey_shared_draft:"+taskId);
      setStatus("中文定稿完成","ok");
      $("save-draft").disabled=true;
      $("finalize-review").disabled=true;
      document.querySelectorAll("textarea").forEach(x=>x.disabled=true);
      alert("中文定稿已完成並寫回 Google Drive。固定編輯連結仍可繼續使用。");
    }else{
      $("save-draft").disabled=false;
      $("finalize-review").disabled=false;
      setStatus(data.message||data.error||"定稿失敗","error");
    }
  }
});

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
    segments=repairTimings(payload.segments||[]);

    const localRaw=localStorage.getItem("soulkey_shared_draft:"+taskId);
    if(localRaw){
      try{
        const local=JSON.parse(localRaw);
        const remoteSavedAt=Date.parse(
          String(payload.draft_saved_at||payload.generated_at||"")
        )||0;
        const localSavedAt=Number(local.saved_at||0);

        if(
          localSavedAt>remoteSavedAt &&
          Array.isArray(local.segments) &&
          local.segments.length===segments.length
        ){
          const localById=new Map(local.segments.map(x=>[Number(x.id),x]));
          segments=segments.map(x=>{
            const draft=localById.get(Number(x.id));
            return draft?{
              ...x,
              text:String(draft.text??x.text),
              confirmed:draft.confirmed===true
            }:x;
          });
          revision=Number(local.revision||1);
          lastSavedRevision=0;
          dirty=true;
          setStatus("已恢復此裝置較新的未送出修改","working");
        }
      }catch(_){}
    }

    render();
    $("save-draft").disabled=false;
    $("finalize-review").disabled=false;
    if(!dirty) setStatus("已載入最新工作稿","ok");
  }catch(err){
    setStatus(err.message||String(err),"error");
    $("segment-list").innerHTML='<div class="card empty">'+esc(err.message||err)+'</div>';
  }
}

document.querySelectorAll("[data-filter]").forEach(btn=>{
  btn.addEventListener("click",()=>{
    document.querySelectorAll("[data-filter]").forEach(x=>x.classList.toggle("active",x===btn));
    activeFilter=btn.dataset.filter||"all";
    visibleCount=RENDER_BATCH;
    render();
  });
});
$("load-more").addEventListener("click",()=>{
  visibleCount+=RENDER_BATCH;
  render();
});
$("save-draft").addEventListener("click",()=>requestDraftSave("manual"));
$("finalize-review").addEventListener("click",finalize);
$("back-5").addEventListener("click",()=>{
  if(playerReady&&player) seekTo(Math.max(0,Number(player.getCurrentTime()||0)-5),true);
});
$("forward-5").addEventListener("click",()=>{
  if(playerReady&&player) seekTo(Number(player.getCurrentTime()||0)+5,true);
});
window.addEventListener("beforeunload",event=>{
  if(dirty&&!finalized){
    event.preventDefault();
    event.returnValue="";
  }
});

mountPlayer();
loadReview();

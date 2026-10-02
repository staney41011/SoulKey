const cfg = window.SOULKEY_CONFIG || {};

const STORE = {
  tasks: "soulkey_studio_tasks_v2",
  terms: "soulkey_studio_terms_v1",
  gpu: "soulkey_studio_gpu_v1"
};

const BRIDGE_ENDPOINT_KEY = "soulkey_bridge_endpoint_v1";
const BRIDGE_SESSION_KEY = "soulkey_bridge_key_session_v1";
const BRIDGE_ENDPOINT = String(cfg.bridgeEndpoint || "").trim();
const STATUS_POLL_MS = 12000;
const REQUIRED_BRIDGE_PROTOCOL = 9;
let bridgeProtocolVersion = 0;
const REVIEW_CACHE_BASE = String(cfg.reviewCacheBaseUrl || "https://raw.githubusercontent.com/staney41011/SoulKey/main/studio-review-cache").replace(/\/$/,"");
const ZH_RENDER_BATCH = 80;
let bridgeClientReady = false;
let youtubeCookiesConfigured = null;
let reviewYouTubePlayer = null;
let reviewYouTubeVideoId = "";
let reviewYouTubeReady = false;
let reviewYouTubePendingSeek = null;
let reviewYouTubeApiPromise = null;

window.addEventListener("error",event=>{
  const message=String(event?.message || "前端執行錯誤");
  const dashboardMessage=document.getElementById("dashboard-bridge-message");
  if(dashboardMessage){
    dashboardMessage.textContent="前端錯誤："+message;
  }
  const apiState=document.getElementById("api-state");
  if(apiState){
    apiState.textContent="前端錯誤";
    apiState.className="warn";
  }
});

const seedTerms = [
  ["前賢","道場稱謂","前嫌、前線、淺顯、請醒"],
  ["白陽期","宗教術語","白羊期、白楊期、白羊棋、白楊棋"],
  ["修道","宗教術語",""],
  ["辦道","宗教術語",""],
  ["修辦","宗教術語","修半、休辦"],
  ["學修講辦","宗教術語","學修講半"],
  ["開荒辦道","宗教術語","開荒半道"],
  ["金線傳承","宗教術語","經現傳承"],
  ["天恩師德","宗教術語","天師德"],
  ["仙佛慈悲","宗教術語","先佛慈悲"],
  ["老母慈悲","宗教術語",""],
  ["關法律主","仙佛／聖賢","關法律子"],
  ["扶圓補缺","宗教術語","胡園補缺"],
  ["一世修一世成","宗教術語","一試修一試成"],
  ["超生了死","宗教術語",""],
  ["渡化","宗教術語","杜化"]
].map((x,i)=>({
  id:"seed-"+i,
  name:x[0],
  category:x[1],
  aliases:x[2],
  description:"",
  en:"",
  status:"正式詞庫"
}));

const WORKFLOW_VERSION = 7;

const workflow = [
  {key:"zh", label:"中文定稿", short:"中文定稿", hint:"來源 → ASR → AI 校稿 → 人工定稿"},
  {key:"en-review", label:"英文定稿", short:"英定稿", hint:"優先 YouTube English CC；無 CC 時中文 → 英文 AI"},
  {key:"multi", label:"各國語言翻譯", short:"多語", hint:"依選擇"},
  {key:"tts", label:"各國語言音檔", short:"音檔", hint:"依選擇"}
];

function load(key, fallback){
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}
function save(key, value){ localStorage.setItem(key, JSON.stringify(value)); }

const REVIEW_CACHE_PREFIX = "soulkey_review_cache_v1:";
const reviewRequestStartedAt = {};
const reviewCacheSeedRequested = new Set();

function reviewCacheKey(taskId,kind){
  return REVIEW_CACHE_PREFIX+String(taskId||"")+":"+String(kind||"");
}

function readReviewCache(taskId,kind){
  try{
    const raw=localStorage.getItem(reviewCacheKey(taskId,kind));
    if(!raw) return null;
    const data=JSON.parse(raw);
    if(!data || !Array.isArray(data.segments) || !data.segments.length) return null;
    return data;
  }catch(_){
    return null;
  }
}

function writeReviewCache(data){
  if(!data || !data.task_id || !data.kind || !Array.isArray(data.segments)) return;
  try{
    localStorage.setItem(
      reviewCacheKey(data.task_id,data.kind),
      JSON.stringify({
        task_id:data.task_id,
        kind:data.kind,
        segments:data.segments,
        load_ms:Number(data.load_ms||0),
        saved_at:Date.now()
      })
    );
  }catch(_){
    // localStorage 空間不足時只略過快取，不影響正式雲端流程。
  }
}

function setZhReviewLoadState(message,state="idle"){
  const el=document.getElementById("review-load-state");
  if(!el) return;
  el.className="badge";
  if(state==="ok") el.classList.add("complete");
  if(state==="error") el.classList.add("bridge-error");
  el.textContent=message;
}

function setZhFinalizeEnabled(enabled){
  const btn=document.getElementById("finalize-zh");
  if(btn) btn.disabled=!enabled;
}

function reviewRequestKey(taskId,kind,chunkIndex=0){
  return String(taskId||"")+"|"+String(kind||"")+"|"+String(chunkIndex||0);
}

function startReviewTimer(taskId,kind,chunkIndex=0){
  reviewRequestStartedAt[reviewRequestKey(taskId,kind,chunkIndex)]=performance.now();
}

function reviewElapsedMs(taskId,kind,chunkIndex=0){
  const key=reviewRequestKey(taskId,kind,chunkIndex);
  const started=reviewRequestStartedAt[key];
  delete reviewRequestStartedAt[key];
  return started ? Math.max(0,performance.now()-started) : 0;
}

let tasks = load(STORE.tasks, []);
let terms = load(STORE.terms, seedTerms);
let languageSettings = [
  {code:"th",name:"ภาษาไทย",can_ai_translate:true,can_tts:true},
  {code:"es",name:"Español",can_ai_translate:true,can_tts:true},
  {code:"id",name:"Bahasa Indonesia",can_ai_translate:true,can_tts:true},
  {code:"vi",name:"Tiếng Việt",can_ai_translate:true,can_tts:true},
  {code:"sd",name:"سنڌي",can_ai_translate:true,can_tts:true},
  {code:"ta",name:"தமிழ்",can_ai_translate:true,can_tts:true}
];
let selectedTaskId = null;
let selectedPeriod = null;
let currentZhReview = [];
let currentZhReviewAll = [];
let zhFreshSegments = [];
let zhReviewLoading = false;
let zhReviewCachedPreview = false;
let zhReviewTotal = 0;
let zhDirtySegmentIds = new Set();
let zhVisibleCount = ZH_RENDER_BATCH;
let zhActiveFilter = "all";
let zhGithubSaveInFlight = false;
let zhGithubSaveQueued = false;
let zhGithubRevision = 0;
let zhGithubLastSavedRevision = 0;
let zhGithubSaveRevisionInFlight = 0;
let currentVernacularReview = [];
let currentEnglishReview = [];
let currentView = "dashboard";
const viewHistory = [];
const youtubeCaptureFilesCache = {};
const youtubeCaptureFilesFetchedAt = {};
let youtubeCaptureFilesLoadingTask = "";
let scheduleDraftPeriod = null;
let scheduleDraftOrder = [];

if(!localStorage.getItem(STORE.terms)) save(STORE.terms, terms);

const titles = {
  dashboard:"任務總覽",
  "new-task":"建立任務",
  schedule:"課表管理",
  "task-detail":"課程任務",
  review:"人工中文定稿",
  "vernacular-review":"人工白話文定稿",
  "en-review":"英文定稿",
  glossary:"專有名詞庫",
  knowledge:"經典知識庫",
  "youtube-audio":"YouTube 抓取",
  system:"系統狀態"
};

function escapeHtml(s){
  return String(s ?? "").replace(/[&<>"']/g,m=>({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[m]));
}

function bridgeKeyValue(){
  return (
    document.getElementById("dashboard-bridge-key")?.value.trim() ||
    sessionStorage.getItem(BRIDGE_SESSION_KEY) ||
    ""
  );
}

function bridgeEndpointValue(){
  return BRIDGE_ENDPOINT;
}

function setDashboardBridgeState(message,state="idle"){
  const badge=document.getElementById("dashboard-bridge-state");
  const msg=document.getElementById("dashboard-bridge-message");
  if(msg) msg.textContent=message;
  if(!badge) return;

  badge.className="badge";
  if(state==="ok"){
    badge.classList.add("complete");
    badge.textContent="已連線";
  }else if(state==="working"){
    badge.textContent="同步中";
  }else if(state==="error"){
    badge.classList.add("bridge-error");
    badge.textContent="連線失敗";
  }else{
    badge.textContent="尚未連線";
  }
}

function syncStudioNow(){
  const key=bridgeKeyValue();
  if(!BRIDGE_ENDPOINT){
    setDashboardBridgeState("系統尚未設定 Apps Script URL。","error");
    return false;
  }
  if(!key){
    setDashboardBridgeState("請先輸入 Bridge Key。","idle");
    return false;
  }

  sessionStorage.setItem(BRIDGE_SESSION_KEY,key);
  setDashboardBridgeState("正在讀取中央控制中心…","working");
  initBridgeClient();
  requestStatusHealth();
  requestLanguageSettings();
  requestTasksFromControlCenter();
  return true;
}

function updateBackButton(){
  const button=document.getElementById("back-button");
  if(!button) return;
  button.hidden=currentView==="dashboard";
}

function latestPeriodForNewTask(){
  const periods=availablePeriods();
  if(periods.length) return periods[0];

  const fallback=Number(selectedPeriod)||Number(document.getElementById("period")?.value)||1;
  return fallback>0 ? fallback : 1;
}

function applyLatestPeriodToNewTask(){
  const input=document.getElementById("period");
  if(!input) return;
  const latest=latestPeriodForNewTask();
  input.value=String(latest);
  updateTaskCodes();
}

function showView(name, options={}){
  const {fromBack=false, replace=false}=options;
  if(!document.getElementById("view-"+name)) return;

  if(name!==currentView && !fromBack && !replace){
    viewHistory.push(currentView);
  }

  document.querySelectorAll(".view").forEach(x=>x.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(
    x=>x.classList.toggle("active",x.dataset.view===name)
  );
  document.getElementById("view-"+name).classList.add("active");
  document.getElementById("view-title").textContent=titles[name]||"SoulKey Studio";
  currentView=name;
  updateBackButton();

  if(name==="new-task"){
    applyLatestPeriodToNewTask();
  }
  if(name==="youtube-audio"){
    renderYoutubeAudioTasks();
  }

  window.scrollTo({top:0,behavior:"smooth"});
}

function goBack(){
  let target=viewHistory.pop();
  if(!target || target===currentView){
    target="dashboard";
  }
  showView(target,{fromBack:true});
}

document.querySelectorAll("[data-page-back]").forEach(
  button=>button.addEventListener("click",goBack)
);

document.querySelectorAll("[data-view]").forEach(
  b=>b.addEventListener("click",()=>showView(b.dataset.view))
);
document.querySelectorAll("[data-go]").forEach(
  b=>b.addEventListener("click",()=>showView(b.dataset.go))
);

function renderPipeline(){
  document.getElementById("pipeline").innerHTML=workflow.map((x,i)=>
    '<div class="step ready">'+
      '<span>STEP '+String(i+1).padStart(2,"0")+'</span>'+
      '<b>'+x.label+'</b>'+
      '<small>'+x.hint+'</small>'+
    '</div>'
  ).join("");
}

function normalizeTask(t){
  if(!Number.isInteger(t.completedStep)) t.completedStep=-1;

  let version=Number(t.workflowVersion || 1);

  // v2：英文翻譯後加入「English CC 定稿」。
  if(version < 2){
    if(t.completedStep >= 6) t.completedStep += 1;
    version=2;
  }

  // v3：AI 白話文後加入「人工白話文定稿」。
  if(version < 3){
    if(t.completedStep >= 5) t.completedStep += 1;
    version=3;
  }

  if(version < 4){
    version=4;
  }

  // v5：來源資訊 + ASR + AI 中文校稿 + 人工中文定稿，合併成「中文定稿」。
  if(version < 5){
    if(t.completedStep >= 3){
      t.completedStep = t.completedStep - 3;
    }else{
      t.completedStep = -1;
    }
    version=5;
  }

  // v6：暫時跳過「AI 白話文」與「人工白話文定稿」。
  // v5 index: zh=0, vernacular=1, vernacular-review=2, en=3, en-review=4, multi=5, tts=6
  // v6 index: zh=0, en=1, en-review=2, multi=3, tts=4
  if(version < 6){
    if(t.completedStep <= 0){
      t.completedStep = Math.max(-1,t.completedStep);
    }else if(t.completedStep <= 2){
      t.completedStep = 0;
    }else{
      t.completedStep = t.completedStep - 2;
    }
    version=6;
  }

  // v7：有 YouTube English CC 時，直接進English CC 定稿，不再跑 AI 英文翻譯。
  // v6 index: zh=0, en=1, en-review=2, multi=3, tts=4
  // v7 index: zh=0, en-review=1, multi=2, tts=3
  if(version < 7){
    if(t.completedStep <= 0){
      t.completedStep = Math.max(-1,t.completedStep);
    }else if(t.completedStep === 1){
      // 舊版只完成 AI 英文翻譯，仍需English CC 定稿。
      t.completedStep = 0;
    }else{
      t.completedStep = t.completedStep - 1;
    }
    version=7;
  }

  t.workflowVersion=version;
  if(t.completedStep >= workflow.length) t.completedStep=workflow.length-1;
  if(!t.status) t.status="等待執行";
  return t;
}

function remoteStageStatus(task, stageKey){
  if(!task || !task.remoteStages) return null;
  if(task.remoteStages[stageKey]) return normalizeRemoteStatus(task.remoteStages[stageKey]);

  if(stageKey==="zh"){
    const stages=task.remoteStages;
    if(stages.review?.status==="done"){
      return {...stages.review,stage:"zh",status:"done",message:"人工中文定稿完成"};
    }
    if(stages.polish?.status==="done" || stages.polish?.status==="needs_review"){
      return {...(stages.polish||{}),stage:"zh",status:"needs_review",message:"AI 中文校稿完成，待人工中文定稿"};
    }

    // 中文定稿是 metadata → ASR → polish 的合併步驟。
    // 不可固定優先讀 ASR/error，否則舊失敗會蓋掉較新的重跑 queued/running。
    const candidates=["metadata","asr","polish"]
      .map(key=>stages[key] ? normalizeRemoteStatus({...stages[key],stage:"zh",_sourceStage:key}) : null)
      .filter(item=>item && ["queued","running","error","stale"].includes(item.status));

    if(candidates.length){
      const stamp=item=>{
        const raw=String(item.updated_at || item.started_at || item.finished_at || "");
        const parsed=Date.parse(raw.replace(" ","T"));
        return Number.isFinite(parsed) ? parsed : 0;
      };
      candidates.sort((a,b)=>stamp(b)-stamp(a));
      return candidates[0];
    }
  }

  return null;
}

function syncCompletedFromRemote(task){
  normalizeTask(task);

  // 若已完成的步驟後來被最新重跑結果標成 error / stale，
  // 必須退回該步驟前一關。否則 Studio 會誤以為 multi 已完成，
  // 直接跳去 TTS，造成舊翻譯檔反覆被使用。
  for(let i=0;i<workflow.length;i++){
    const remote=remoteStageStatus(task,workflow[i].key);
    if(
      remote &&
      ["error","stale"].includes(remote.status) &&
      i<=task.completedStep
    ){
      task.completedStep=i-1;
      break;
    }
  }

  for(let i=0;i<workflow.length;i++){
    const remote=remoteStageStatus(task,workflow[i].key);
    if(remote && remote.status==="done" && i===task.completedStep+1){
      task.completedStep=i;
    }else if(i>task.completedStep+1){
      break;
    }
  }
  return task;
}

function nextStageFor(task){
  const t=syncCompletedFromRemote(task);
  const nextIndex=t.completedStep+1;
  return nextIndex<workflow.length ? workflow[nextIndex] : null;
}

function taskProgressHtml(task){
  const t=normalizeTask(task);
  return '<div class="task-progress">'+workflow.map((stage,i)=>{
    const state=i<=t.completedStep ? "done" : (i===t.completedStep+1 ? "current" : "");
    return '<span class="task-progress-step '+state+'" title="'+escapeHtml(stage.label)+'">'+
      '<i></i><small>'+escapeHtml(stage.short)+'</small>'+
    '</span>';
  }).join("")+'</div>';
}

function availablePeriods(){
  return [...new Set(tasks.map(t=>Number(t.period)).filter(Boolean))]
    .sort((a,b)=>b-a);
}

function renderPeriodSelector(){
  const select=document.getElementById("dashboard-period");
  if(!select) return;

  const periods=availablePeriods();
  if(!periods.length){
    select.innerHTML='<option value="">尚無期數</option>';
    select.disabled=true;
    selectedPeriod=null;
    return;
  }

  select.disabled=false;
  if(!selectedPeriod || !periods.includes(Number(selectedPeriod))){
    selectedPeriod=periods[0];
  }

  select.innerHTML=periods.map(p=>
    '<option value="'+p+'" '+(Number(selectedPeriod)===p?"selected":"")+'>第 '+p+' 期</option>'
  ).join("");
}

function tasksForSelectedPeriod(){
  if(!selectedPeriod) return [];
  return tasks.filter(t=>Number(t.period)===Number(selectedPeriod));
}

function normalizeRemoteStatus(item){
  if(!item) return null;
  const copy={...item};
  if(["queued","running"].includes(copy.status) && copy.updated_at){
    const ts=Date.parse(String(copy.updated_at).replace(" ","T"));
    if(Number.isFinite(ts) && Date.now()-ts > 30*60*1000){
      copy.status="stale";
      copy.message=(copy.message ? copy.message+"；" : "")+"超過 30 分鐘未更新，可重新執行";
    }
  }
  return copy;
}

function remoteStatusText(status){
  const map={
    pending:"等待執行",
    queued:"Kaggle 排隊中",
    running:"Kaggle 執行中",
    needs_review:"待人工確認",
    done:"完成",
    error:"執行失敗",
    stale:"上游已變更，需重跑"
  };
  return map[status] || status || "";
}

function activeRemoteStatus(task){
  for(const stage of workflow){
    const item=remoteStageStatus(task,stage.key);
    if(!item) continue;
    if(["queued","running","needs_review","error","stale"].includes(item.status)){
      return item;
    }
  }
  return null;
}

function mergeRemoteTasks(remoteTasks){
  if(!Array.isArray(remoteTasks)) return;

  const localById=Object.fromEntries(tasks.map(t=>[t.id,t]));
  const merged=remoteTasks.map(remote=>{
    const local=localById[remote.id] || {};
    const task={
      ...local,
      ...remote,
      id:remote.id,
      workflowVersion:local.workflowVersion || WORKFLOW_VERSION,
      completedStep:Number.isInteger(local.completedStep) ? local.completedStep : -1,
      languagePlan:Array.isArray(local.languagePlan) ? local.languagePlan : []
    };
    normalizeTask(task);
    return task;
  });

  // Preserve local drafts that have not reached the sheet yet.
  tasks.forEach(local=>{
    if(!merged.some(x=>x.id===local.id)) merged.push(local);
  });

  tasks=merged;
  if(!selectedPeriod && tasks.length){
    selectedPeriod=Math.max(...tasks.map(x=>Number(x.period)||0));
  }
  save(STORE.tasks,tasks);
  renderTasks();
}

function requestTasksFromControlCenter(){
  const sent=jsonpBridgeRequest({action:"tasks_get"});
  if(!sent){
    const el=document.getElementById("task-list");
    const select=document.getElementById("dashboard-period");
    if(el){
      el.innerHTML='<div class="empty">尚未連線中央控制中心。請在上方輸入 Bridge Key；Google Sheet 原本任務不會消失。</div>';
    }
    if(select){
      select.innerHTML='<option value="">等待控制中心</option>';
      select.disabled=true;
    }
    if(!bridgeKeyValue()){
      document.getElementById("stat-tasks").textContent="—";
    }
  }
  return sent;
}

function githubReviewUrl(taskId){
  return REVIEW_CACHE_BASE+"/"+encodeURIComponent(String(taskId||""))+"/zh.json?_="+Date.now();
}


function youtubeVideoIdFromUrl(url){
  try{
    const u=new URL(String(url||""));
    if(u.hostname==="youtu.be") return u.pathname.replace(/^\//,"").split("/")[0];
    if(u.hostname.includes("youtube.com")){
      if(u.pathname==="/watch") return u.searchParams.get("v")||"";
      const parts=u.pathname.split("/").filter(Boolean);
      if(["embed","shorts","live"].includes(parts[0])) return parts[1]||"";
    }
  }catch(_){}
  const m=String(url||"").match(/(?:youtu\.be\/|[?&]v=|\/embed\/|\/shorts\/|\/live\/)([A-Za-z0-9_-]{6,})/);
  return m ? m[1] : "";
}

function loadYouTubeIframeApi(){
  if(window.YT && window.YT.Player) return Promise.resolve(window.YT);
  if(reviewYouTubeApiPromise) return reviewYouTubeApiPromise;

  reviewYouTubeApiPromise=new Promise((resolve,reject)=>{
    const prior=window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady=()=>{
      try{ if(typeof prior==="function") prior(); }catch(_){}
      resolve(window.YT);
    };

    if(document.querySelector('script[data-soulkey-youtube-api="1"]')){
      let tries=0;
      const timer=window.setInterval(()=>{
        tries++;
        if(window.YT && window.YT.Player){
          window.clearInterval(timer);
          resolve(window.YT);
        }else if(tries>100){
          window.clearInterval(timer);
          reject(new Error("YouTube Player API 載入逾時"));
        }
      },100);
      return;
    }

    const script=document.createElement("script");
    script.src="https://www.youtube.com/iframe_api";
    script.async=true;
    script.dataset.soulkeyYoutubeApi="1";
    script.onerror=()=>reject(new Error("YouTube Player API 載入失敗"));
    document.head.appendChild(script);
  });

  return reviewYouTubeApiPromise;
}

async function mountReviewYouTubePlayer(task){
  const host=document.getElementById("youtube-review-player");
  const state=document.getElementById("youtube-review-state");
  if(!host) return;

  const videoId=youtubeVideoIdFromUrl(task?.url||"");
  reviewYouTubeVideoId=videoId;
  reviewYouTubeReady=false;
  reviewYouTubePendingSeek=null;

  if(!videoId){
    host.innerHTML='<div class="empty">無法辨識這堂課的 YouTube ID。</div>';
    if(state) state.textContent="YouTube 網址無法辨識";
    return;
  }

  if(state) state.textContent="載入 YouTube…";

  try{
    await loadYouTubeIframeApi();

    if(reviewYouTubePlayer && typeof reviewYouTubePlayer.destroy==="function"){
      try{ reviewYouTubePlayer.destroy(); }catch(_){}
    }

    host.innerHTML='<div id="youtube-review-player-inner"></div>';
    reviewYouTubePlayer=new YT.Player("youtube-review-player-inner",{
      width:"100%",
      height:"100%",
      videoId,
      playerVars:{
        playsinline:1,
        rel:0,
        modestbranding:1
      },
      events:{
        onReady:()=>{
          reviewYouTubeReady=true;
          if(state) state.textContent="YouTube 已就緒";
          if(reviewYouTubePendingSeek!==null){
            const sec=reviewYouTubePendingSeek;
            reviewYouTubePendingSeek=null;
            seekReviewYouTube(sec,true);
          }
        },
        onError:(event)=>{
          if(state) state.textContent="YouTube 播放器錯誤："+event.data;
        }
      }
    });
  }catch(err){
    if(state) state.textContent=String(err?.message||err);
    host.innerHTML='<div class="empty">YouTube 播放器載入失敗。</div>';
  }
}

function seekReviewYouTube(seconds,autoplay=true){
  const sec=Math.max(0,Number(seconds)||0);
  document.getElementById("current-time").textContent=formatClock(sec);

  if(!reviewYouTubeReady || !reviewYouTubePlayer){
    reviewYouTubePendingSeek=sec;
    return;
  }

  try{
    reviewYouTubePlayer.seekTo(sec,true);
    if(autoplay && typeof reviewYouTubePlayer.playVideo==="function"){
      reviewYouTubePlayer.playVideo();
    }
  }catch(_){
    reviewYouTubePendingSeek=sec;
  }
}

function formatClock(seconds){
  const total=Math.max(0,Math.floor(Number(seconds)||0));
  const h=String(Math.floor(total/3600)).padStart(2,"0");
  const m=String(Math.floor((total%3600)/60)).padStart(2,"0");
  const sec=String(total%60).padStart(2,"0");
  return h+":"+m+":"+sec;
}

function repairReviewTimings(items){
  const list=(Array.isArray(items)?items:[]).map(x=>({...x}));
  for(let i=0;i<list.length;i++){
    const cur=list[i];
    const next=list[i+1];
    const start=Number(cur.start||0);
    let end=Number(cur.end||0);
    if(
      next &&
      Number(next.start)>start &&
      (
        !Number.isFinite(end) ||
        end<start ||
        (end-start<2 && Number(next.start)-start>5)
      )
    ){
      end=Number(next.start);
    }
    cur.start=start;
    cur.end=Math.max(start,end||start);
    cur.time=formatClock(start);
  }
  return list;
}

function setZhRefreshButtonState(loading){
  const btn=document.getElementById("refresh-zh-review");
  if(!btn) return;
  btn.disabled=!!loading;
  btn.textContent=loading ? "重新抓取中…" : "重新抓取最新逐字稿";
}

async function loadZhReviewFromGithub(taskId,options={}){
  const retry=Number(options.retry||0);
  const maxRetries=20;
  zhReviewLoading=true;
  setZhFinalizeEnabled(false);
  setZhRefreshButtonState(true);
  setZhReviewLoadState(
    retry ? "GitHub 快取同步中・重新讀取 "+retry+"/"+maxRetries : "GitHub 直讀中…",
    "working"
  );

  try{
    const controller=new AbortController();
    const timeout=window.setTimeout(()=>controller.abort(),6000);
    let response;
    try{
      response=await fetch(githubReviewUrl(taskId),{
        method:"GET",
        cache:"no-store",
        signal:controller.signal,
        headers:{
          "Accept":"application/json"
        }
      });
    }finally{
      window.clearTimeout(timeout);
    }

    if(response.status===404){
      // GitHub is only a speed/cache layer. The source of truth remains Drive.
      // If the deterministic cache is missing, seed it in the background but
      // immediately restore the older reliable Drive-backed review_load path.
      if(!reviewCacheSeedRequested.has(String(taskId))){
        const seeded=submitBridgePost({
          action:"review_cache_seed",
          task_id:String(taskId||"")
        });
        if(seeded) reviewCacheSeedRequested.add(String(taskId));
      }

      setZhReviewLoadState("GitHub 快取缺少・改由 Google Drive 直接載入…","working");
      const fallback=requestReviewData(taskId,"zh",0);
      if(fallback) return;

      if(retry<maxRetries){
        window.setTimeout(
          ()=>loadZhReviewFromGithub(taskId,{retry:retry+1}),
          retry<4 ? 500 : 1000
        );
        return;
      }
      throw new Error("GitHub 快取缺少，且 Google Drive 備援目前未連線。");
    }

    if(!response.ok){
      throw new Error("GitHub HTTP "+response.status);
    }

    const data=await response.json();
    if(!data || !Array.isArray(data.segments)){
      throw new Error("GitHub 快取格式不正確");
    }
    if(data.task_id && String(data.task_id)!==String(taskId)){
      throw new Error("GitHub 快取 task_id 不一致");
    }

    const currentById=new Map(
      currentZhReviewAll.map(x=>[Number(x.id),x])
    );
    const repairedSegments=repairReviewTimings(data.segments);
    const incoming=repairedSegments.map(x=>{
      const id=Number(x.id);
      if(zhDirtySegmentIds.has(id) && currentById.has(id)){
        const current=currentById.get(id);
        return {
          ...x,
          text:current.text,
          confirmed:current.confirmed===true,
          en_text:String(current.en_text||x.en_text||x.source_en||""),
          en_confirmed:current.en_confirmed===true
        };
      }
      return x;
    });

    zhFreshSegments=incoming.slice();
    zhReviewTotal=Number(data.total_segments||incoming.length);
    zhReviewCachedPreview=false;
    zhReviewLoading=false;
    setZhRefreshButtonState(false);
    currentZhReviewAll=incoming.slice();
    zhActiveFilter="all";
    zhVisibleCount=ZH_RENDER_BATCH;

    writeReviewCache({
      task_id:taskId,
      kind:"zh",
      segments:incoming,
      saved_at:Date.now()
    });
    document.querySelectorAll("[data-filter]").forEach(
      x=>x.classList.toggle("active",x.dataset.filter==="all")
    );
    renderSegments(incoming);
    setZhFinalizeEnabled(true);
    setZhReviewLoadState(
      "GitHub 直讀完成・"+incoming.length+" 段",
      "ok"
    );
  }catch(err){
    const isAbort=err && err.name==="AbortError";

    if(isAbort && retry<maxRetries){
      window.setTimeout(
        ()=>loadZhReviewFromGithub(taskId,{retry:retry+1}),
        700
      );
      return;
    }

    zhReviewLoading=false;
    setZhRefreshButtonState(false);
    setZhFinalizeEnabled(false);
    const rawReason=String(err && err.message ? err.message : err);

    // GitHub read problems must never block review while the control center is
    // connected. Fall back to the original Drive-backed chunked loader.
    const fallback=requestReviewData(taskId,"zh",0);
    if(fallback){
      setZhReviewLoadState(
        isAbort
          ? "GitHub 讀取逾時・改由 Google Drive 直接載入…"
          : "GitHub 讀取失敗・改由 Google Drive 直接載入…",
        "working"
      );
      return;
    }

    const reason=isAbort
      ? "GitHub 讀取逾時"
      : (/load failed|failed to fetch/i.test(rawReason)
          ? "GitHub 連線被瀏覽器阻擋，且 Google Drive 備援未連線"
          : rawReason);
    setZhReviewLoadState(reason,"error");

    const el=document.getElementById("segment-list");
    if(el && !currentZhReviewAll.length){
      el.innerHTML=
        '<div class="empty">人工定稿資料讀取失敗：'+
        escapeHtml(reason)+
        '<br><br><button class="ghost" id="retry-github-review">重新讀取 GitHub</button></div>';
      document.getElementById("retry-github-review")?.addEventListener(
        "click",
        ()=>{
          reviewCacheSeedRequested.delete(String(taskId));
          loadZhReviewFromGithub(taskId,{retry:0});
        }
      );
    }
  }
}

function requestReviewData(taskId,kind,chunkIndex=0){
  startReviewTimer(taskId,kind,chunkIndex);
  return jsonpBridgeRequest({
    action:"review_load",
    task_id:taskId,
    kind,
    chunk_index:chunkIndex
  });
}
function quickReviewUrl(task){
  const videoId=youtubeVideoIdFromUrl(task?.url||"");
  const url=new URL("./review.html",window.location.href);
  url.searchParams.set("task",String(task?.id||""));
  if(videoId) url.searchParams.set("video",videoId);
  return url.toString();
}

function openQuickReview(taskId){
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;

  // Quick Review prefers the deterministic GitHub cache, but it must never
  // depend on a previous polish run having published that cache successfully.
  // Seed/rebuild in the background whenever the control center is connected;
  // review-editor.js also has a Drive fallback if GitHub is still propagating.
  if(bridgeKeyValue()){
    submitBridgePost({
      action:"review_cache_seed",
      task_id:String(taskId||"")
    });
  }

  const popup=window.open(quickReviewUrl(task),"_blank");
  if(popup){
    try{
      const key=bridgeKeyValue();
      if(key) popup.sessionStorage.setItem(BRIDGE_SESSION_KEY,key);
    }catch(_){}
  }
}

function renderTasks(){
  const el=document.getElementById("task-list");

  renderPeriodSelector();

  if(!tasks.length){
    el.innerHTML='<div class="empty">尚無任務。到「建立任務」輸入一期四堂課的 YouTube 網址。</div>';
  }else if(!tasksForSelectedPeriod().length){
    el.innerHTML='<div class="empty">這一期目前沒有課程任務。</div>';
  }else{
    const sorted=tasksForSelectedPeriod().slice().sort((a,b)=>{
      if(Number(b.period)!==Number(a.period)) return Number(b.period)-Number(a.period);
      return Number(String(a.lesson).replace(/\D/g,""))-Number(String(b.lesson).replace(/\D/g,""));
    });

    el.innerHTML=sorted.map(raw=>{
      const t=normalizeTask(raw);
      const next=nextStageFor(t);
      const complete=!next;
      const remoteActive=activeRemoteStatus(t);
      const nextRemote=next ? remoteStageStatus(t,next.key) : null;
      return '<article class="course-task-row" data-open-task="'+escapeHtml(t.id)+'">'+
        '<div class="course-task-main">'+
          '<div class="course-task-title">'+
            '<span class="course-lesson">'+escapeHtml(t.lesson)+'</span>'+
            '<div><b>'+escapeHtml(t.title||t.id)+'</b>'+
            '<small>'+escapeHtml(t.course_uid||t.id)+'・第'+escapeHtml(t.period)+'期</small></div>'+
          '</div>'+
          '<div class="course-url" title="'+escapeHtml(t.url)+'">'+escapeHtml(t.url)+'</div>'+
        '</div>'+
        '<div class="course-task-flow">'+
          taskProgressHtml(t)+
          '<div class="course-stage-line">'+
            '<span class="badge '+(complete?"complete":"")+'">'+
              (complete?"全部完成":"下一步："+escapeHtml(next.label))+
            '</span>'+
            '<span class="muted">'+escapeHtml(
              remoteActive
                ? remoteStatusText(remoteActive.status)+
                  (remoteActive.progress ? " "+remoteActive.progress+"%" : "")
                : t.status
            )+'</span>'+
          '</div>'+
        '</div>'+
        '<div class="course-task-actions">'+
          '<button class="ghost task-review-btn" data-review-task="'+escapeHtml(t.id)+'" '+
            (!(remoteStageStatus(t,"zh") && ["needs_review","done"].includes(remoteStageStatus(t,"zh").status)) ? "disabled" : "")+
            '>人工中文定稿</button>'+
          '<button class="ghost task-quick-btn" data-quick-task="'+escapeHtml(t.id)+'" '+
            (!(remoteStageStatus(t,"zh") && ["needs_review","done"].includes(remoteStageStatus(t,"zh").status)) ? "disabled" : "")+
            '>快速流程</button>'+
          '<button class="primary task-next-btn" data-next-task="'+escapeHtml(t.id)+'" '+
            (complete || (nextRemote && ["queued","running"].includes(nextRemote.status)) ? "disabled" : "")+'>'+
            (complete
              ? "已完成"
              : nextRemote && nextRemote.status==="running"
                ? "執行中 "+(nextRemote.progress||"")+"%"
                : nextRemote && nextRemote.status==="queued"
                  ? "排隊中"
                  : nextRemote && nextRemote.status==="error"
                    ? "重新執行"
                    : "執行下一步")+
          '</button>'+
        '</div>'+
      '</article>';
    }).join("");

    document.querySelectorAll("[data-open-task]").forEach(row=>{
      row.addEventListener("click",e=>{
        if(e.target.closest("button")) return;
        openTaskDetail(row.dataset.openTask);
      });
    });

    document.querySelectorAll("[data-review-task]").forEach(btn=>{
      btn.addEventListener("click",e=>{
        e.stopPropagation();
        openTaskReview(btn.dataset.reviewTask);
      });
    });

    document.querySelectorAll("[data-quick-task]").forEach(btn=>{
      btn.addEventListener("click",e=>{
        e.stopPropagation();
        openQuickReview(btn.dataset.quickTask);
      });
    });

    document.querySelectorAll("[data-next-task]").forEach(btn=>{
      btn.addEventListener("click",e=>{
        e.stopPropagation();
        confirmNextStage(btn.dataset.nextTask);
      });
    });
  }

  document.getElementById("stat-tasks").textContent=tasks.length;
  document.getElementById("stat-terms").textContent=terms.length;
  renderYoutubeAudioTasks();
  renderScheduleManager();
}

function scheduleSelectedTask(){
  const select=document.getElementById("schedule-task-select");
  if(!select) return null;
  return tasks.find(x=>String(x.id)===String(select.value)) || null;
}

function scheduleShortTitle(task){
  const raw=String(task?.title||task?.course_uid||task?.id||"未命名課程");
  return raw.split(/[|｜丨]/)[0].trim() || raw;
}

function tasksForSchedulePeriod(period){
  return tasks
    .filter(t=>Number(t.period)===Number(period))
    .slice()
    .sort((a,b)=>
      Number(String(a.lesson||"").replace(/\D/g,""))-
      Number(String(b.lesson||"").replace(/\D/g,""))
    );
}

function resetScheduleDraft(period){
  const current=tasksForSchedulePeriod(period);
  scheduleDraftPeriod=Number(period)||null;
  scheduleDraftOrder=current.map(t=>String(t.id));
  renderScheduleOrderDraft();
}

function renderScheduleOrderDraft(){
  const list=document.getElementById("schedule-order-list");
  const preview=document.getElementById("schedule-preview");
  if(!list) return;

  const period=Number(scheduleDraftPeriod)||0;
  const current=tasksForSchedulePeriod(period);
  const currentIds=current.map(t=>String(t.id));
  const validDraft=
    scheduleDraftOrder.length===currentIds.length &&
    scheduleDraftOrder.slice().sort().join("|")===currentIds.slice().sort().join("|");

  if(!validDraft){
    scheduleDraftOrder=currentIds.slice();
  }

  if(!current.length){
    list.innerHTML='<div class="empty">這一期目前沒有課程。</div>';
    if(preview) preview.textContent="沒有可排序的課程。";
    return;
  }

  const byId=new Map(tasks.map(t=>[String(t.id),t]));
  list.innerHTML=scheduleDraftOrder.map((id,index)=>{
    const t=byId.get(String(id))||{};
    const currentLesson=Number(String(t.lesson||"").replace(/\D/g,""))||0;
    const newLesson=index+1;
    const moved=currentLesson!==newLesson;

    return '<article class="course-task-row">'+
      '<div class="course-task-main">'+
        '<div class="course-task-title">'+
          '<span class="course-lesson">第'+newLesson+'堂</span>'+
          '<div><b>'+escapeHtml(scheduleShortTitle(t))+'</b>'+
          '<small>'+escapeHtml(t.course_uid||t.id||"")+
          (moved ? "・原 "+escapeHtml(t.lesson||"") : "・位置不變")+
          '</small></div>'+
        '</div>'+
      '</div>'+
      '<div class="course-task-actions">'+
        '<button class="ghost" type="button" data-schedule-up="'+index+'" '+
          (index===0?"disabled":"")+'>↑</button>'+
        '<button class="ghost" type="button" data-schedule-down="'+index+'" '+
          (index===scheduleDraftOrder.length-1?"disabled":"")+'>↓</button>'+
      '</div>'+
    '</article>';
  }).join("");

  document.querySelectorAll("[data-schedule-up]").forEach(btn=>{
    btn.addEventListener("click",()=>{
      moveScheduleDraft(Number(btn.dataset.scheduleUp),-1);
    });
  });
  document.querySelectorAll("[data-schedule-down]").forEach(btn=>{
    btn.addEventListener("click",()=>{
      moveScheduleDraft(Number(btn.dataset.scheduleDown),1);
    });
  });

  if(preview){
    const oldText=current.map(t=>scheduleShortTitle(t)).join(" → ");
    const newText=scheduleDraftOrder
      .map(id=>scheduleShortTitle(byId.get(String(id))))
      .join(" → ");
    preview.textContent=
      "目前："+oldText+"｜新順序："+newText+
      (currentIds.join("|")===scheduleDraftOrder.join("|")
        ? "｜尚未變更"
        : "｜按「套用新順序」才會真正更新");
  }
}

function moveScheduleDraft(index,delta){
  const target=index+delta;
  if(
    index<0 || target<0 ||
    index>=scheduleDraftOrder.length ||
    target>=scheduleDraftOrder.length
  ) return;

  const next=scheduleDraftOrder.slice();
  const tmp=next[index];
  next[index]=next[target];
  next[target]=tmp;
  scheduleDraftOrder=next;
  renderScheduleOrderDraft();
}

function renderScheduleManager(){
  const periodSelect=document.getElementById("schedule-period-select");
  const taskSelect=document.getElementById("schedule-task-select");
  const identityList=document.getElementById("schedule-course-list");
  if(!periodSelect || !taskSelect || !identityList) return;

  const periods=[...new Set(
    tasks.map(t=>Number(t.period)||0).filter(Boolean)
  )].sort((a,b)=>b-a);

  const priorPeriod=Number(periodSelect.value)||
    Number(scheduleDraftPeriod)||
    Number(selectedPeriod)||
    periods[0]||0;

  periodSelect.innerHTML=periods.length
    ? periods.map(p=>'<option value="'+p+'">第'+p+'期</option>').join("")
    : '<option value="">尚無期數</option>';

  if(periods.includes(priorPeriod)){
    periodSelect.value=String(priorPeriod);
  }
  const activePeriod=Number(periodSelect.value)||periods[0]||0;

  const activeIds=tasksForSchedulePeriod(activePeriod).map(t=>String(t.id));
  if(
    Number(scheduleDraftPeriod)!==activePeriod ||
    scheduleDraftOrder.slice().sort().join("|")!==activeIds.slice().sort().join("|")
  ){
    scheduleDraftPeriod=activePeriod;
    scheduleDraftOrder=activeIds.slice();
  }

  const sorted=tasks.slice().sort((a,b)=>{
    if(Number(a.period)!==Number(b.period)) return Number(b.period)-Number(a.period);
    return Number(String(a.lesson||"").replace(/\D/g,""))-
      Number(String(b.lesson||"").replace(/\D/g,""));
  });

  const previousTask=String(taskSelect.value||"");
  taskSelect.innerHTML=sorted.length
    ? sorted.map(t=>
        '<option value="'+escapeHtml(t.id)+'">'+
        escapeHtml("第"+t.period+"期 "+t.lesson+"｜"+scheduleShortTitle(t))+
        '</option>'
      ).join("")
    : '<option value="">尚無課程</option>';
  taskSelect.disabled=!sorted.length;
  if(previousTask && sorted.some(t=>String(t.id)===previousTask)){
    taskSelect.value=previousTask;
  }

  const selected=scheduleSelectedTask();
  const periodInput=document.getElementById("schedule-new-period");
  const lessonSelect=document.getElementById("schedule-new-lesson");
  if(selected){
    if(!periodInput.value) periodInput.value=String(selected.period||"");
    if(!lessonSelect.value) lessonSelect.value=String(
      Number(String(selected.lesson||"").replace(/\D/g,""))||1
    );
  }

  identityList.innerHTML=sorted.length ? sorted.map(t=>{
    const moved=Number(t.original_period)&&(
      Number(t.original_period)!==Number(t.period) ||
      String(t.original_lesson||"")!==String(t.lesson||"")
    );
    return '<article class="course-task-row">'+
      '<div class="course-task-main">'+
        '<div class="course-task-title">'+
          '<span class="course-lesson">'+escapeHtml(t.lesson||"—")+'</span>'+
          '<div><b>'+escapeHtml(scheduleShortTitle(t))+'</b>'+
          '<small>'+escapeHtml(t.course_uid||t.id)+'・第'+escapeHtml(t.period)+'期</small></div>'+
        '</div>'+
      '</div>'+
      '<div class="course-task-flow">'+
        '<span class="badge '+(moved?"":"complete")+'">'+
          escapeHtml(moved?"已調課":"原排程")+
        '</span>'+
      '</div>'+
    '</article>';
  }).join("") : '<div class="empty">尚無課程。</div>';

  renderScheduleOrderDraft();
  updateAdvancedSchedulePreview();
}

function updateAdvancedSchedulePreview(){
  const task=scheduleSelectedTask();
  const preview=document.getElementById("schedule-advanced-preview");
  if(!preview) return;
  if(!task){
    preview.textContent="尚未選擇課程。";
    return;
  }

  const newPeriod=Number(document.getElementById("schedule-new-period")?.value)||0;
  const newLesson=Number(document.getElementById("schedule-new-lesson")?.value)||0;
  if(!newPeriod || !newLesson){
    preview.textContent="請選擇新的期數與堂次。";
    return;
  }

  const occupant=tasks.find(t=>
    String(t.id)!==String(task.id) &&
    Number(t.period)===newPeriod &&
    Number(String(t.lesson||"").replace(/\D/g,""))===newLesson
  );

  preview.textContent=
    scheduleShortTitle(task)+"｜目前：第"+task.period+"期 "+task.lesson+
    " → 新位置：第"+newPeriod+"期 第"+newLesson+"堂"+
    (occupant
      ? "；目的位置已有「"+scheduleShortTitle(occupant)+"」，會交換兩堂。"
      : "；目的位置目前沒有課程。");
}

function applyPeriodReorder(){
  const status=document.getElementById("schedule-status");
  const state=document.getElementById("schedule-state");
  const button=document.getElementById("schedule-apply-order");
  const period=Number(scheduleDraftPeriod)||0;

  if(!period || !scheduleDraftOrder.length){
    if(status) status.textContent="這一期沒有可排序的課程。";
    return;
  }
  if(bridgeProtocolVersion<REQUIRED_BRIDGE_PROTOCOL){
    if(status) status.textContent=
      "Apps Script 控制中心版本過舊，目前 v"+bridgeProtocolVersion+
      "，需要 v"+REQUIRED_BRIDGE_PROTOCOL+"。";
    return;
  }

  const current=tasksForSchedulePeriod(period).map(t=>String(t.id));
  if(current.join("|")===scheduleDraftOrder.join("|")){
    if(status) status.textContent="順序沒有變更，不需要送出。";
    return;
  }

  const sent=submitBridgePost({
    action:"period_reorder",
    period:String(period),
    ordered_task_ids:scheduleDraftOrder.join(",")
  });
  if(!sent){
    if(status) status.textContent="排序工作未送出，請重新連線控制中心。";
    return;
  }

  if(button) button.disabled=true;
  if(state){
    state.textContent="排序中";
    state.className="badge";
  }
  if(status){
    status.textContent=
      "正在一次更新第"+period+"期課表與 Drive 資料夾；不會逐堂交換。";
  }
}

function applyScheduleChange(){
  const task=scheduleSelectedTask();
  const status=document.getElementById("schedule-status");
  const state=document.getElementById("schedule-state");
  const button=document.getElementById("schedule-apply");

  if(!task){
    if(status) status.textContent="請先選擇課程。";
    return;
  }
  if(bridgeProtocolVersion<REQUIRED_BRIDGE_PROTOCOL){
    if(status) status.textContent=
      "Apps Script 控制中心版本過舊，目前 v"+bridgeProtocolVersion+
      "，需要 v"+REQUIRED_BRIDGE_PROTOCOL+"。";
    return;
  }

  const newPeriod=Number(document.getElementById("schedule-new-period")?.value)||0;
  const newLesson=Number(document.getElementById("schedule-new-lesson")?.value)||0;
  if(!newPeriod || !newLesson){
    if(status) status.textContent="請填入新的期數與堂次。";
    return;
  }

  const sent=submitBridgePost({
    action:"task_reschedule",
    task_id:task.id,
    new_period:String(newPeriod),
    new_lesson:String(newLesson)
  });
  if(!sent){
    if(status) status.textContent="調課工作未送出，請重新連線控制中心。";
    return;
  }

  if(button) button.disabled=true;
  if(state){
    state.textContent="調整中";
    state.className="badge";
  }
  if(status) status.textContent="正在執行進階單堂調課…";
}

function youtubeAudioSelectedTask(){
  const select=document.getElementById("youtube-audio-task");
  if(!select) return null;
  return tasks.find(x=>String(x.id)===String(select.value)) || null;
}

function youtubeCaptureSelectedPeriod(){
  return Number(document.getElementById("youtube-capture-period")?.value)||null;
}

function formatCaptureFileSize(bytes){
  const value=Number(bytes||0);
  if(!value) return "";
  if(value>=1024*1024) return (value/(1024*1024)).toFixed(value>=10*1024*1024?0:1)+" MB";
  if(value>=1024) return Math.round(value/1024)+" KB";
  return value+" B";
}

function captureStateInfo(task,kind,files){
  const list=Array.isArray(files)?files:[];
  const remote=task?.remoteStages?.[kind==="cc" ? "cc" : "youtube-audio"] || null;
  const status=String(remote?.status||"").toLowerCase();
  const message=String(remote?.message||remote?.error_message||"").trim();

  if(status==="running" || status==="queued"){
    return {key:"working",label:"執行中",detail:message || "Kaggle 正在處理這項抓取工作。"};
  }
  if(status==="done"){
    if(message.includes("NO_YOUTUBE_CC")){
      return {
        key:"idle",
        label:"無可用 CC",
        detail:"YouTube 沒有提供字幕軌；請改用中文 ASR，外語由 SoulKey 翻譯流程產生。"
      };
    }
    const match=message.match(/(\d+)\/(\d+)\s*語言完成/);
    const partial=match && Number(match[1])<Number(match[2]);
    return {
      key:partial ? "partial" : "complete",
      label:partial ? "部分完成" : "已抓取完成",
      detail:message || (
        list.length
          ? "雲端目前有 "+list.length+" 個檔案。"
          : "工作已完成，正在同步雲端檔案。"
      )
    };
  }
  if(status==="error"){
    if(list.length){
      return {
        key:"partial",
        label:"部分檔案已存在",
        detail:"最近一次執行失敗，但 Drive 已有 "+list.length+" 個檔案。"+(message ? "｜"+message : "")
      };
    }
    return {key:"error",label:"執行失敗",detail:message || "最近一次抓取工作失敗。"};
  }
  if(status==="stale"){
    return {
      key:list.length ? "partial" : "error",
      label:list.length ? "部分檔案已存在" : "需重新執行",
      detail:message || "目前結果已標記為過期。"
    };
  }
  if(list.length){
    return {key:"complete",label:"已抓取完成",detail:"Drive 已找到 "+list.length+" 個檔案。"};
  }
  return {key:"idle",label:"未執行",detail:"尚未找到執行紀錄或雲端檔案。"};
}

function setCaptureState(kind,info){
  const label=document.getElementById(kind==="cc" ? "youtube-cc-state-label" : "youtube-audio-state-label");
  const detail=document.getElementById(kind==="cc" ? "youtube-cc-state-detail" : "youtube-audio-state-detail");
  if(label){
    label.className="capture-state state-"+String(info.key||"idle");
    label.textContent=info.label||"未執行";
  }
  if(detail) detail.textContent=info.detail||"";
}

function visibleYoutubeCaptureFiles(kind,files){
  const list=Array.isArray(files)?files:[];
  return list.filter(file=>{
    const raw=String(file?.name||"");
    const display=String(file?.display_name||raw);

    // General users do not need implementation files in the Studio list.
    if(/\.json$/i.test(raw) || /\.json$/i.test(display)) return false;
    if(/\.srt$/i.test(raw) || /\.srt$/i.test(display)) return false;

    if(kind==="cc"){
      // CC list exposes only the pure transcript.  Keep the timeline TXT on
      // Drive for downstream processing but do not show it in Studio.
      return (
        /\.transcript\.txt$/i.test(raw) ||
        /CC純逐字稿\.txt$/i.test(display)
      );
    }

    if(kind==="audio"){
      return /\.mp3$/i.test(raw) || /音軌\.mp3$/i.test(display);
    }

    return true;
  });
}

function renderCaptureFileList(containerId,files,emptyText){
  const host=document.getElementById(containerId);
  if(!host) return;
  const list=Array.isArray(files)?files:[];
  if(!list.length){
    host.innerHTML='<div class="empty">'+escapeHtml(emptyText)+'</div>';
    return;
  }

  host.innerHTML=list.map(file=>{
    const updated=file.updated_at ? new Date(file.updated_at).toLocaleString() : "";
    const size=formatCaptureFileSize(file.size);
    return '<div class="youtube-cloud-file">'+
      '<div class="youtube-cloud-file-main">'+
        '<b>'+escapeHtml(file.display_name||file.name||"未命名檔案")+'</b>'+
        '<span>'+escapeHtml([size,updated].filter(Boolean).join("・"))+'</span>'+
      '</div>'+
      '<a href="'+escapeHtml(file.url||"#")+'" target="_blank" rel="noopener">開啟雲端檔案</a>'+
    '</div>';
  }).join("");
}

function renderYoutubeCaptureFiles(task){
  const payload=task ? youtubeCaptureFilesCache[task.id] : null;
  const ccFiles=payload?.cc_files || [];
  const asrFiles=payload?.asr_files || [];
  const audioFiles=payload?.audio_files || [];
  const visibleCcFiles=visibleYoutubeCaptureFiles("cc",ccFiles);
  const visibleAsrFiles=visibleYoutubeCaptureFiles("asr",asrFiles);
  const visibleAudioFiles=visibleYoutubeCaptureFiles("audio",audioFiles);

  renderCaptureFileList(
    "youtube-asr-files",
    visibleAsrFiles,
    task ? "尚未產生中文 ASR 檔案。" : "尚未選擇課程。"
  );
  renderCaptureFileList(
    "youtube-cc-files",
    visibleCcFiles,
    task ? "尚未產生可閱讀的外語 CC 純逐字稿。" : "尚未選擇課程."
  );
  renderCaptureFileList(
    "youtube-audio-files",
    visibleAudioFiles,
    task ? "尚未抓取任何 YouTube 音軌檔案。" : "尚未選擇課程。"
  );

  const asrFolder=document.getElementById("youtube-asr-folder-link");
  const ccFolder=document.getElementById("youtube-cc-folder-link");
  const audioFolder=document.getElementById("youtube-audio-folder-link");
  if(asrFolder){
    asrFolder.hidden=!payload?.transcript_folder_url;
    asrFolder.href=payload?.transcript_folder_url || "#";
  }
  if(ccFolder){
    ccFolder.hidden=!payload?.source_folder_url;
    ccFolder.href=payload?.source_folder_url || "#";
  }
  if(audioFolder){
    audioFolder.hidden=!payload?.audio_folder_url;
    audioFolder.href=payload?.audio_folder_url || "#";
  }

  setCaptureState("cc",captureStateInfo(task,"cc",ccFiles));
  setCaptureState("audio",captureStateInfo(task,"audio",audioFiles));

  const badge=document.getElementById("youtube-capture-files-state");
  if(badge && payload){
    badge.textContent="可使用 "+(visibleAsrFiles.length+visibleCcFiles.length+visibleAudioFiles.length)+" 個檔案";
    badge.className="badge complete";
  }
}

function requestYoutubeCaptureFiles(taskId,force=false){
  const id=String(taskId||"").trim();
  if(!id) return false;
  const age=Date.now()-Number(youtubeCaptureFilesFetchedAt[id]||0);
  if(!force && youtubeCaptureFilesCache[id] && age<30000) return true;
  if(youtubeCaptureFilesLoadingTask===id && !force) return true;

  youtubeCaptureFilesLoadingTask=id;
  const badge=document.getElementById("youtube-capture-files-state");
  if(badge){
    badge.textContent="正在讀取 Drive…";
    badge.className="badge";
  }

  const fields={action:"youtube_capture_files",task_id:id};
  const sent=bridgeClientRequest(fields) || jsonpBridgeRequest(fields);
  if(!sent){
    youtubeCaptureFilesLoadingTask="";
    if(badge){
      badge.textContent="尚未連線控制中心";
      badge.className="badge";
    }
  }
  return sent;
}

function renderYoutubeAudioTasks(forceFiles=false){
  const periodSelect=document.getElementById("youtube-capture-period");
  const taskSelect=document.getElementById("youtube-audio-task");
  const info=document.getElementById("youtube-audio-task-info");
  if(!taskSelect) return;

  const periods=availablePeriods();
  if(periodSelect){
    const previousPeriod=Number(periodSelect.value)||null;
    periodSelect.innerHTML=periods.length
      ? periods.map(p=>'<option value="'+p+'">第 '+p+' 期</option>').join("")
      : '<option value="">尚無期數</option>';
    if(previousPeriod && periods.includes(previousPeriod)){
      periodSelect.value=String(previousPeriod);
    }else if(periods.length){
      periodSelect.value=String(periods[0]);
    }
    periodSelect.disabled=!periods.length;
  }

  const period=youtubeCaptureSelectedPeriod();
  const filtered=tasks
    .filter(t=>Number(t.period)===Number(period))
    .sort((a,b)=>
      Number(String(a.lesson).replace(/\D/g,""))-
      Number(String(b.lesson).replace(/\D/g,""))
    );

  const previousTask=String(taskSelect.value||"");
  if(!filtered.length){
    taskSelect.innerHTML='<option value="">這一期尚無課程</option>';
    taskSelect.disabled=true;
    if(info) info.textContent="這一期目前沒有可抓取的課程任務。";
    renderYoutubeCaptureFiles(null);
    return;
  }

  taskSelect.disabled=false;
  taskSelect.innerHTML=filtered.map(task=>
    '<option value="'+escapeHtml(task.id)+'">'+
      escapeHtml(task.lesson)+"｜"+escapeHtml(task.title||task.id)+
    '</option>'
  ).join("");
  if(previousTask && filtered.some(x=>String(x.id)===previousTask)){
    taskSelect.value=previousTask;
  }

  const task=youtubeAudioSelectedTask();
  if(info){
    info.innerHTML=task
      ? '<div class="youtube-capture-task-info">'+
          '<div><b>'+escapeHtml(task.id)+'</b><span>第'+escapeHtml(task.period)+'期・'+escapeHtml(task.lesson)+'</span></div>'+
          '<a href="'+escapeHtml(task.url||"#")+'" target="_blank" rel="noopener">'+escapeHtml(task.url||"尚無 YouTube URL")+'</a>'+
        '</div>'
      : "尚未選擇課程。";
  }

  renderYoutubeCaptureFiles(task);
  if(task){
    const age=Date.now()-Number(youtubeCaptureFilesFetchedAt[task.id]||0);
    if(forceFiles || !youtubeCaptureFilesCache[task.id] || age>=30000){
      requestYoutubeCaptureFiles(task.id,forceFiles);
    }
  }
}

function youtubeCaptureMode(){
  return String(
    document.querySelector('input[name="youtube-capture-type"]:checked')?.value || "cc"
  );
}

function syncYoutubeCaptureModeUi(){
  const mode=youtubeCaptureMode();
  const audioOptions=document.getElementById("youtube-audio-options");
  const button=document.getElementById("youtube-audio-run");
  const status=document.getElementById("youtube-audio-status");

  if(audioOptions) audioOptions.hidden=mode!=="audio";
  if(button) button.textContent=mode==="cc" ? "抓取 CC 字幕" : "抓取音軌";
  if(status && !/已送出|Kaggle|完成|錯誤|處理中/.test(String(status.textContent||""))){
    status.textContent=mode==="cc"
      ? "將抓取 YouTube 目前可取得的多語 CC 字幕。"
      : "將抓取 YouTube 目前可取得的多語音軌。";
  }
}

function youtubeAudioRequestedLangs(){
  const all=document.getElementById("youtube-audio-all");
  if(all?.checked) return "all";

  const selected=[...document.querySelectorAll("[data-youtube-audio-lang]:checked")]
    .map(x=>String(x.value||"").trim())
    .filter(Boolean);
  const custom=String(document.getElementById("youtube-audio-custom-langs")?.value||"")
    .split(",")
    .map(x=>x.trim())
    .filter(Boolean);
  return [...new Set([...selected,...custom])].join(",");
}

function runYoutubeAudioGrab(){
  const task=youtubeAudioSelectedTask();
  const status=document.getElementById("youtube-audio-status");
  const button=document.getElementById("youtube-audio-run");
  const mode=youtubeCaptureMode();

  if(!task){
    if(status) status.textContent="請先選擇期數與課程。";
    return;
  }
  if(!task.url){
    if(status) status.textContent="這堂課沒有 YouTube URL。";
    return;
  }

  let langs="";
  if(mode==="audio"){
    langs=youtubeAudioRequestedLangs();
    if(!langs){
      if(status) status.textContent="請勾選至少一個語言，或改選「全部可用音軌」。";
      return;
    }
  }

  if(!bridgeKeyValue() || !bridgeEndpointValue()){
    if(status) status.textContent="尚未連線控制中心；請先回總覽輸入 Bridge Key。";
    return;
  }
  if(bridgeProtocolVersion<=0){
    if(status) status.textContent="控制中心尚未回報 Bridge 版本，請重新連線後再試。";
    return;
  }
  if(bridgeProtocolVersion<REQUIRED_BRIDGE_PROTOCOL){
    if(status){
      status.textContent=
        "Apps Script 控制中心版本過舊：目前 v"+bridgeProtocolVersion+
        "，需要 v"+REQUIRED_BRIDGE_PROTOCOL+"。";
    }
    return;
  }

  const payload={action:"run_stage",task_id:task.id,stage:"cc"};
  if(mode==="audio"){
    payload.lang="multi-audio";
    payload.langs=langs;
  }

  const sent=submitBridgePost(payload);
  if(!sent){
    if(status) status.textContent="YouTube 抓取工作未送出，請重新連線控制中心後再試。";
    return;
  }

  if(button) button.disabled=true;
  if(status){
    status.textContent=mode==="cc"
      ? "已送出｜抓取所有可用 CC 字幕"
      : "已送出｜"+(langs==="all" ? "抓取全部可用音軌" : "指定音軌語言："+langs);
  }

  const stateInfo={key:"working",label:"執行中",detail:"Kaggle 已收到抓取工作，等待處理。"};
  setCaptureState(mode==="cc"?"cc":"audio",stateInfo);

  window.setTimeout(()=>{
    if(button) button.disabled=false;
    requestTaskStatuses();
  },1800);
}

function stageState(task,index){
  normalizeTask(task);
  const stage=workflow[index];
  const remote=remoteStageStatus(task,stage.key);

  if(remote){
    if(remote.status==="done") return "done";
    if(remote.status==="running") return "running";
    if(remote.status==="queued") return "queued";
    if(remote.status==="needs_review") return "needs-review";
    if(remote.status==="error") return "error";
    if(remote.status==="stale") return "stale";
  }

  if(index<=task.completedStep) return "done";
  if(index===task.completedStep+1) return "current";
  return "locked";
}


function normalizedLanguagePlan(task){
  const current=Array.isArray(task.languagePlan) ? task.languagePlan : [];
  const byCode=Object.fromEntries(current.map(x=>[x.language_code || x.code,x]));

  return languageSettings.map(lang=>{
    const saved=byCode[lang.code] || {};
    const english = lang.code==="en";
    return {
      language_code:lang.code,
      language_name:lang.name,
      transcript_enabled:english ? true : !!saved.transcript_enabled,
      transcript_source:english ? "human" : (saved.transcript_source || "ai"),
      audio_enabled:!!saved.audio_enabled,
      audio_source:saved.audio_source || "tts"
    };
  });
}

function renderLanguagePlan(task){
  const list=document.getElementById("language-plan-list");
  const status=document.getElementById("language-plan-status");
  if(!list || !task) return;

  const plan=normalizedLanguagePlan(task);

  list.innerHTML=plan.map(item=>{
    const lang=languageSettings.find(x=>x.code===item.language_code) || {};
    const aiDisabled=!lang.can_ai_translate;
    const ttsDisabled=!lang.can_tts;
    const english=item.language_code==="en";
    return '<article class="language-plan-row" data-lang-plan="'+escapeHtml(item.language_code)+'">'+
      '<div class="language-name"><b>'+escapeHtml(item.language_name)+'</b><small>'+escapeHtml(item.language_code)+'</small></div>'+
      '<div class="language-output-cell">'+
        '<label class="output-toggle"><input type="checkbox" data-plan-transcript '+(item.transcript_enabled?"checked":"")+' '+(english?"disabled":"")+'> '+(english?"英文定稿":"需要文稿")+'</label>'+
        '<select data-plan-transcript-source '+((!item.transcript_enabled||english)?"disabled":"")+'>'+
          '<option value="ai" '+(item.transcript_source==="ai"?"selected":"")+' '+(aiDisabled?"disabled":"")+'>AI 翻譯</option>'+
          '<option value="human" '+(item.transcript_source==="human"?"selected":"")+'>'+(english?"English CC 定稿":"真人翻譯／人工提供")+'</option>'+
        '</select>'+
      '</div>'+
      '<div class="language-output-cell">'+
        '<label class="output-toggle"><input type="checkbox" data-plan-audio '+(item.audio_enabled?"checked":"")+'> 需要音檔</label>'+
        '<select data-plan-audio-source '+(!item.audio_enabled?"disabled":"")+'>'+
          '<option value="tts" '+(item.audio_source==="tts"?"selected":"")+' '+(ttsDisabled?"disabled":"")+'>AI TTS</option>'+
          '<option value="human" '+(item.audio_source==="human"?"selected":"")+'>真人錄音</option>'+
        '</select>'+
      '</div>'+
    '</article>';
  }).join("");

  if(status){
    const selected=plan.filter(x=>x.transcript_enabled || x.audio_enabled).length;
    status.textContent=selected
      ? "目前已選 "+selected+" 種語言；尚未變更前可直接調整。"
      : "尚未選擇任何目標語言；不會自動把全部語言送去 Kaggle。";
  }

  document.querySelectorAll(".language-plan-row").forEach(row=>{
    const transcript=row.querySelector("[data-plan-transcript]");
    const transcriptSource=row.querySelector("[data-plan-transcript-source]");
    const audio=row.querySelector("[data-plan-audio]");
    const audioSource=row.querySelector("[data-plan-audio-source]");

    transcript?.addEventListener("change",()=>{
      transcriptSource.disabled=!transcript.checked;
    });
    audio?.addEventListener("change",()=>{
      audioSource.disabled=!audio.checked;
      if(audio.checked && audioSource.value==="tts" && !transcript.checked){
        transcript.checked=true;
        transcriptSource.disabled=false;
      }
    });
    audioSource?.addEventListener("change",()=>{
      if(audio.checked && audioSource.value==="tts" && !transcript.checked){
        transcript.checked=true;
        transcriptSource.disabled=false;
      }
    });
  });
}

function collectLanguagePlan(){
  return [...document.querySelectorAll(".language-plan-row")].map(row=>{
    const code=row.dataset.langPlan;
    const lang=languageSettings.find(x=>x.code===code) || {name:code};
    return {
      language_code:code,
      language_name:lang.name || code,
      transcript_enabled:!!row.querySelector("[data-plan-transcript]")?.checked,
      transcript_source:row.querySelector("[data-plan-transcript-source]")?.value || "ai",
      audio_enabled:!!row.querySelector("[data-plan-audio]")?.checked,
      audio_source:row.querySelector("[data-plan-audio-source]")?.value || "tts"
    };
  });
}

function saveLanguagePlanForSelectedTask(){
  const task=tasks.find(x=>x.id===selectedTaskId);
  if(!task) return;

  const plan=collectLanguagePlan();
  task.languagePlan=plan;
  save(STORE.tasks,tasks);

  const selected=plan.filter(x=>x.transcript_enabled || x.audio_enabled);
  const status=document.getElementById("language-plan-status");

  if(!selected.length){
    if(status) status.textContent="已儲存：本堂課目前不需要任何其他語言輸出。";
  }else{
    if(status) status.textContent="已儲存 "+selected.length+" 種語言設定，正在同步控制中心…";
  }

  const sent=submitBridgePost({
    action:"language_plan_save",
    task_id:task.id,
    plan_json:JSON.stringify(plan)
  });

  if(!sent && status){
    status.textContent="已儲存在目前瀏覽器；Bridge 連線後會再同步中央控制表。";
  }
}

function requestLanguageSettings(){
  return jsonpBridgeRequest({action:"language_settings"});
}

function requestLanguagePlan(taskId){
  if(!taskId) return false;
  return jsonpBridgeRequest({action:"language_plan_get",task_id:taskId});
}

function renderTaskDetail(task){
  normalizeTask(task);
  renderLanguagePlan(task);
  const next=nextStageFor(task);
  const nextIndex=task.completedStep+1;

  document.getElementById("detail-title").textContent=
    "第"+task.period+"期・"+task.lesson;

  document.getElementById("detail-meta").innerHTML=
    '<b>'+escapeHtml(task.id)+'</b>'+
    '<span>'+escapeHtml(task.status)+'</span>'+
    '<small>'+escapeHtml(task.url)+'</small>';

  document.getElementById("detail-stage-list").innerHTML=workflow.map((stage,i)=>{
    const state=stageState(task,i);
    const remote=remoteStageStatus(task,stage.key);
    const label=remote
      ? remoteStatusText(remote.status)+(remote.progress ? " "+remote.progress+"%" : "")
      : state==="done"?"已完成":state==="current"?"目前步驟":"尚未開放";
    const reviewStage=["zh","en-review"].includes(stage.key);
    return '<button class="detail-stage '+state+'" data-detail-stage="'+i+'" '+(state==="locked"?"disabled":"")+'>'+
      '<span class="detail-stage-number">'+String(i+1).padStart(2,"0")+'</span>'+
      '<div><b>'+escapeHtml(stage.label)+'</b><small>'+label+'・'+escapeHtml(stage.hint)+'</small></div>'+
      (reviewStage?'<em>'+(stage.key==="en-review"?"英文定稿":"中文定稿")+'</em>':'')+
    '</button>';
  }).join("");

  const current=next || workflow[workflow.length-1];
  const zhRemote = next && next.key==="zh" ? remoteStageStatus(task,"zh") : null;
  const isChineseReview = next && next.key==="zh" && zhRemote && zhRemote.status==="needs_review";
  const isEnglishReview = next && next.key==="en-review";
  document.getElementById("detail-current-title").textContent=
    next ? next.label : "全部流程完成";

  if(!next){
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message success"><b>這堂課已全部完成</b><span>所有流程均已完成。</span></div>';
  }else if(isChineseReview){
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message review-ready">'+
        '<div><b>現在要進行人工中文定稿</b><span>左側查看 ASR 中文逐字稿，右側查看 AI 中文校稿結果；右側可直接修改成最終版本。</span></div>'+
        '<button class="primary" data-open-review-inline="'+escapeHtml(task.id)+'">進入人工中文定稿</button>'+
      '</div>';
  }else if(isEnglishReview){
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message review-ready">'+
        '<div><b>現在要進行English CC 定稿</b><span>逐段查看中文 Final 與英文稿（YouTube CC 或 AI 翻譯），修正後同步學習專有名詞的正式英文譯法。</span></div>'+
        '<button class="primary" data-open-en-review-inline="'+escapeHtml(task.id)+'">進入English CC 定稿</button>'+
      '</div>';
  }else{
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message">'+
        '<div><b>下一步：'+escapeHtml(next.label)+'</b><span>'+escapeHtml(next.hint)+' 工作。確認後才會執行這堂課的下一階段。</span></div>'+
      '</div>';
  }

  const previousBtn=document.getElementById("detail-previous-btn");
  previousBtn.disabled=task.completedStep < 0;
  previousBtn.onclick=()=>rollbackPreviousStage(task.id);

  const reviewBtn=document.getElementById("detail-review-btn");
  const zhStatus=remoteStageStatus(task,"zh");
  reviewBtn.hidden = !(zhStatus && ["needs_review","done"].includes(zhStatus.status));
  reviewBtn.textContent="開啟快速流程";
  reviewBtn.onclick=()=>openQuickReview(task.id);

  const nextBtn=document.getElementById("detail-next-btn");
  const nextRemote=next ? remoteStageStatus(task,next.key) : null;
  nextBtn.disabled=!next || !!(nextRemote && ["queued","running"].includes(nextRemote.status));
  const humanReviewNext=next && next.key==="en-review";
  const zhNeedsReview=next && next.key==="zh" && nextRemote && nextRemote.status==="needs_review";
  nextBtn.textContent=next
    ? (zhNeedsReview ? "進入：人工中文定稿" : humanReviewNext ? "進入："+next.label : "執行下一步："+next.label)
    : "已全部完成";
  nextBtn.onclick=()=>{
    if(!next) return;
    if(next.key==="zh" && nextRemote && nextRemote.status==="needs_review") return openTaskReview(task.id);
    if(next.key==="en-review") return openEnglishReview(task.id);
    return confirmNextStage(task.id);
  };

  document.querySelectorAll("[data-open-review-inline]").forEach(btn=>{
    btn.addEventListener("click",()=>openTaskReview(btn.dataset.openReviewInline));
  });

  document.querySelectorAll("[data-open-en-review-inline]").forEach(btn=>{
    btn.addEventListener("click",()=>openEnglishReview(btn.dataset.openEnReviewInline));
  });

  document.querySelectorAll("[data-detail-stage]").forEach(btn=>{
    btn.addEventListener("click",()=>{
      const index=Number(btn.dataset.detailStage);
      const stage=workflow[index];
      if(stage.key==="zh"){
        const zh=remoteStageStatus(task,"zh");
        if(zh && ["needs_review","done"].includes(zh.status)) openTaskReview(task.id);
      }else if(stage.key==="en-review"){
        openEnglishReview(task.id);
      }
    });
  });
}

function rollbackPreviousStage(taskId){
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;
  normalizeTask(task);

  if(task.completedStep < 0){
    alert("目前已經是第一個步驟，無法再退回。");
    return;
  }

  const reopenIndex=task.completedStep;
  const reopenStage=workflow[reopenIndex];

  const ok=confirm(
    task.id+"｜"+task.lesson+"\n\n"+
    "確定退回上一步並重新開啟「"+reopenStage.label+"」？\n\n"+
    "已產生的檔案不會刪除；正式後端會把後續結果標記為需要重新確認，避免誤用舊版本。"
  );
  if(!ok) return;

  task.completedStep=Math.max(-1, task.completedStep-1);
  task.status="已退回："+reopenStage.label;
  task.rollbackAt=new Date().toISOString();
  task.rollbackStage=reopenStage.key;

  save(STORE.tasks,tasks);
  renderTasks();
  renderTaskDetail(task);
}

function openTaskDetail(taskId){
  selectedTaskId=taskId;
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;
  renderTaskDetail(task);
  requestLanguagePlan(task.id);
  showView("task-detail");
}

function openTaskReview(taskId){
  selectedTaskId=taskId;
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;

  const context=document.getElementById("review-task-context");
  context.innerHTML=
    '<b>'+escapeHtml(task.id)+'</b>'+
    '<span>第'+escapeHtml(task.period)+'期・'+escapeHtml(task.lesson)+'</span>'+
    '<small>'+escapeHtml(task.url)+'</small>';

  document.getElementById("current-time").textContent="--:--";
  setZhFinalizeEnabled(false);
  zhFreshSegments=[];
  zhReviewLoading=true;
  zhReviewTotal=0;
  zhDirtySegmentIds=new Set();
  zhVisibleCount=ZH_RENDER_BATCH;
  zhActiveFilter="all";
  zhGithubSaveInFlight=false;
  zhGithubSaveQueued=false;
  zhGithubRevision=0;
  zhGithubLastSavedRevision=0;
  zhGithubSaveRevisionInFlight=0;

  const cached=readReviewCache(task.id,"zh");
  zhReviewCachedPreview=!!cached;
  if(cached){
    currentZhReviewAll=(cached.segments||[]).slice();
    renderSegments(currentZhReviewAll);
    setZhReviewLoadState("先顯示本機快取・同步 GitHub 最新版","working");
  }else{
    currentZhReview=[];
    currentZhReviewAll=[];
    document.getElementById("segment-list").innerHTML='<div class="empty">正在直接讀取 GitHub 人工定稿資料…</div>';
    setZhReviewLoadState("GitHub 直讀中…","working");
  }

  showView("review");
  mountReviewYouTubePlayer(task);
  loadZhReviewFromGithub(task.id);
}

function confirmNextStage(taskId){
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;
  normalizeTask(task);
  const next=nextStageFor(task);
  if(!next) return;

  const currentRemote=remoteStageStatus(task,next.key);
  if(next.key==="zh" && currentRemote && currentRemote.status==="needs_review") return openTaskReview(task.id);

  // Cookies are an optional fallback only. Production source acquisition
  // now tries bgutil guest PO tokens / anonymous clients first, so missing
  // YOUTUBE_COOKIES_B64 must never block a normal Chinese-stage launch.
  if(next.key==="en-review") return openEnglishReview(task.id);

  let langs="";
  if(next.key==="multi"){
    const plan=normalizedLanguagePlan(task);
    langs=plan
      .filter(x=>x.language_code!=="en" && x.transcript_enabled && x.transcript_source==="ai")
      .map(x=>x.language_code)
      .join(",");
    if(!langs){
      alert("這堂課沒有勾選需要 AI 翻譯的其他語言。請先到「各國語言輸出設定」選擇語言，或等待真人翻譯文稿完成。");
      return;
    }
  }

  if(next.key==="tts"){
    const plan=normalizedLanguagePlan(task);
    langs=plan
      .filter(x=>x.audio_enabled && x.audio_source==="tts")
      .map(x=>x.language_code)
      .join(",");
    if(!langs){
      alert("這堂課沒有勾選需要 AI TTS 的語言。請先選擇音檔語言，或等待真人錄音完成。");
      return;
    }
  }

  const remote=remoteStageStatus(task,next.key);
  const retry=remote && ["error","stale"].includes(remote.status);

  const ok=confirm(
    task.id+"｜"+task.lesson+"\n\n"+
    (retry?"重新執行：":"確定執行下一步驟：")+"\n"+next.label+"？\n\n"+
    "確認後會送到 GitHub Actions，再啟動 Kaggle Web Worker。完成前下一步會保持鎖定。"
  );
  if(!ok) return;

  const dispatchStage=next.key==="zh" ? "zh" : next.key;
  const sent=submitBridgePost({
    action:"run_stage",
    task_id:task.id,
    stage:dispatchStage,
    lang:"",
    langs
  });

  if(!sent){
    alert("尚未設定 Apps Script Web App URL 或 Bridge Key。");
    return;
  }

  task.status="排隊中："+next.label;
  task.remoteStages=task.remoteStages||{};
  task.remoteStages[next.key]={
    task_id:task.id,
    stage:next.key,
    status:"queued",
    progress:"0",
    message:"已送出 Kaggle Web Job"
  };
  save(STORE.tasks,tasks);
  renderTasks();

  if(currentView==="task-detail" && selectedTaskId===task.id){
    renderTaskDetail(task);
  }

  window.setTimeout(()=>requestTaskStatuses(),1800);
}
function taskAtSchedulePosition(period,lessonNo){
  return tasks.find(t=>
    Number(t.period)===Number(period) &&
    Number(String(t.lesson||"").replace(/\D/g,""))===Number(lessonNo)
  ) || null;
}

function availableLegacyTaskId(period,lessonNo){
  const base="P"+period+"-L"+String(lessonNo).padStart(2,"0");
  if(!tasks.some(t=>String(t.id)===base)) return base;
  let n=2;
  while(tasks.some(t=>String(t.id)===base+"-R"+n)) n++;
  return base+"-R"+n;
}

function updateTaskCodes(){
  const period=Number(document.getElementById("period").value)||0;
  for(let i=1;i<=4;i++){
    const existing=taskAtSchedulePosition(period,i);
    const id=existing?.id || availableLegacyTaskId(period,i);
    const code=document.getElementById("task-code-"+i);
    if(code){
      code.textContent=existing
        ? ((existing.course_uid||id)+" · 已建立")
        : id;
    }
  }
}
document.getElementById("dashboard-period")?.addEventListener("change",e=>{
  selectedPeriod=Number(e.target.value)||null;
  renderTasks();
});

document.getElementById("run-p255-batch")?.addEventListener("click",()=>{
  if(!bridgeKeyValue()){
    alert("請先在總覽輸入 Bridge Key 並連線控制中心。");
    document.getElementById("dashboard-bridge-key")?.focus();
    return;
  }

  const available = ["P255-L01","P255-L02"].filter(id=>
    tasks.some(task=>String(task.id||"")===id)
  );
  if(available.length!==2){
    alert("控制中心目前找不到 P255-L01 與 P255-L02 兩堂完整任務，請先同步控制中心。");
    return;
  }

  const ok=confirm(
    "確定直接跑完第255期兩堂課？\n\n"+
    "會執行：Taiwan-Breeze ASR → Gemini 中文/英文/六語 QA → Meta MMS 七語 TTS → 字幕輸出。\n"+
    "這次採批次自動定稿，Final 會標示 batch_auto_user_requested。"
  );
  if(!ok) return;

  // Give each lesson its own authenticated runtime nonce and GitHub/Kaggle
  // job. GitHub keeps them serial via the workflow concurrency group, but a
  // long P255-L01 can no longer consume P255-L02's runtime/timeout budget.
  const sentL01=submitBridgePost({
    action:"run_stage",
    task_id:"P255-L01",
    stage:"batch",
    lang:"",
    langs:"P255-L01"
  });
  const sentL02=submitBridgePost({
    action:"run_stage",
    task_id:"P255-L02",
    stage:"batch",
    lang:"",
    langs:"P255-L02"
  });

  if(!sentL01 || !sentL02){
    alert("至少一堂批次工作送出失敗：請重新連線控制中心後再試一次。");
    return;
  }

  const btn=document.getElementById("run-p255-batch");
  if(btn){
    btn.disabled=true;
    btn.textContent="已送出255期兩個續跑工作";
  }

  ["P255-L01","P255-L02"].forEach(id=>{
    const task=tasks.find(x=>x.id===id);
    if(!task) return;
    task.status="排隊中：255期斷點續跑";
    task.remoteStages=task.remoteStages||{};
    task.remoteStages.batch={
      task_id:id,
      stage:"batch",
      status:"queued",
      progress:"0",
      message:id+" 已獨立送出斷點續跑"
    };
  });
  save(STORE.tasks,tasks);
  renderTasks();
  window.setTimeout(()=>requestTaskStatuses(),1800);
});

document.getElementById("period").addEventListener("input",updateTaskCodes);

document.getElementById("task-form").addEventListener("submit",async e=>{
  e.preventDefault();

  const period=Number(document.getElementById("period").value);
  const note=document.getElementById("task-note").value.trim();
  const entries=[1,2,3,4]
    .map(i=>({
      lessonNo:i,
      url:document.getElementById("youtube-url-"+i).value.trim()
    }))
    .filter(x=>x.url);

  if(!period || period<1){
    alert("請先填入正確的期數。");
    return;
  }

  if(!entries.length){
    alert("至少填入一堂課的 YouTube 網址即可。其他堂可以之後再補。");
    return;
  }

  const replacements=entries.filter(x=>{
    const existing=taskAtSchedulePosition(period,x.lessonNo);
    return existing && existing.url && existing.url!==x.url;
  });

  if(replacements.length){
    const labels=replacements.map(x=>{
      const existing=taskAtSchedulePosition(period,x.lessonNo);
      return existing?.course_uid || existing?.id || ("第"+x.lessonNo+"堂");
    }).join("、");
    if(!confirm(labels+" 已經建立過。\n\n這次會用新的 YouTube 網址覆蓋原網址，確定要更新嗎？")){
      return;
    }
  }

  const created=[];
  for(const entry of entries){
    const i=entry.lessonNo;
    const existing=taskAtSchedulePosition(period,i);
    const id=existing?.id || availableLegacyTaskId(period,i);

    const task=existing || {
      id,
      period,
      lesson:"第"+i+"堂",
      completedStep:-1,
      workflowVersion:WORKFLOW_VERSION,
      createdAt:new Date().toISOString()
    };

    task.url=entry.url;
    task.note=note || task.note || "";
    task.status=cfg.apiBaseUrl ? "建立中" : "等待執行";

    if(cfg.apiBaseUrl){
      try{
        const r=await fetch(cfg.apiBaseUrl.replace(/\/$/,"")+"/jobs",{
          method:"POST",
          headers:{"content-type":"application/json"},
          body:JSON.stringify(task)
        });
        if(!r.ok) throw new Error("API "+r.status);
        const data=await r.json();
        task.status=data.status||"等待執行";
      }catch(err){
        task.status="本機草稿："+err.message;
      }
    }

    if(!existing) tasks.push(task);
    created.push(task);
  }

  selectedPeriod=period;
  save(STORE.tasks,tasks);
  renderTasks();

  submitBridgePost({
    action:"tasks_upsert",
    tasks_json:JSON.stringify(created.map(t=>({
      id:t.id,
      period:t.period,
      lesson:t.lesson,
      url:t.url,
      note:t.note||"",
      course_uid:t.course_uid||""
    })))
  });

  // 只清除本次填寫內容，保留期數，方便同一期分批補課程。
  for(const entry of entries){
    document.getElementById("youtube-url-"+entry.lessonNo).value="";
  }
  document.getElementById("task-note").value="";
  document.getElementById("period").value=period;
  updateTaskCodes();

  alert(
    "第 "+period+" 期本次已建立／更新 "+created.length+" 堂課：\n"+
    created.map(t=>"• "+t.id+" "+t.lesson).join("\n")+
    "\n\n其他堂課可以之後再回來補，不需要一次填滿四堂。"
  );
  showView("dashboard");
});

function renderTerms(filter=""){
  const q=filter.trim().toLowerCase();
  const rows=terms.filter(t=>
    !q||[t.name,t.category,t.en,t.aliases,t.description].join(" ").toLowerCase().includes(q)
  );

  document.getElementById("term-body").innerHTML=rows.map(t=>
    '<tr>'+
      '<td><b>'+escapeHtml(t.name)+'</b></td>'+
      '<td>'+escapeHtml(t.category)+'</td>'+
      '<td>'+escapeHtml(t.en||"—")+'</td>'+
      '<td>'+escapeHtml(t.aliases||"—")+'</td>'+
      '<td><span class="badge">'+escapeHtml(t.status||"正式詞庫")+'</span></td>'+
      '<td><button class="mini term" data-delete-term="'+escapeHtml(t.id)+'">刪除</button></td>'+
    '</tr>'
  ).join("");

  document.querySelectorAll("[data-delete-term]").forEach(b=>b.addEventListener("click",()=>{
    if(!confirm("刪除這個本機詞彙？")) return;
    terms=terms.filter(t=>t.id!==b.dataset.deleteTerm);
    save(STORE.terms,terms);
    renderTerms(document.getElementById("term-search").value);
    renderTasks();
  }));
}

document.getElementById("term-search").addEventListener(
  "input",e=>renderTerms(e.target.value)
);

const dlg=document.getElementById("term-dialog");
document.getElementById("add-term").addEventListener("click",()=>dlg.showModal());

document.getElementById("save-term").addEventListener("click",e=>{
  const form=document.getElementById("term-form");
  if(!form.reportValidity()){
    e.preventDefault();
    return;
  }

  const t={
    id:"term-"+Date.now(),
    name:document.getElementById("term-name").value.trim(),
    category:document.getElementById("term-category").value,
    en:document.getElementById("term-en").value.trim(),
    aliases:document.getElementById("term-aliases").value.trim(),
    description:document.getElementById("term-description").value.trim(),
    status:"正式詞庫"
  };

  terms.push(t);
  save(STORE.terms,terms);
  renderTerms();
  renderTasks();
  form.reset();
});

const demoSegments=[
  {time:"08:20",raw:"尤其是白楊棋裡面更是為法律主",text:"尤其是白陽期裡面更是為關法律主",flags:["changed"]},
  {time:"08:51",raw:"老母慈悲！暗猜鮮活！來跟你指點迷津",text:"老母慈悲！暗猜鮮活！來跟你指點迷津",flags:["uncertain"]},
  {time:"16:07",raw:"我們聽過一句成語叫做學護五車",text:"我們聽過一句成語叫做學富五車",flags:["changed"]},
  {time:"26:10",raw:"大家要扮演上善若水！胡園補缺就對了",text:"大家要扮演上善若水！扶圓補缺就對了",flags:["changed"]}
];

function segmentRowsHtml(items){
  return items.map((s,i)=>
    '<article class="zh-review-row '+(s.flags||[]).join(" ")+' '+(s.confirmed===true?"confirmed":"")+'" data-id="'+escapeHtml(s.id ?? i)+'" data-start="'+escapeHtml(s.start ?? 0)+'" data-end="'+escapeHtml(s.end ?? 0)+'" data-time="'+escapeHtml(s.time)+'">'+
      '<div class="zh-review-row-meta">'+
        '<span>#'+escapeHtml((s.id ?? i)+1)+'</span>'+
        '<span>'+escapeHtml(s.time)+'</span>'+
        '<span class="zh-review-flags">'+(s.flags||[]).map(x=>x==="uncertain"?"⚠ 待人工確認":"AI 已修改").join(" · ")+'</span>'+
      '</div>'+
      '<div class="zh-review-pair">'+
        '<div class="zh-asr-source">'+escapeHtml(s.raw)+'</div>'+
        '<textarea class="zh-polished-final">'+escapeHtml(s.text)+'</textarea>'+
      '</div>'+
      '<div class="segment-actions">'+
        '<button class="mini play-segment" type="button">▶ 聽這段</button>'+
        '<button class="mini term" type="button">加入詞庫</button>'+
        '<button class="mini confirm '+(s.confirmed===true?"confirmed":"")+'" type="button">'+(s.confirmed===true?"✓ 已確認":"確認此段")+'</button>'+
      '</div>'+
    '</article>'
  ).join("");
}

function filteredZhSegments(){
  if(zhActiveFilter==="all") return currentZhReviewAll;
  return currentZhReviewAll.filter(x=>(x.flags||[]).includes(zhActiveFilter));
}

function zhGithubPayload(){
  return {
    version:5,
    task_id:selectedTaskId,
    total_segments:currentZhReviewAll.length,
    segments:currentZhReviewAll.map(item=>({
      id:Number(item.id),
      start:Number(item.start||0),
      end:Number(item.end||0),
      time:String(item.time||formatClock(item.start)),
      raw:String(item.raw||""),
      text:String(item.text||""),
      flags:Array.isArray(item.flags)?item.flags:[],
      confirmed:item.confirmed===true,
      source_en:String(item.source_en||""),
      en_text:String(item.en_text||item.source_en||""),
      en_confirmed:item.en_confirmed===true
    }))
  };
}

function queueZhGithubSave(){
  if(!selectedTaskId) return false;

  if(zhGithubSaveInFlight){
    zhGithubSaveQueued=true;
    setZhReviewLoadState("GitHub 同步中・最新確認已排隊","working");
    return true;
  }

  zhGithubSaveInFlight=true;
  zhGithubSaveQueued=false;
  zhGithubSaveRevisionInFlight=zhGithubRevision;
  setZhReviewLoadState("正在同步確認狀態到 GitHub…","working");

  const sent=submitBridgePost({
    action:"review_share_draft_save",
    task_id:selectedTaskId,
    payload_json:JSON.stringify(zhGithubPayload())
  });

  if(!sent){
    zhGithubSaveInFlight=false;
    setZhReviewLoadState("GitHub 同步失敗：尚未連線控制中心","error");
  }
  return sent;
}

function bindZhReviewRows(){
  document.querySelectorAll(".zh-review-row").forEach(seg=>{
    if(seg.dataset.bound==="1") return;
    seg.dataset.bound="1";
    seg.addEventListener("click",event=>{
      document.getElementById("current-time").textContent=seg.dataset.time||"--:--";
      if(event.target.closest("textarea,button,input,select,a")) return;
      seekReviewYouTube(Number(seg.dataset.start||0),false);
    });
    const playBtn=seg.querySelector(".play-segment");
    playBtn?.addEventListener("click",event=>{
      event.stopPropagation();
      seekReviewYouTube(Number(seg.dataset.start||0),true);
      document.querySelectorAll(".zh-review-row.playing").forEach(x=>x.classList.remove("playing"));
      seg.classList.add("playing");
    });
    const textarea=seg.querySelector(".zh-polished-final");
    textarea?.addEventListener("input",()=>{
      const id=Number(seg.dataset.id);
      const item=currentZhReviewAll.find(x=>Number(x.id)===id);
      if(item) item.text=String(textarea.value||"");
      zhDirtySegmentIds.add(id);
      writeReviewCache({task_id:selectedTaskId,kind:"zh",segments:currentZhReviewAll,saved_at:Date.now()});
    });
    const btn=seg.querySelector(".confirm");
    btn?.addEventListener("click",()=>{
      const id=Number(seg.dataset.id);
      const item=currentZhReviewAll.find(x=>Number(x.id)===id);
      if(!item) return;

      item.confirmed=item.confirmed!==true;
      zhGithubRevision++;
      writeReviewCache({
        task_id:selectedTaskId,
        kind:"zh",
        segments:currentZhReviewAll,
        saved_at:Date.now()
      });

      seg.classList.toggle("confirmed",item.confirmed===true);
      btn.classList.toggle("confirmed",item.confirmed===true);
      btn.textContent=item.confirmed===true?"✓ 已確認":"確認此段";
      queueZhGithubSave();
    });
  });
  document.getElementById("zh-load-more")?.addEventListener("click",()=>{
    zhVisibleCount+=ZH_RENDER_BATCH;
    renderZhVisible();
  });
}

function renderZhVisible(){
  const el=document.getElementById("segment-list");
  const filtered=filteredZhSegments();
  currentZhReview=filtered;
  if(!filtered.length){
    el.innerHTML='<div class="empty">沒有符合目前篩選條件的段落。</div>';
    return;
  }
  const visible=filtered.slice(0,zhVisibleCount);
  const more=filtered.length-visible.length;
  el.innerHTML=segmentRowsHtml(visible)+(more>0 ? '<div class="load-more-row"><button class="ghost" id="zh-load-more">再顯示 '+Math.min(ZH_RENDER_BATCH,more)+' 段（尚有 '+more+' 段）</button></div>' : "");
  document.getElementById("stat-uncertain").textContent=currentZhReviewAll.filter(x=>(x.flags||[]).includes("uncertain")).length;
  const confirmedCount=currentZhReviewAll.filter(x=>x.confirmed===true).length;
  setZhReviewLoadState(
    zhReviewLoading
      ? "GitHub 最新版仍在同步"
      : "GitHub 直讀完成・已確認 "+confirmedCount+"/"+currentZhReviewAll.length+" 段",
    zhReviewLoading ? "working" : "ok"
  );
  bindZhReviewRows();
}

function renderSegments(items,options={}){
  if(!options.preserveMaster){
    currentZhReviewAll=Array.isArray(items) ? items.slice() : [];
  }
  zhVisibleCount=ZH_RENDER_BATCH;
  renderZhVisible();
}
document.getElementById("load-demo")?.addEventListener(
  "click",()=>renderSegments(demoSegments)
);

document.querySelectorAll("[data-filter]").forEach(b=>b.addEventListener("click",()=>{
  if(zhReviewLoading){
    setZhReviewLoadState("GitHub 最新版仍在同步，完成後即可篩選","working");
    return;
  }
  document.querySelectorAll("[data-filter]").forEach(
    x=>x.classList.toggle("active",x===b)
  );
  zhActiveFilter=b.dataset.filter||"all";
  zhVisibleCount=ZH_RENDER_BATCH;
  renderZhVisible();
}));


document.getElementById("review-back-5")?.addEventListener("click",()=>{
  if(reviewYouTubeReady && reviewYouTubePlayer){
    seekReviewYouTube(Math.max(0,Number(reviewYouTubePlayer.getCurrentTime?.()||0)-5),true);
  }
});
document.getElementById("review-forward-5")?.addEventListener("click",()=>{
  if(reviewYouTubeReady && reviewYouTubePlayer){
    seekReviewYouTube(Number(reviewYouTubePlayer.getCurrentTime?.()||0)+5,true);
  }
});

document.getElementById("refresh-zh-review")?.addEventListener("click",()=>{
  if(!selectedTaskId){
    alert("請先選擇一堂課。");
    return;
  }

  const task=tasks.find(x=>x.id===selectedTaskId);
  if(!task) return;

  setZhReviewLoadState("手動重新抓取 GitHub 最新逐字稿…","working");
  loadZhReviewFromGithub(task.id,{retry:0});
});

document.getElementById("create-review-share")?.addEventListener("click",()=>{
  if(!selectedTaskId){
    alert("請先選擇一堂課。");
    return;
  }

  const task=tasks.find(x=>x.id===selectedTaskId);
  if(!task) return;

  const shareUrl=quickReviewUrl(task);

  const state=document.getElementById("review-share-state");
  const copied=()=>{
    if(state) state.textContent="已複製固定編輯連結";
  };

  if(navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(shareUrl).then(copied).catch(()=>{
      window.prompt("請複製這堂課的固定編輯連結：",shareUrl);
    });
  }else{
    window.prompt("請複製這堂課的固定編輯連結：",shareUrl);
  }
});


document.getElementById("finalize-zh").addEventListener("click",()=>{
  if(!selectedTaskId){
    alert("請先從任務總覽選擇一堂課。");
    return;
  }

  const task=tasks.find(x=>x.id===selectedTaskId);
  if(!task) return;

  const ok=confirm(
    task.id+"｜"+task.lesson+"\n\n"+
    "確定中文逐字稿已人工確認完成並定稿？\n"+
    "定稿會寫回 Google Drive，之後 AI 白話文只使用這份 Final。"
  );
  if(!ok) return;

  if(zhReviewLoading){
    alert("GitHub 最新逐字稿仍在同步，請等右上角顯示「GitHub 直讀完成」後再定稿。");
    return;
  }

  const segments=currentZhReviewAll.map(item=>({
    id:Number(item.id),
    start:Number(item.start||0),
    end:Number(item.end||0),
    text:String(item.text||"").trim()
  }));

  if(!segments.length){
    alert("目前沒有可定稿的中文段落。");
    return;
  }

  submitBridgePost({
    action:"review_save",
    task_id:task.id,
    kind:"zh",
    segments_json:JSON.stringify(segments),
    terms_json:"[]"
  });

  task.status="中文定稿儲存中";
  save(STORE.tasks,tasks);
  alert("已送出中文 Final。系統確認寫入後會自動解鎖 AI 白話文。");
  openTaskDetail(task.id);
  window.setTimeout(()=>requestTaskStatuses(),1500);
});


const demoVernacularReview = [
  {
    id: 12,
    time: "08:20",
    original: "尤其是白陽期裡面，更是為關法律主。",
    vernacular: "尤其在白陽期，更要依循關法律主所指示的方向來修辦。"
  },
  {
    id: 13,
    time: "08:51",
    original: "老母慈悲，來跟你指點迷津。",
    vernacular: "老母慈悲地指引我們，在迷惘時找到正確方向。"
  },
  {
    id: 14,
    time: "09:14",
    original: "欲成佛道，當要先行佛事。",
    vernacular: "若想成就佛道，就應先從實際去行佛事、利益眾生做起。"
  }
];

function openVernacularReview(taskId){
  selectedTaskId=taskId;
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;

  const context=document.getElementById("vernacular-review-task-context");
  context.innerHTML=
    '<b>'+escapeHtml(task.id)+'</b>'+
    '<span>第'+escapeHtml(task.period)+'期・'+escapeHtml(task.lesson)+'</span>'+
    '<small>'+escapeHtml(task.url)+'</small>';

  document.getElementById("vernacular-review-list").innerHTML='<div class="empty">正在讀取白話文資料…</div>';
  showView("vernacular-review");
  requestReviewData(task.id,"vernacular");
}

function renderVernacularReview(items){
  currentVernacularReview=items;
  const list=document.getElementById("vernacular-review-list");
  if(!list) return;

  list.innerHTML=items.map(item=>
    '<article class="vernacular-review-row" data-vernacular-segment="'+item.id+'" data-start="'+escapeHtml(item.start ?? 0)+'" data-end="'+escapeHtml(item.end ?? 0)+'">'+
      '<div class="en-review-meta"><span>#'+item.id+'</span><span>'+escapeHtml(item.time)+'</span></div>'+
      '<div class="vernacular-review-pair">'+
        '<div class="zh-source">'+escapeHtml(item.original)+'</div>'+
        '<textarea class="vernacular-draft">'+escapeHtml(item.vernacular)+'</textarea>'+
      '</div>'+
      '<div class="segment-actions">'+
        '<button class="mini confirm" data-confirm-vernacular-segment="'+item.id+'">確認此段</button>'+
      '</div>'+
    '</article>'
  ).join("");

  document.querySelectorAll("[data-confirm-vernacular-segment]").forEach(btn=>{
    btn.addEventListener("click",()=>{
      const row=btn.closest(".vernacular-review-row");
      row.classList.add("confirmed");
      btn.textContent="已確認";
      btn.disabled=true;
    });
  });
}

document.getElementById("load-vernacular-demo")?.addEventListener(
  "click",()=>renderVernacularReview(demoVernacularReview)
);

document.getElementById("finalize-vernacular")?.addEventListener("click",()=>{
  if(!selectedTaskId){
    alert("請先從任務總覽選擇一堂課。");
    return;
  }

  const task=tasks.find(x=>x.id===selectedTaskId);
  if(!task) return;

  const ok=confirm(
    task.id+"｜"+task.lesson+"\n\n"+
    "確定白話文已人工確認完成並定稿？\n"+
    "定稿會寫回 Google Drive，英文翻譯會優先使用這份 Final。"
  );
  if(!ok) return;

  const segments=[...document.querySelectorAll("#vernacular-review-list .vernacular-review-row")].map(row=>({
    id:Number(row.dataset.vernacularSegment),
    start:Number(row.dataset.start||0),
    end:Number(row.dataset.end||0),
    text:String(row.querySelector(".vernacular-draft")?.value||"").trim()
  }));

  if(!segments.length){
    alert("目前沒有可定稿的白話文段落。");
    return;
  }

  submitBridgePost({
    action:"review_save",
    task_id:task.id,
    kind:"vernacular",
    segments_json:JSON.stringify(segments),
    terms_json:"[]"
  });

  task.status="白話文定稿儲存中";
  save(STORE.tasks,tasks);
  alert("已送出白話文 Final。系統確認寫入後會自動解鎖英文翻譯。");
  openTaskDetail(task.id);
  window.setTimeout(()=>requestTaskStatuses(),1500);
});

const demoEnglishReview = [
  {
    id: 12,
    time: "08:20",
    original: "尤其是白陽期裡面，更是為關法律主。",
    vernacular: "尤其在白陽期，更要把修辦的方向確立清楚。",
    en: "Especially in the White Yang Era, we need to clearly establish the direction of cultivation and Tao propagation.",
    terms: [
      {zh:"白陽期", en:"White Yang Era"},
      {zh:"修辦", en:"cultivation and Tao propagation"}
    ]
  },
  {
    id: 13,
    time: "08:51",
    original: "感恩天恩師德，各位前賢一路成全。",
    vernacular: "我們感恩天恩師德，也感謝各位前賢一路以來的成全。",
    en: "We are grateful for Heaven's grace and our Teacher's virtue, and for the support of all senior predecessors along the way.",
    terms: [
      {zh:"天恩師德", en:"Heaven's grace and our Teacher's virtue"},
      {zh:"前賢", en:"senior predecessors"}
    ]
  },
  {
    id: 14,
    time: "09:14",
    original: "修道不是只有自己明白，也要懂得渡化眾生。",
    vernacular: "修道不只是自己明白道理，也要懂得如何引導、渡化他人。",
    en: "Cultivating the Tao is not only about understanding it ourselves; we also need to know how to guide and transform others.",
    terms: [
      {zh:"修道", en:"cultivating the Tao"},
      {zh:"渡化", en:"guide and transform"}
    ]
  }
];

function englishReviewItemsFromGithub(payload){
  const segments=repairReviewTimings(
    Array.isArray(payload?.segments) ? payload.segments : []
  );

  return segments.map((item,i)=>{
    const zhText=String(item.text||"").trim();
    const sourceEn=String(item.source_en||"").trim();
    const editableEn=String(item.en_text||sourceEn).trim();
    const pairs=terms
      .filter(t=>t && t.name && zhText.includes(String(t.name)))
      .map(t=>({zh:String(t.name),en:String(t.en||"")}));

    return {
      id:Number(item.id!==undefined?item.id:i),
      start:Number(item.start||0),
      end:Number(item.end||0),
      time:String(item.time||formatClock(item.start)),
      original:zhText,
      vernacular:"",
      en:editableEn,
      source_en:sourceEn,
      terms:pairs
    };
  });
}

async function waitForEnglishCcRefresh(taskId,button,statusEl){
  const maxAttempts=36;
  for(let attempt=1;attempt<=maxAttempts;attempt++){
    if(statusEl){
      statusEl.textContent="補抓進行中… "+attempt+"/"+maxAttempts;
    }
    await new Promise(resolve=>setTimeout(resolve,5000));

    try{
      const response=await fetch(githubReviewUrl(taskId),{
        method:"GET",
        cache:"no-store",
        headers:{"Accept":"application/json"}
      });
      if(!response.ok) continue;
      const refreshed=await response.json();
      const available=(refreshed.segments||[]).filter(
        x=>String(x.source_en||x.en_text||"").trim()
      ).length;
      if(available>0){
        if(statusEl) statusEl.textContent="English CC 補抓完成，正在載入…";
        await openEnglishReview(taskId);
        return;
      }
    }catch(_){}
  }

  showNoEnglishCcFallback(taskId);
}

function dispatchEnglishCcRefresh(taskId,button,statusEl){
  const sent=submitBridgePost({
    action:"run_stage",
    task_id:taskId,
    stage:"en",
    lang:"cc-refresh",
    langs:""
  });

  if(!sent){
    if(statusEl) statusEl.textContent="尚未連線 Apps Script 或缺少 Bridge Key。";
    return;
  }

  if(button){
    button.disabled=true;
    button.textContent="已送出補抓工作";
  }
  if(statusEl) statusEl.textContent="已送出，只補抓 English CC，不重跑中文。";
  waitForEnglishCcRefresh(taskId,button,statusEl);
}

async function waitForAiEnglishTranslation(taskId,button,statusEl){
  const maxAttempts=72;
  for(let attempt=1;attempt<=maxAttempts;attempt++){
    if(statusEl){
      statusEl.textContent="中文 → 英文 AI 翻譯中… "+attempt+"/"+maxAttempts;
    }

    requestTaskStatuses();
    await new Promise(resolve=>setTimeout(resolve,5000));

    const task=tasks.find(x=>x.id===taskId);
    const remote=remoteStageStatus(task,"en");

    if(remote && remote.status==="done"){
      if(statusEl) statusEl.textContent="英文翻譯完成，正在載入人工定稿資料…";
      const requested=requestReviewData(taskId,"en",0);
      if(!requested && statusEl){
        statusEl.textContent="英文翻譯已完成，但目前無法讀取英文定稿資料。";
      }
      return;
    }

    if(remote && ["error","stale"].includes(remote.status)){
      if(statusEl){
        statusEl.textContent=
          "中文 → 英文翻譯失敗："+String(remote.message||remoteStatusText(remote.status));
      }
      if(button){
        button.disabled=false;
        button.textContent="重新執行中文 → 英文";
      }
      return;
    }
  }

  if(statusEl){
    statusEl.textContent="英文翻譯仍在執行或尚未回報，可稍後重新整理後再進入此頁。";
  }
  if(button){
    button.disabled=false;
    button.textContent="重新檢查／執行中文 → 英文";
  }
}

function dispatchAiEnglishTranslation(taskId,button,statusEl){
  const ok=confirm(
    "這堂課目前沒有可用的 YouTube English CC。\n\n"+
    "要改用已完成的中文 Final 直接進行 AI 中文 → 英文翻譯嗎？"
  );
  if(!ok) return;

  const sent=submitBridgePost({
    action:"run_stage",
    task_id:taskId,
    stage:"en",
    lang:"",
    langs:""
  });

  if(!sent){
    if(statusEl) statusEl.textContent="尚未連線 Apps Script 或缺少 Bridge Key。";
    return;
  }

  const task=tasks.find(x=>x.id===taskId);
  if(task){
    task.remoteStages=task.remoteStages||{};
    task.remoteStages.en={
      task_id:taskId,
      stage:"en",
      status:"queued",
      progress:"0",
      message:"已送出中文 → 英文 AI 翻譯"
    };
    task.status="排隊中：中文 → 英文";
    save(STORE.tasks,tasks);
  }

  if(button){
    button.disabled=true;
    button.textContent="已送出中文 → 英文";
  }
  if(statusEl){
    statusEl.textContent="已送出。來源為中文 Final，不需要重新跑 ASR 或中文校稿。";
  }

  window.setTimeout(()=>requestTaskStatuses(),1200);
  waitForAiEnglishTranslation(taskId,button,statusEl);
}

function showNoEnglishCcFallback(taskId){
  const list=document.getElementById("en-review-list");
  if(!list) return;

  list.innerHTML=
    '<div class="empty">'+
      '<b>擷取不到 English CC 字幕，或此影片沒有 English auto-generated CC。</b>'+
      '<br><br>你可以再嘗試擷取一次；如果確認影片本身沒有 CC，'+
      '可以直接改用已完成的中文 Final 進行中文 → 英文 AI 翻譯。'+
      '<br><br>'+
      '<div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">'+
        '<button class="ghost" id="refresh-en-cc">重新嘗試擷取 CC</button>'+
        '<button class="primary" id="translate-zh-en">改用中文 → 英文 AI 翻譯</button>'+
      '</div>'+
      '<div class="muted" id="en-fallback-status" style="margin-top:12px"></div>'+
    '</div>';

  currentEnglishReview=[];

  const refreshBtn=document.getElementById("refresh-en-cc");
  const translateBtn=document.getElementById("translate-zh-en");
  const statusEl=document.getElementById("en-fallback-status");

  refreshBtn?.addEventListener("click",()=>{
    dispatchEnglishCcRefresh(taskId,refreshBtn,statusEl);
  });

  translateBtn?.addEventListener("click",()=>{
    dispatchAiEnglishTranslation(taskId,translateBtn,statusEl);
  });
}

async function openEnglishReview(taskId){
  selectedTaskId=taskId;
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;

  const context=document.getElementById("en-review-task-context");
  context.innerHTML=
    '<b>'+escapeHtml(task.id)+'</b>'+
    '<span>第'+escapeHtml(task.period)+'期・'+escapeHtml(task.lesson)+'</span>'+
    '<small>'+escapeHtml(task.url)+'</small>';

  const list=document.getElementById("en-review-list");
  list.innerHTML=
    '<div class="empty">正在讀取英文來源（優先 YouTube English CC；無快取則讀取 Drive 英文稿）…</div>';
  showView("en-review");

  try{
    const response=await fetch(githubReviewUrl(task.id),{
      method:"GET",
      cache:"no-store",
      headers:{"Accept":"application/json"}
    });

    if(response.ok){
      const payload=await response.json();
      const items=englishReviewItemsFromGithub(payload);
      const available=items.filter(x=>String(x.en||"").trim()).length;

      if(items.length && available){
        renderEnglishReview(items);
        return;
      }
    }

    // GitHub review cache is only an acceleration layer. It may legitimately
    // be absent on resumed batches. The authoritative English draft is in
    // Google Drive (en.json), so always try the Bridge/Drive loader before
    // declaring English CC unavailable.
    list.innerHTML=
      '<div class="empty">GitHub 英文對照快取不存在或沒有 English CC，正在改由 Google Drive 載入英文稿…</div>';
    if(requestReviewData(taskId,"en",0)) return;

    throw new Error("Google Drive 英文稿備援目前未連線");
  }catch(err){
    list.innerHTML=
      '<div class="empty">英文稿讀取失敗：'+
      escapeHtml(String(err?.message||err))+
      '<br><br><button class="ghost" id="retry-en-cc">重新讀取</button></div>';
    document.getElementById("retry-en-cc")?.addEventListener(
      "click",
      ()=>openEnglishReview(taskId)
    );
  }
}

function renderEnglishReview(items){
  currentEnglishReview=items;
  document.getElementById("en-review-head")?.classList.add("hide-vernacular");
  document.getElementById("en-review-list")?.classList.add("hide-vernacular");
  const list=document.getElementById("en-review-list");
  const termBox=document.getElementById("en-term-learning");
  if(!list || !termBox) return;

  list.innerHTML=items.map(item=>
    '<article class="en-review-row" data-en-segment="'+item.id+'" data-start="'+escapeHtml(item.start ?? 0)+'" data-end="'+escapeHtml(item.end ?? 0)+'">'+
      '<div class="en-review-meta">'+
        '<span>#'+item.id+'</span><span>'+escapeHtml(item.time)+'</span>'+
      '</div>'+
      '<div class="en-review-pair">'+
        '<div class="zh-source original-column">'+escapeHtml(item.original)+'</div>'+
        '<textarea class="en-draft">'+escapeHtml(item.en)+'</textarea>'+
      '</div>'+
      '<div class="segment-actions">'+
        '<button class="mini confirm" data-confirm-en-segment="'+item.id+'">確認此段</button>'+
      '</div>'+
    '</article>'
  ).join("");

  const pairs=[];
  items.forEach(item=>{
    (item.terms||[]).forEach(pair=>{
      const key=pair.zh+"|||"+pair.en;
      if(!pairs.some(x=>x.key===key)) pairs.push({...pair,key});
    });
  });

  termBox.innerHTML=pairs.map(pair=>{
    const existing=terms.find(t=>t.name===pair.zh);
    const current=existing && existing.en ? existing.en : "";
    const learned=current && current===pair.en;
    return '<article class="term-learning-card '+(learned?"learned":"")+'">'+
      '<div><b>'+escapeHtml(pair.zh)+'</b><span>AI / 目前英文譯法</span></div>'+
      '<input value="'+escapeHtml(pair.en)+'" data-term-en-input="'+escapeHtml(pair.zh)+'">'+
      '<small>'+(current?'詞庫目前：'+escapeHtml(current):'詞庫尚未設定英文譯法')+'</small>'+
      '<button class="'+(learned?"ghost":"primary")+'" data-learn-term="'+escapeHtml(pair.zh)+'">'+
        (learned?"已學習":"確認並學習")+
      '</button>'+
    '</article>';
  }).join("");

  document.querySelectorAll("[data-confirm-en-segment]").forEach(btn=>{
    btn.addEventListener("click",()=>{
      const row=btn.closest(".en-review-row");
      row.classList.add("confirmed");
      btn.textContent="已確認";
      btn.disabled=true;
    });
  });

  document.querySelectorAll("[data-learn-term]").forEach(btn=>{
    btn.addEventListener("click",()=>{
      const zh=btn.dataset.learnTerm;
      const input=document.querySelector('[data-term-en-input="'+CSS.escape(zh)+'"]');
      const en=String(input?.value||"").trim();
      if(!en){
        alert("請先輸入英文譯法。");
        return;
      }

      let term=terms.find(t=>t.name===zh);
      if(!term){
        term={
          id:"learned-"+Date.now(),
          name:zh,
          category:"宗教術語",
          aliases:"",
          description:"由英文人工定稿同步學習",
          en:"",
          status:"正式詞庫"
        };
        terms.push(term);
      }

      term.en=en;
      term.status="英文已確認";
      save(STORE.terms,terms);
      renderTerms(document.getElementById("term-search").value);
      renderTasks();
      btn.textContent="已學習";
      btn.className="ghost";
      btn.closest(".term-learning-card")?.classList.add("learned");
    });
  });
}

document.getElementById("toggle-en-vernacular")?.addEventListener("change",e=>{
  const hidden=!e.target.checked;
  document.getElementById("en-review-head")?.classList.toggle("hide-vernacular",hidden);
  document.getElementById("en-review-list")?.classList.toggle("hide-vernacular",hidden);
});

document.getElementById("finalize-en")?.addEventListener("click",()=>{
  if(!selectedTaskId){
    alert("請先從任務總覽選擇一堂課。");
    return;
  }

  const task=tasks.find(x=>x.id===selectedTaskId);
  if(!task) return;

  const ok=confirm(
    task.id+"｜"+task.lesson+"\n\n"+
    "確定英文稿已人工確認完成並定稿？\n"+
    "定稿會寫回 Google Drive；其他語言會直接使用這份 English Final。"
  );
  if(!ok) return;

  const segments=[...document.querySelectorAll("#en-review-list .en-review-row")].map(row=>({
    id:Number(row.dataset.enSegment),
    start:Number(row.dataset.start||0),
    end:Number(row.dataset.end||0),
    text:String(row.querySelector(".en-draft")?.value||"").trim()
  }));

  const learnedTerms=[...document.querySelectorAll("[data-term-en-input]")].map(input=>({
    zh:String(input.dataset.termEnInput||"").trim(),
    en:String(input.value||"").trim()
  })).filter(x=>x.zh&&x.en);

  if(!segments.length){
    alert("目前沒有可定稿的英文段落。");
    return;
  }

  submitBridgePost({
    action:"review_save",
    task_id:task.id,
    kind:"en",
    segments_json:JSON.stringify(segments),
    terms_json:JSON.stringify(learnedTerms)
  });

  task.status="英文定稿儲存中";
  save(STORE.tasks,tasks);
  alert("已送出 English Final。系統確認後會自動解鎖各國語言翻譯。");
  openTaskDetail(task.id);
  window.setTimeout(()=>requestTaskStatuses(),1500);
});

function submitBridgePost(fields){
  const endpoint=bridgeEndpointValue();
  const key=bridgeKeyValue();

  if(!endpoint || !key) return false;

  if(fields && fields.action==="run_stage"){
    if(bridgeProtocolVersion<=0){
      alert("控制中心版本尚未驗證完成，請先按「連線控制中心」並等待顯示 Bridge 版本。");
      return false;
    }
    if(bridgeProtocolVersion<REQUIRED_BRIDGE_PROTOCOL){
      alert(
        "Apps Script 控制中心版本過舊（目前 "+bridgeProtocolVersion+
        "，需要 "+REQUIRED_BRIDGE_PROTOCOL+"）。請先重新部署 Code.gs；"+
        "系統已阻止送出可能使用錯誤協定的 Kaggle 工作。"
      );
      return false;
    }
  }

  // Every POST gets its own hidden iframe. Reusing one target causes two rapid
  // submissions (for example P255-L01 + P255-L02) to race, and the second
  // navigation can replace the first before Apps Script receives it.
  const target="soulkey-bridge-post-"+Date.now()+"-"+Math.random().toString(36).slice(2);
  const frame=document.createElement("iframe");
  frame.name=target;
  frame.style.display="none";
  frame.setAttribute("aria-hidden","true");

  const form=document.createElement("form");
  form.method="POST";
  form.action=endpoint;
  form.target=target;
  form.style.display="none";

  const payload={...fields,bridge_key:key};
  for(const [name,value] of Object.entries(payload)){
    const input=document.createElement("input");
    input.type="hidden";
    input.name=name;
    input.value=String(value ?? "");
    form.appendChild(input);
  }

  document.body.appendChild(frame);
  document.body.appendChild(form);
  form.submit();
  window.setTimeout(()=>{
    form.remove();
    frame.remove();
  },10000);
  return true;
}

function initBridgeClient(){
  const frame=document.getElementById("soulkey-status-bridge");
  if(!frame) return;

  const endpoint=bridgeEndpointValue();

  if(!endpoint) return;

  bridgeClientReady=false;
  const sep=endpoint.includes("?") ? "&" : "?";
  frame.src=endpoint+sep+"view=client&v=20260920-13";
}

function bridgeClientRequest(fields){
  const frame=document.getElementById("soulkey-status-bridge");
  const key=bridgeKeyValue();

  if(!frame || !frame.contentWindow || !bridgeClientReady || !key){
    return false;
  }

  frame.contentWindow.postMessage({
    source:"soulkey-studio",
    type:"bridge_request",
    request:{...fields,bridge_key:key}
  },"*");

  return true;
}

function jsonpBridgeRequest(fields){
  const endpoint=bridgeEndpointValue();
  const key=bridgeKeyValue();

  if(!endpoint || !key) return false;

  const callbackName="__soulkey_jsonp_"+Date.now()+"_"+Math.random().toString(36).slice(2);
  const script=document.createElement("script");
  const params=new URLSearchParams({
    ...Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,String(v ?? "")])),
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
    const syncState=document.getElementById("status-sync-state");
    const syncText=document.getElementById("status-sync-text");
    if(syncState){
      syncState.textContent="同步失敗";
      syncState.className="warn";
    }
    if(syncText){
      syncText.textContent="無法讀取 Apps Script 狀態 API。";
    }
  };

  const sep=endpoint.includes("?") ? "&" : "?";
  script.src=endpoint+sep+params.toString();
  document.head.appendChild(script);
  return true;
}

function applyRemoteStatuses(payload){
  const remoteTasks=payload && payload.tasks ? payload.tasks : {};
  let changed=false;

  for(const task of tasks){
    const remote=remoteTasks[task.id];
    if(!remote || !remote.stages) continue;
    task.remoteStages=remote.stages;
    task.remoteUpdatedAt=payload.server_time || new Date().toISOString();
    syncCompletedFromRemote(task);
    changed=true;
  }

  if(changed){
    save(STORE.tasks,tasks);
    renderTasks();
    if(currentView==="task-detail" && selectedTaskId){
      const task=tasks.find(x=>x.id===selectedTaskId);
      if(task) renderTaskDetail(task);
    }
    if(currentView==="youtube-audio"){
      renderYoutubeAudioTasks();
    }
  }

  const syncState=document.getElementById("status-sync-state");
  if(syncState){
    syncState.textContent="已同步";
    syncState.className="ok";
  }
  const syncText=document.getElementById("status-sync-text");
  if(syncText){
    syncText.textContent="最後同步："+new Date().toLocaleTimeString();
  }
}

function requestTaskStatuses(){
  const key=bridgeKeyValue();
  const endpoint=bridgeEndpointValue();
  if(!key || !endpoint || !tasks.length) return false;

  const ids=tasks.map(t=>t.id).filter(Boolean).slice(0,20);
  if(!ids.length) return false;

  return jsonpBridgeRequest({
    action:"status_batch",
    task_ids:ids.join(",")
  });
}

function requestStatusHealth(){
  return jsonpBridgeRequest({action:"status_health"});
}

window.addEventListener("message",event=>{
  const data=event.data || {};

  if(data.source==="soulkey-bridge-client" && data.type==="ready"){
    bridgeClientReady=true;
    const syncState=document.getElementById("status-sync-state");
    const syncText=document.getElementById("status-sync-text");
    if(syncState){
      syncState.textContent="Bridge 已連線";
      syncState.className="ok";
    }
    if(syncText){
      syncText.textContent="正在讀取執行狀態…";
    }
    requestStatusHealth();
    requestTaskStatuses();
    requestLanguageSettings();
    return;
  }

  if(data.source!=="soulkey-bridge") return;

  if(data.type==="worker_setup"){
    if(data.ok){
      setWorkerStatus(
        "Web Worker 建立工作已送出。完成後請在 Kaggle 的 SoulKey Web Worker 附加 SOULKEY_WEB_TEST 測試 Secret。",
        "ready"
      );
    }else{
      setWorkerStatus("建立 Web Worker 失敗："+(data.message || data.error || "未知錯誤"),"error");
    }
  }

  if(data.type==="worker_secret_test"){
    if(data.ok){
      setWorkerStatus(
        "私人憑證資料集測試已送出。請等待 GitHub Actions 完成；通過後就可以接正式網頁執行。",
        "sending"
      );
    }else{
      setWorkerStatus("私人憑證資料集測試送出失敗："+(data.message || data.error || "未知錯誤"),"error");
    }
  }

  if(data.type==="bridge_error"){
    const reason=data.message || data.error || "未知錯誤";
    if(currentView==="youtube-audio" && youtubeCaptureFilesLoadingTask){
      const badge=document.getElementById("youtube-capture-files-state");
      if(badge){
        badge.textContent=String(data.error||"")==="unsupported_action"
          ? "Apps Script 需重新部署"
          : "雲端檔案讀取失敗";
        badge.className="badge";
      }
      youtubeCaptureFilesLoadingTask="";
    }
    setDashboardBridgeState("Bridge 錯誤："+reason,"error");
    const syncState=document.getElementById("status-sync-state");
    const syncText=document.getElementById("status-sync-text");
    if(syncState){
      syncState.textContent="Bridge 錯誤："+reason;
      syncState.className="warn";
    }
    if(syncText){
      syncText.textContent="Bridge 錯誤："+reason;
    }
  }

  if(data.type==="tasks_result"){
    const apiState=document.getElementById("api-state");
    if(data.ok){
      if(apiState){
        apiState.textContent="任務已同步";
        apiState.className="ok";
      }
      mergeRemoteTasks(data.tasks||[]);
      const backendText=document.getElementById("backend-text");
      const backendDot=document.querySelector(".backend-pill .status-dot");
      if(backendText) backendText.textContent="控制中心已連線";
      if(backendDot) backendDot.style.background="#56b981";
      setDashboardBridgeState(
        "已從 Google Sheet 載入 "+String((data.tasks||[]).length)+" 筆任務，正在同步各階段狀態。",
        "ok"
      );
      window.setTimeout(()=>requestTaskStatuses(),150);
    }else{
      if(apiState){
        apiState.textContent="任務同步失敗";
        apiState.className="warn";
      }
      const el=document.getElementById("task-list");
      if(el){
        el.innerHTML='<div class="empty">任務同步失敗：'+escapeHtml(data.message||data.error||"未知錯誤")+'</div>';
      }
    }
  }

  if(data.type==="review_share_draft_saved"){
    zhGithubSaveInFlight=false;

    if(data.ok){
      zhGithubLastSavedRevision=Math.max(
        zhGithubLastSavedRevision,
        zhGithubSaveRevisionInFlight
      );

      const confirmedCount=currentZhReviewAll.filter(x=>x.confirmed===true).length;
      setZhReviewLoadState(
        zhGithubSaveQueued
          ? "前一批已同步・繼續同步最新確認…"
          : "GitHub 已同步・已確認 "+confirmedCount+"/"+currentZhReviewAll.length+" 段",
        zhGithubSaveQueued ? "working" : "ok"
      );

      if(zhGithubSaveQueued){
        zhGithubSaveQueued=false;
        window.setTimeout(()=>queueZhGithubSave(),0);
      }
    }else{
      setZhReviewLoadState(
        "GitHub 同步失敗："+(data.message||data.error||"未知錯誤"),
        "error"
      );
    }
  }

  if(data.type==="review_data"){
    const chunkIndex=Number(data.chunk_index||0);
    const browserElapsed=reviewElapsedMs(data.task_id,data.kind,chunkIndex);
    if(!data.ok){
      if(data.kind==="zh"){
        zhReviewLoading=false;
        setZhFinalizeEnabled(false);
        setZhReviewLoadState("雲端同步失敗","error");
        alert("讀取人工校正資料失敗："+(data.message || data.error || "未知錯誤"));
      }else if(data.kind==="en"){
        // Neither GitHub English-CC cache nor Drive en.json is available.
        // Present the intended fallback actions instead of a dead-end alert.
        showNoEnglishCcFallback(data.task_id || selectedTaskId);
        const status=document.getElementById("en-fallback-status");
        if(status){
          status.textContent="Drive 英文稿目前也尚未建立："+(data.message || data.error || "未知錯誤");
        }
      }else{
        alert("讀取人工校正資料失敗："+(data.message || data.error || "未知錯誤"));
      }
    }else if(data.kind==="zh"){
      const incoming=Array.isArray(data.segments) ? data.segments : [];
      if(chunkIndex===0){
        zhFreshSegments=[];
        zhReviewTotal=Number(data.total_segments||incoming.length);
      }
      zhFreshSegments.push(...incoming);

      if(!zhReviewCachedPreview){
        renderSegments(incoming,{append:chunkIndex>0});
      }

      const loaded=zhFreshSegments.length;
      const total=zhReviewTotal || loaded;
      const backendMs=Number(data.load_ms||0);
      const shownMs=backendMs || browserElapsed;
      setZhReviewLoadState(
        "已載入 "+loaded+"/"+total+" 段"+(shownMs ? "・本批 "+(shownMs/1000).toFixed(1)+"s" : ""),
        data.has_more ? "working" : "ok"
      );

      if(data.has_more){
        window.setTimeout(
          ()=>requestReviewData(data.task_id,"zh",chunkIndex+1),
          30
        );
      }else{
        const currentById=new Map(currentZhReviewAll.map(x=>[Number(x.id),x]));
        const merged=zhFreshSegments.map(x=>{
          const id=Number(x.id);
          if(zhDirtySegmentIds.has(id) && currentById.has(id)){
            return {...x,text:currentById.get(id).text};
          }
          return x;
        });

        if(zhReviewCachedPreview){
          renderSegments(merged);
        }else{
          currentZhReview=merged;
          currentZhReviewAll=merged;
        }

        writeReviewCache({
          task_id:data.task_id,
          kind:"zh",
          segments:currentZhReviewAll,
          load_ms:Number(data.load_ms||0)
        });

        zhReviewCachedPreview=false;
        zhReviewLoading=false;
        setZhFinalizeEnabled(true);
        setZhReviewLoadState("雲端最新・共 "+currentZhReviewAll.length+" 段","ok");
      }
    }else if(data.kind==="vernacular"){
      renderVernacularReview(data.segments||[]);
    }else if(data.kind==="en"){
      renderEnglishReview(data.segments||[]);
    }
  }

  if(data.type==="review_saved"){
    if(data.ok){
      requestTaskStatuses();
    }else{
      alert("人工定稿寫入失敗："+(data.message || data.error || "未知錯誤"));
    }
  }

  if(data.type==="run_stage"){
    if(data.ok){
      const audioStatus=document.getElementById("youtube-audio-status");
      if(
        currentView==="youtube-audio" &&
        data.stage==="cc" &&
        audioStatus
      ){
        audioStatus.textContent="Kaggle 已接收 YouTube 抓取工作，正在等待執行。";
      }
      requestTaskStatuses();
    }else{
      alert("Kaggle 工作送出失敗："+(data.message || data.error || "未知錯誤"));
    }
  }

  if(data.type==="youtube_capture_files"){
    youtubeCaptureFilesLoadingTask="";
    const badge=document.getElementById("youtube-capture-files-state");

    if(data.ok && data.task_id){
      youtubeCaptureFilesCache[data.task_id]=data;
      youtubeCaptureFilesFetchedAt[data.task_id]=Date.now();

      const selected=youtubeAudioSelectedTask();
      if(selected && String(selected.id)===String(data.task_id)){
        renderYoutubeCaptureFiles(selected);
      }
    }else if(badge){
      badge.textContent="雲端檔案讀取失敗";
      badge.className="badge";
    }
  }

  if(data.type==="task_rescheduled"){
    const state=document.getElementById("schedule-state");
    const status=document.getElementById("schedule-status");
    const button=document.getElementById("schedule-apply");
    if(button) button.disabled=false;

    if(data.ok){
      if(state){
        state.textContent="調課完成";
        state.className="badge complete";
      }
      if(status){
        status.textContent=data.message || "調課完成。";
      }
      requestTasksFromControlCenter();
      window.setTimeout(()=>requestTaskStatuses(),200);
    }else{
      if(state){
        state.textContent="調課失敗";
        state.className="badge";
      }
      if(status){
        status.textContent="調課失敗："+(data.message||data.error||"未知錯誤");
      }
    }
  }

  if(data.type==="drive_names_migrated"){
    const state=document.getElementById("drive-name-state");
    const status=document.getElementById("drive-name-status");
    const button=document.getElementById("drive-name-migrate-all");
    if(button) button.disabled=false;

    if(data.ok){
      if(state){
        state.textContent="整理完成";
        state.className="badge complete";
      }
      if(status){
        status.textContent=
          "已整理 "+String(data.task_count||0)+" 堂課；"+
          "重新命名 "+String(data.renamed||0)+" 個檔案，"+
          "寫入 canonical 標記 "+String(data.marked||0)+" 個。";
      }
      requestTaskStatuses();
      if(currentView==="youtube-audio"){
        renderYoutubeAudioTasks(true);
      }
    }else{
      if(state){
        state.textContent="整理失敗";
        state.className="badge";
      }
      if(status){
        status.textContent="檔名整理失敗："+(data.message||data.error||"未知錯誤");
      }
    }
  }

  if(data.type==="status_result"){
    if(data.ok){
      applyRemoteStatuses(data);
    }else{
      const syncState=document.getElementById("status-sync-state");
      const syncText=document.getElementById("status-sync-text");
      const reason=data.message || data.error || "未知錯誤";
      if(syncState){
        syncState.textContent="同步失敗";
        syncState.className="warn";
      }
      if(syncText){
        syncText.textContent="狀態同步失敗："+reason;
      }
    }
  }

  if(data.type==="language_settings" && data.ok){
    const received=Array.isArray(data.languages) ? data.languages : [];
    if(received.length){
      languageSettings=received;
      const task=tasks.find(x=>x.id===selectedTaskId);
      if(task) renderLanguagePlan(task);
    }
  }

  if(data.type==="language_plan" && data.ok){
    const task=tasks.find(x=>x.id===data.task_id);
    if(task){
      task.languagePlan=Array.isArray(data.plan) ? data.plan : [];
      save(STORE.tasks,tasks);
      if(selectedTaskId===task.id) renderLanguagePlan(task);
    }
  }

  if(data.type==="language_plan_saved"){
    const status=document.getElementById("language-plan-status");
    if(data.ok){
      const task=tasks.find(x=>x.id===data.task_id);
      if(task){
        task.languagePlan=Array.isArray(data.plan) ? data.plan : task.languagePlan;
        save(STORE.tasks,tasks);
      }
      if(status){
        status.textContent=data.translation_changed
          ? "已同步；翻譯設定有變更，舊多語/TTS 結果已標記需重跑。"
          : data.audio_changed
            ? "已同步；音檔設定有變更，舊 TTS 結果已標記需重跑。"
            : "已同步到中央控制表。";
      }
      window.setTimeout(()=>requestTaskStatuses(),150);
    }else if(status){
      status.textContent="語言設定同步失敗，請稍後再試。";
    }
  }

  if(data.type==="status_health"){
    const syncState=document.getElementById("status-sync-state");
    const syncText=document.getElementById("status-sync-text");
    if(data.ok){
      bridgeProtocolVersion=Number(data.bridge_protocol||0);
      const protocolOk=bridgeProtocolVersion>=REQUIRED_BRIDGE_PROTOCOL;
      if(syncState){
        syncState.textContent=protocolOk ? "狀態表已連線" : "控制中心版本過舊";
        syncState.className=protocolOk ? "ok" : "warn";
      }
      const apiState=document.getElementById("api-state");
      if(apiState){
        apiState.textContent=protocolOk
          ? "Apps Script 已連線"
          : "Apps Script 需重新部署";
        apiState.className=protocolOk ? "ok" : "warn";
      }
      if(syncText){
        syncText.textContent=protocolOk
          ? "執行狀態表目前 "+String(data.rows||0)+" 筆紀錄・Bridge v"+bridgeProtocolVersion
          : "GitHub 前端需要 Bridge v"+REQUIRED_BRIDGE_PROTOCOL+
            "，目前部署回報 v"+bridgeProtocolVersion+"；讀取功能可繼續，但已阻止新工作送出。";
      }
      youtubeCookiesConfigured=!!data.youtube_cookies_configured;
      const cookieState=document.getElementById("youtube-cookie-state");
      if(cookieState){
        if(youtubeCookiesConfigured){
          cookieState.textContent="Apps Script 已設定";
          cookieState.className="ok";
        }else{
          cookieState.textContent="未設定（guest PO token／匿名模式可用）";
          cookieState.className="ok";
        }
      }
      if(bridgeProtocolVersion>=REQUIRED_BRIDGE_PROTOCOL){
        setDashboardBridgeState("控制中心已連線，正在同步任務…","working");
      }else{
        setDashboardBridgeState(
          "控制中心可讀取，但 Apps Script 部署版本落後；請重新部署 Code.gs 後再執行新工作。",
          "error"
        );
      }
      requestLanguageSettings();
      requestTasksFromControlCenter();
    }else if(syncState){
      const reason=data.message || data.error || "未知錯誤";
      syncState.textContent="狀態表連線失敗";
      syncState.className="warn";
      if(syncText) syncText.textContent="狀態表連線失敗："+reason;
    }
  }
});

document.getElementById("schedule-task-select")?.addEventListener("change",()=>{
  const task=scheduleSelectedTask();
  const period=document.getElementById("schedule-new-period");
  const lesson=document.getElementById("schedule-new-lesson");
  if(task){
    if(period) period.value=String(task.period||"");
    if(lesson) lesson.value=String(
      Number(String(task.lesson||"").replace(/\D/g,""))||1
    );
  }
  updateSchedulePreview();
});
document.getElementById("schedule-new-period")?.addEventListener("input",updateSchedulePreview);
document.getElementById("schedule-new-lesson")?.addEventListener("change",updateSchedulePreview);
document.getElementById("schedule-apply")?.addEventListener("click",applyScheduleChange);

document.getElementById("drive-name-migrate-all")?.addEventListener("click",()=>{
  const state=document.getElementById("drive-name-state");
  const status=document.getElementById("drive-name-status");
  const button=document.getElementById("drive-name-migrate-all");

  if(bridgeProtocolVersion<REQUIRED_BRIDGE_PROTOCOL){
    if(status){
      status.textContent=
        "Apps Script 尚未部署支援正式檔名的最新版，請先重新部署。";
    }
    return;
  }

  const sent=submitBridgePost({action:"drive_names_migrate"});
  if(!sent){
    if(status) status.textContent="工作未送出；請重新連線控制中心後再試。";
    return;
  }
  if(button) button.disabled=true;
  if(state){
    state.textContent="整理中";
    state.className="badge";
  }
  if(status){
    status.textContent="正在整理所有既有課程的 Google Drive 檔名…";
  }
});

document.getElementById("youtube-capture-period")?.addEventListener("change",()=>{
  renderYoutubeAudioTasks(true);
});
document.getElementById("youtube-audio-task")?.addEventListener("change",()=>{
  renderYoutubeAudioTasks(true);
});
document.getElementById("youtube-capture-refresh")?.addEventListener("click",()=>{
  const task=youtubeAudioSelectedTask();
  requestTaskStatuses();
  if(task) requestYoutubeCaptureFiles(task.id,true);
});
document.querySelectorAll('input[name="youtube-capture-type"]').forEach(input=>{
  input.addEventListener("change",syncYoutubeCaptureModeUi);
});
document.getElementById("youtube-audio-all")?.addEventListener("change",event=>{
  const disabled=!!event.target.checked;
  document.querySelectorAll("[data-youtube-audio-lang]").forEach(input=>{
    input.disabled=disabled;
  });
  const custom=document.getElementById("youtube-audio-custom-langs");
  if(custom) custom.disabled=disabled;
});
document.getElementById("youtube-audio-run")?.addEventListener("click",runYoutubeAudioGrab);
syncYoutubeCaptureModeUi();

document.getElementById("save-language-plan")?.addEventListener("click",saveLanguagePlanForSelectedTask);
document.getElementById("refresh-language-settings")?.addEventListener("click",()=>{
  requestLanguageSettings();
  if(selectedTaskId) requestLanguagePlan(selectedTaskId);
});

function initStatusPolling(){
  window.setTimeout(()=>{
    if(bridgeKeyValue()){
      syncStudioNow();
    }else{
      requestTasksFromControlCenter();
    }
  },700);

  window.setInterval(()=>{
    if(!bridgeKeyValue()) return;
    requestTaskStatuses();
  },STATUS_POLL_MS);

  window.setInterval(()=>{
    if(!bridgeKeyValue()) return;
    requestTasksFromControlCenter();
  },60000);
}
function setWorkerStatus(message,state="idle"){
  const box=document.getElementById("web-worker-status");
  const badge=document.getElementById("web-worker-state");
  if(box) box.textContent=message;
  if(!badge) return;

  badge.className="badge";
  if(state==="ready"){
    badge.classList.add("complete");
    badge.textContent="已建立";
  }else if(state==="verified"){
    badge.classList.add("complete");
    badge.textContent="正式橋樑已驗證";
  }else if(state==="sending"){
    badge.textContent="處理中";
  }else if(state==="error"){
    badge.classList.add("bridge-error");
    badge.textContent="需要檢查";
  }else{
    badge.textContent="尚未驗證";
  }
}

document.getElementById("worker-setup")?.addEventListener("click",()=>{
  const sent=submitBridgePost({action:"worker_setup"});
  if(!sent){
    setWorkerStatus("尚未設定 Apps Script URL 或 Bridge Key。","error");
    return;
  }
  setWorkerStatus(
    "已送出建立 Web Worker。請等待 GitHub Actions 的 Kaggle Web Worker Setup 執行。",
    "sending"
  );
});

document.getElementById("worker-secret-test")?.addEventListener("click",()=>{
  const sent=submitBridgePost({action:"worker_secret_test"});
  if(!sent){
    setWorkerStatus("尚未設定 Apps Script URL 或 Bridge Key。","error");
    return;
  }
  setWorkerStatus(
    "已送出私人憑證資料集測試。GitHub Actions 會建立無敏感測試資料集並驗證 Kaggle API 觸發後是否可讀取。",
    "sending"
  );
});

function setBridgeStatus(message, state="idle"){
  const status=document.getElementById("bridge-status");
  const badge=document.getElementById("bridge-state");
  if(status) status.textContent=message;
  if(!badge) return;

  badge.className="badge";
  if(state==="ready"){
    badge.classList.add("complete");
    badge.textContent="已設定";
  }else if(state==="sending"){
    badge.textContent="送出中";
  }else if(state==="sent"){
    badge.classList.add("complete");
    badge.textContent="已送出";
  }else if(state==="error"){
    badge.classList.add("bridge-error");
    badge.textContent="需要檢查";
  }else{
    badge.textContent="尚未設定";
  }
}

function initBridgePanel(){
  // 舊版曾把 URL 寫進 localStorage，v23 起固定使用 config.js，避免舊網址干擾同步。
  localStorage.removeItem(BRIDGE_ENDPOINT_KEY);

  const dashboardKey=document.getElementById("dashboard-bridge-key");
  const connectButton=document.getElementById("dashboard-bridge-connect");
  const testButton=document.getElementById("bridge-test");
  const endpointDisplay=document.getElementById("bridge-endpoint-display");

  if(endpointDisplay){
    endpointDisplay.textContent=BRIDGE_ENDPOINT ? "已內建／可用" : "未設定";
  }

  const savedKey=sessionStorage.getItem(BRIDGE_SESSION_KEY) || "";
  if(dashboardKey) dashboardKey.value=savedKey;

  const connect=()=>{
    const key=dashboardKey?.value.trim() || "";
    if(!key){
      setDashboardBridgeState("請輸入 Bridge Key。","error");
      dashboardKey?.focus();
      return;
    }
    sessionStorage.setItem(BRIDGE_SESSION_KEY,key);
    syncStudioNow();
  };

  connectButton?.addEventListener("click",connect);
  dashboardKey?.addEventListener("keydown",event=>{
    if(event.key==="Enter"){
      event.preventDefault();
      connect();
    }
  });
  dashboardKey?.addEventListener("input",()=>{
    const key=dashboardKey.value.trim();
    if(key){
      sessionStorage.setItem(BRIDGE_SESSION_KEY,key);
      setDashboardBridgeState("Bridge Key 已輸入，按「連線控制中心」開始同步。","idle");
    }else{
      sessionStorage.removeItem(BRIDGE_SESSION_KEY);
      setDashboardBridgeState("請輸入 Bridge Key。","idle");
    }
  });

  if(savedKey){
    setDashboardBridgeState("正在自動重新連線中央控制中心…","working");
    window.setTimeout(()=>syncStudioNow(),250);
  }else{
    setDashboardBridgeState("請輸入 Bridge Key 以載入 Google Sheet 任務。","idle");
  }

  testButton?.addEventListener("click",()=>{
    if(!bridgeKeyValue()){
      setBridgeStatus("請先回總覽輸入 Bridge Key。","error");
      showView("dashboard");
      dashboardKey?.focus();
      return;
    }

    testButton.disabled=true;
    setBridgeStatus("正在送出網頁 → GitHub → Kaggle 測試…","sending");
    submitBridgePost({action:"smoke"});

    window.setTimeout(()=>{
      testButton.disabled=false;
      setBridgeStatus(
        "測試已送出。到 GitHub Actions 查看新的「Kaggle Run Bridge Test」。",
        "sent"
      );
    },1500);
  });

  setBridgeStatus(
    BRIDGE_ENDPOINT
      ? "Apps Script URL 已內建。日常只需要從總覽連線控制中心。"
      : "Apps Script URL 尚未設定。",
    BRIDGE_ENDPOINT ? "ready" : "error"
  );
}
async function pingBackend(){
  if(!cfg.apiBaseUrl) return;
  try{
    const r=await fetch(cfg.apiBaseUrl.replace(/\/$/,"")+"/health");
    if(!r.ok) throw new Error();
    document.getElementById("backend-text").textContent="後端已連線";
    document.querySelector(".backend-pill .status-dot").style.background="#56b981";
    document.getElementById("api-state").textContent="已連線";
    document.getElementById("api-state").className="ok";
  }catch{
    document.getElementById("backend-text").textContent="後端離線";
  }
}

updateTaskCodes();
renderPipeline();
renderTasks();
renderTerms();
updateBackButton();
initBridgePanel();
initStatusPolling();
pingBackend();

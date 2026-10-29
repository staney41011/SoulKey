const cfg = window.SOULKEY_CONFIG || {};

const STORE = {
  tasks: "soulkey_studio_tasks_v2",
  terms: "soulkey_studio_terms_v1",
  gpu: "soulkey_studio_gpu_v1"
};

const BRIDGE_ENDPOINT_KEY = "soulkey_bridge_endpoint_v1";
const BRIDGE_SESSION_KEY = "soulkey_bridge_key_session_v1";
const BRIDGE_ENDPOINT = String(cfg.bridgeEndpoint || "").trim();
const STATUS_POLL_MS = 30000;
const REQUIRED_BRIDGE_PROTOCOL = 9;
let bridgeProtocolVersion = 0;
const REVIEW_CACHE_BASE = String(cfg.reviewCacheBaseUrl || "https://raw.githubusercontent.com/staney41011/SoulKey/main/studio-review-cache").replace(/\/$/,"");
const ZH_RENDER_BATCH = 80;
let bridgeClientReady = false;
let bridgeAuthenticated = false; // true only after verified health AND central tasks are loaded
let driveOwnerConfigured = false; // requires verified owner OAuth before Drive publishing
let youtubeCCQueueEnabled = false; // set only by authenticated Cloud Run health
let bridgeIsCloudRecovery = false;
let firebaseSnapshotReadOnly=false; // verified encrypted Firebase snapshot, NEVER enables mutations
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

const YOUTUBE_CC_TARGETS = ["en"]; // Captions only; other languages use the translation pipeline.

function load(key, fallback){
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}
function save(key, value){ localStorage.setItem(key, JSON.stringify(value)); }

const REVIEW_CACHE_PREFIX = "soulkey_review_cache_v1:";
const reviewRequestStartedAt = {};
const reviewCacheSeedRequested = new Set();
const englishCacheSeedRequested = new Set();

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

let tasks = []; // Never expose or edit browser-only lessons before central authentication.
// Local browser drafts cannot launch cloud workers until centrally confirmed.
let confirmedRemoteTaskIds = new Set();
let terms = load(STORE.terms, seedTerms);
let languageSettings = [
  {code:"en",name:"English",can_ai_translate:false,can_tts:true},
  {code:"th",name:"ภาษาไทย",can_ai_translate:true,can_tts:true},
  {code:"es",name:"Español",can_ai_translate:true,can_tts:true},
  {code:"id",name:"Bahasa Indonesia",can_ai_translate:true,can_tts:true},
  {code:"vi",name:"Tiếng Việt",can_ai_translate:true,can_tts:true},
  {code:"hi",name:"हिन्दी",can_ai_translate:true,can_tts:true},
  {code:"ta",name:"தமிழ்",can_ai_translate:true,can_tts:true},
  {code:"ja",name:"日本語",can_ai_translate:true,can_tts:true},
  {code:"ko",name:"한국어",can_ai_translate:true,can_tts:true},
  {code:"km",name:"ភាសាខ្មែរ",can_ai_translate:true,can_tts:true},
  {code:"bn",name:"বাংলা",can_ai_translate:true,can_tts:true},
  {code:"ne",name:"नेपाली",can_ai_translate:true,can_tts:true},
  {code:"lo",name:"ພາສາລາວ",can_ai_translate:true,can_tts:true},
  {code:"my",name:"မြန်မာဘာသာ",can_ai_translate:true,can_tts:true},
  {code:"it",name:"Italiano",can_ai_translate:true,can_tts:true},
  {code:"pt",name:"Português (Brasil)",can_ai_translate:true,can_tts:true}
];
let selectedTaskId = null;
let selectedPeriod = null;
let currentZhReview = [];
let zhFinalPendingTaskId = "";
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
// Only an authenticated task-matched Bridge read can authorize editing/finalizing.
let englishCanonicalLoadedTaskId = "";
let englishDraftSavePendingId = null;
const englishDraftSaveQueuedIds = new Set();
let englishDraftSavePendingIds = new Set();
const englishReviewDirtyIds = new Set();
const englishCloudOverridesByTask={};
let englishDraftSaveRequestId = "";
let englishDraftSaveWatchdog = null;
let englishDraftSavedSnapshot = null;
// Only acknowledgements from Drive-backed saves may enter this local cache.
const ENGLISH_DRIVE_ACK_PREFIX="soulkey_en_drive_ack:";
const ENGLISH_UNCONFIRMED_BACKUP_PREFIX="soulkey_en_unsaved_backup:";
const ENGLISH_FINAL_PENDING_PREFIX="soulkey_en_final_pending:";
let englishFinalizePendingTaskId = "";
let englishFinalizePriorFinishedAt = "";
let englishFinalizeWatchdog = null;
let pendingRunStageRequest=null;
let pendingYoutubeCapture=null;
// A confirmed Drive acknowledgement applies to its own task only.
const englishFinalizedThisSession = new Set();
const englishSheetFinalizedThisSession = new Set();
let currentView = "dashboard";
const viewHistory = [];
const youtubeCaptureFilesCache = {};
const youtubeCaptureFilesFetchedAt = {};
let youtubeCaptureFilesLoadingTask = "";
const courseFilesCache = {};
const courseFilesFetchedAt = {};
let courseFilesLoadingTask = "";
const ttsShareLinksCache = {};
const ttsShareLinksFetchedAt = {};
const ttsShareLinkErrors = {};
let ttsShareLoadingTask = "";
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

async function restoreFirebaseSnapshot(){
  const input=document.getElementById("dashboard-firebase-key");
  const button=document.getElementById("dashboard-firebase-connect");
  const message=document.getElementById("dashboard-firebase-message");
  if(!input?.value.trim()){if(message)message.textContent="請輸入 Firebase 專用存取碼";return false;}
  if(button)button.disabled=true;
  if(message)message.textContent="正在驗證並讀取 Firebase 課程快照…";
  try{
    // Same-origin GitHub Pages path; no Apps Script, no third-party cookies.
    const url=new URL("../firebase-control-center/public/data.enc.json",window.location.href);
    const response=await fetch(url.toString(),{cache:"no-store"});
    if(!response.ok)throw new Error("無法取得 Firebase 資料（HTTP "+response.status+"）");
    const blob=await response.json();
    const asBytes=base64=>Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
    const textEncoder=new TextEncoder();
    const material=await crypto.subtle.importKey("raw",textEncoder.encode(input.value.trim()),"PBKDF2",false,["deriveKey"]);
    const key=await crypto.subtle.deriveKey({
      name:"PBKDF2",salt:asBytes(blob.salt),iterations:blob.iterations,hash:"SHA-256"
    },material,{name:"AES-GCM",length:256},false,["decrypt"]);
    let plain;
    try{
      plain=await crypto.subtle.decrypt({
        name:"AES-GCM",iv:asBytes(blob.iv),additionalData:textEncoder.encode("SoulKey-Firebase-Snapshot-v1")
      },key,asBytes(blob.ciphertext));
    }catch(_){throw new Error("Firebase 存取碼不正確，或快照無法驗證");}
    const data=JSON.parse(new TextDecoder().decode(plain));
    if(!Array.isArray(data.tasks)||!data.tasks.length ||
       !data.tasks.every(t=>/^P\d+-L\d+$/i.test(String(t.id||""))&&/^SKC-\d+$/i.test(String(t.course_uid||""))))
       throw new Error("課程資料格式或固定 UID 驗證失敗");
    input.value="";
    firebaseSnapshotReadOnly=true;
    bridgeAuthenticated=true;  // permits existing read-only dashboard renderer
    confirmedRemoteTaskIds=new Set();
    tasks=data.tasks.map(x=>normalizeTask({
      id:x.id,period:x.period,lesson:x.lesson,title:x.title,
      youtubeUrl:x.youtubeUrl,course_uid:x.course_uid,
      progress:x.progress,asr:x.asr,zh:x.zh,en:x.en,tts:x.tts,
      workflowVersion:WORKFLOW_VERSION,completedStep:-1,languagePlan:[]
    }));
    selectedPeriod=Math.max(...tasks.map(x=>Number(x.period)||0));
    // Snapshot is NEVER merged into local drafts or uploaded to central Sheets.
    renderTasks();
    const state=document.getElementById("stat-tasks");
    if(state)state.textContent=String(tasks.length);
    setDashboardBridgeState(
      "Firebase 已恢復 "+tasks.length+" 堂課的唯讀總覽（備援快照，非即時狀態）。目前禁止調課、定稿與啟動 Kaggle。",
      "ok"
    );
    const badge=document.getElementById("dashboard-bridge-state");
    if(badge)badge.textContent="Firebase 唯讀";
    if(message)message.textContent="已驗證 "+tasks.length+" 堂課。查看課程可用；寫入功能仍待後端恢復。";
    showView("dashboard");
    return true;
  }catch(error){
    if(message)message.textContent="Firebase 備援讀取失敗："+String(error.message||error);
    return false;
  }finally{if(button)button.disabled=false;}
}

function syncStudioNow(){
  firebaseSnapshotReadOnly=false;
  const key=bridgeKeyValue();
  if(!BRIDGE_ENDPOINT){
    setDashboardBridgeState("系統尚未設定 Cloud Run 橋樑網址。","error");
    return false;
  }
  if(!key){
    setDashboardBridgeState("請先輸入 Bridge Key。","idle");
    return false;
  }

  bridgeAuthenticated=false;
  confirmedRemoteTaskIds=new Set();
  sessionStorage.setItem(BRIDGE_SESSION_KEY,key);
  setDashboardBridgeState("正在驗證控制中心，再讀取正式課程…","working");
  // A single health probe first. Previously 3 JSONP calls plus iframe
  // duplicated tasks/status/language requests and delayed the dashboard.
  requestStatusHealth();
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
  if(firebaseSnapshotReadOnly && name!=="dashboard"){
    setDashboardBridgeState("Firebase 備援目前只有課程總覽，不可修改課程、人工定稿或執行翻譯。","ok");
    name="dashboard";
  }
  if(name!=="dashboard" && !bridgeAuthenticated){
    setDashboardBridgeState("請先完成控制中心連線驗證，才能開啟課程或修改資料。","error");
    name="dashboard";
  }
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
  window.setTimeout(updateZhReviewVideoFloat,0);

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
      .filter(item=>item && ["queued","running","delayed","error","stale"].includes(item.status));

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
      (["error","stale"].includes(remote.status) ||
        (["multi","tts"].includes(workflow[i].key) && remote.status==="needs_review")) &&
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
      // A stale timestamp is NOT proof of an upstream data change.
      // Reserve "stale" for actual dependency invalidation from backend.
      copy.original_status=copy.status;
      copy.status="delayed";
      copy.message=(copy.message ? copy.message+"；" : "")+
        (copy.original_status==="queued"
         ? "排隊超過30分鐘，GitHub Worker 尚未領取；請檢查 Actions 與 Cloud Run 部署，勿重複派送"
         : "執行中超過30分鐘未更新；請檢查 Worker 紀錄，勿重複派送");
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
    stale:"上游資料已失效，需檢查",
    delayed:"工作逾時未回報（勿重複派送）"
  };
  return map[status] || status || "";
}

function remoteErrorReason(item){
  if(!item || String(item.status||"")!=="error") return "";
  return String(
    item.root_error_message ||
    item.error_message ||
    item.message ||
    ""
  ).trim();
}

function activeRemoteStatus(task){
  for(const stage of workflow){
    const item=remoteStageStatus(task,stage.key);
    if(!item) continue;
    if(["queued","running","delayed","needs_review","error","stale"].includes(item.status)){
      return item;
    }
  }
  return null;
}

function mergeRemoteTasks(remoteTasks){
  if(!Array.isArray(remoteTasks)) return;
  confirmedRemoteTaskIds = new Set(remoteTasks.map(t=>String(t.id||"")));

  const localTasks=load(STORE.tasks,[]);
  const localById=Object.fromEntries(localTasks.map(t=>[t.id,t]));
  const localByUid=Object.fromEntries(localTasks
    .filter(t=>String(t.course_uid||"").trim())
    .map(t=>[String(t.course_uid),t]));
  const merged=remoteTasks.map(remote=>{
    // SKC is immutable. Reusing an old Pxxx-Lxx for a different course
    // must NEVER borrow the previous course's local drafts or stage cache.
    const stableUid=String(remote.course_uid||"").trim();
    const local=stableUid
      ? (localByUid[stableUid] || {})
      : (localById[remote.id] || {});
    const task={
      ...local,
      ...remote,
      id:remote.id,
      workflowVersion:local.workflowVersion || WORKFLOW_VERSION,
      completedStep:Number.isInteger(local.completedStep) ? local.completedStep : -1,
      languagePlan:Array.isArray(local.languagePlan) ? local.languagePlan : []
    };
    normalizeTask(task);
    if(bridgeIsCloudRecovery && /^已退回：/.test(String(local.status||""))){
      // Previous UI rollback only touched localStorage. Discard the misleading
      // local status while preserving central Sheet and all draft manuscripts.
      task.status=String(remote.status||"中央工作狀態已同步");
      delete task.rollbackStage;
      delete task.rollbackAt;
    }
    return task;
  });

  // Central control sheet is authoritative. Browser-only drafts never
  // reappear as actionable lessons and can never be reuploaded implicitly.
  tasks=merged;
  if(!selectedPeriod && tasks.length){
    selectedPeriod=Math.max(...tasks.map(x=>Number(x.period)||0));
  }
  save(STORE.tasks,tasks);
  renderTasks();
}

function requestTasksFromControlCenter(){
  const sent=bridgeProtocolVersion>=REQUIRED_BRIDGE_PROTOCOL
    ? jsonpBridgeRequest({action:"tasks_get"}) : false;
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

function githubReviewUrl(taskId,kind="zh"){
  const file=kind==="en"?"en.json":"zh.json";
  return REVIEW_CACHE_BASE+"/"+encodeURIComponent(String(taskId||""))+"/"+file+"?_="+Date.now();
}

// Same-origin GitHub Pages static JSON normally beats a cross-domain raw
// GitHub handshake. Race both sources, because Pages can deploy a few seconds
// after the GitHub branch update. No Drive/Apps Script round trip is needed.
const fastReviewRequests=new Map();
function fastReviewUrl(taskId,kind="zh"){
  const file=kind==="en"?"en.json":"zh.json";
  return new URL(
    "../studio-review-cache/"+encodeURIComponent(String(taskId||""))+"/"+file+
    "?_="+Date.now(),window.location.href
  ).toString();
}
function invalidateReviewFetch(taskId,kind){
  fastReviewRequests.delete(String(taskId)+"|"+String(kind));
}
function fetchReviewPayload(taskId,kind="zh",options={}){
  const key=String(taskId)+"|"+String(kind);
  const cached=fastReviewRequests.get(key);
  if(!options.force && cached && Date.now()-cached.created<12000){
    return cached.promise;
  }
  const paths=[fastReviewUrl(taskId,kind),githubReviewUrl(taskId,kind)];
  const promises=paths.map(async url=>{
    const controller=new AbortController();
    const timer=window.setTimeout(()=>controller.abort(),5000);
    try{
      const response=await fetch(url,{
        cache:"no-store",signal:controller.signal,
        headers:{"Accept":"application/json"}
      });
      if(!response.ok) throw new Error("HTTP "+response.status);
      const payload=await response.json();
      if(!Array.isArray(payload?.segments) ||
         (payload.task_id && String(payload.task_id)!==String(taskId))){
        throw new Error("課程快取不完整");
      }
      return payload;
    }finally{window.clearTimeout(timer);}
  });
  const promise=Promise.any(promises);
  fastReviewRequests.set(key,{created:Date.now(),promise});
  promise.catch(()=>{
    // A missing cache may be published after Chinese Final; a second
    // attempt must not be stuck on a cached 404.
    if(fastReviewRequests.get(key)?.promise===promise){
      fastReviewRequests.delete(key);
    }
  });
  return promise;
}
function prefetchReviewPayloads(taskId){
  if(!taskId) return;
  fetchReviewPayload(taskId,"zh").catch(()=>{});
  fetchReviewPayload(taskId,"en").catch(()=>{});
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
    let data;
    try{
      data=await fetchReviewPayload(taskId,"zh");
    }catch(cacheError){
      if(!reviewCacheSeedRequested.has(String(taskId))){
        const seeded=submitBridgePost({
          action:"review_cache_seed",task_id:String(taskId||"")
        });
        if(seeded) reviewCacheSeedRequested.add(String(taskId));
      }
      setZhReviewLoadState("快取尚未就緒・改由 Google Drive 載入…","working");
      if(requestReviewData(taskId,"zh",0)) return;
      throw cacheError;
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
function quickReviewUrl(task,step=""){
  const videoId=youtubeVideoIdFromUrl(task?.url||"");
  const url=new URL("./review.html",window.location.href);
  url.searchParams.set("task",String(task?.id||""));
  if(videoId) url.searchParams.set("video",videoId);
  if(step) url.searchParams.set("step",String(step));
  return url.toString();
}

function openQuickReview(taskId){
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;

  // Never re-seed on every open: the human editor may have an unsaved or
  // recently saved GitHub draft. Quick Review repairs only a proven missing
  // snapshot or an out-of-date published Final revision.
  const popup=window.open(quickReviewUrl(task),"_blank");
  if(popup){
    try{
      const key=bridgeKeyValue();
      if(key) popup.sessionStorage.setItem(BRIDGE_SESSION_KEY,key);
    }catch(_){}
  }
}

function cloudStageUnavailable(stage){
  return !!(bridgeIsCloudRecovery && stage && (stage.key==="zh" || stage.key==="tts"));
}

function renderTasks(){
  const el=document.getElementById("task-list");

  renderPeriodSelector();

  if(!bridgeAuthenticated){
    el.innerHTML='<div class="empty">請先連線控制中心並完成驗證；未連線時禁止建立或修改課程。</div>';
  }else if(!tasks.length){
    el.innerHTML='<div class="empty">中央控制表尚無任務。連線後可在「建立任務」新增課程。</div>';
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
      const cloudConfirmed=confirmedRemoteTaskIds.has(t.id);
      const remoteActive=activeRemoteStatus(t);
      const nextRemote=next ? remoteStageStatus(t,next.key) : null;
      const failureReason=remoteErrorReason(remoteActive);
      const stageUnavailable=cloudStageUnavailable(next);
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
              (!cloudConfirmed?"本機草稿（尚未同步）":complete?"全部完成":"下一步："+escapeHtml(next.label))+
            '</span>'+
            '<span class="muted">'+escapeHtml(
              remoteActive
                ? remoteStatusText(remoteActive.status)+
                  (remoteActive.status!=="delayed" && remoteActive.progress ? " "+remoteActive.progress+"%" : "")
                : t.status
            )+'</span>'+
          '</div>'+
          (failureReason
            ? '<div class="course-error-reason"><b>失敗原因</b><span>'+escapeHtml(failureReason)+'</span></div>'
            : '')+
        '</div>'+
        '<div class="course-task-actions">'+
          '<button class="ghost task-review-btn" data-review-task="'+escapeHtml(t.id)+'" '+
            (!(remoteStageStatus(t,"zh") && ["needs_review","done"].includes(remoteStageStatus(t,"zh").status)) ? "disabled" : "")+
            '>人工中文定稿</button>'+
          '<button class="ghost task-quick-btn" data-quick-task="'+escapeHtml(t.id)+'" '+
            (!(remoteStageStatus(t,"zh") && ["needs_review","done"].includes(remoteStageStatus(t,"zh").status)) ? "disabled" : "")+
            '>快速流程</button>'+
          '<button class="primary task-next-btn" data-next-task="'+escapeHtml(t.id)+'" '+
            (complete || stageUnavailable || !cloudConfirmed || pendingRunStageRequest?.taskId===t.id || (nextRemote && ["queued","running","delayed"].includes(nextRemote.status)) ? "disabled" : "")+'>'+
            (!cloudConfirmed
              ? "等待雲端同步"
              : complete
              ? "已完成"
              : stageUnavailable
              ? "此步驟待恢復"
              : nextRemote && nextRemote.status==="running"
                ? "執行中 "+(nextRemote.progress||"")+"%"
                : nextRemote && nextRemote.status==="queued"
                  ? "排隊中"
                  : nextRemote && nextRemote.status==="delayed"
                    ? "已派送，待確認"
                  : nextRemote && nextRemote.status==="error"
                    ? "重新執行"
                    : "執行下一步")+
          '</button>'+
          ''+
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

function ccCompletedLanguageCodes(files){
  const found=new Set();
  (Array.isArray(files)?files:[]).forEach(file=>{
    const raw=String(file?.name||"");
    const match=raw.match(/youtube\.([^.]+)\.transcript\.txt$/i);
    if(!match) return;
    const code=String(match[1]||"").toLowerCase().replace("_","-");
    const base=code.split("-",1)[0];
    if(YOUTUBE_CC_TARGETS.includes(code)) found.add(code);
    else if(YOUTUBE_CC_TARGETS.includes(base)) found.add(base);
  });
  return [...found];
}

function captureStateInfo(task,kind,files){
  const list=Array.isArray(files)?files:[];
  const remote=task?.remoteStages?.[kind==="cc" ? "cc" : "youtube-audio"] || null;
  const status=String(remote?.status||"").toLowerCase();
  const message=String(remote?.message||remote?.error_message||"").trim();
  const ccDone=kind==="cc" ? ccCompletedLanguageCodes(list).length : 0;
  const ccTotal=YOUTUBE_CC_TARGETS.length;
  const ccDetail=ccDone
    ? ccDone+"/"+ccTotal+" 語已有可閱讀的純逐字稿。"
    : "尚未找到可閱讀的外語 CC 純逐字稿。";

  if(status==="running" || status==="queued"){
    return {key:"working",label:status==="queued"?"佇列已登記":"執行中",
      detail:message || (status==="queued"?"等待 Worker 實際領取，不代表已在 Kaggle 執行。":
      "正在等待 Worker 的資料回報。")};
  }
  if(status==="done"){
    if(kind==="cc" && ccDone===0){
      return {key:"error",label:"缺少已驗證字幕",
        detail:"執行狀態雖記錄完成，但目前沒有對應本堂、可讀取的 CC 成果；不可視為完成。"};
    }
    if(message.includes("NO_YOUTUBE_CC")){
      return {
        key:"idle",
        label:"無可用 CC",
        detail:"YouTube 沒有提供字幕軌；請改用中文 ASR，外語由 SoulKey 翻譯流程產生。"
      };
    }
    const match=message.match(/(\d+)\/(\d+)\s*語言完成/);
    const messagePartial=match && Number(match[1])<Number(match[2]);
    const filePartial=kind==="cc" && ccDone>0 && ccDone<ccTotal;
    const partial=!!(messagePartial || filePartial);
    return {
      key:partial ? "partial" : "complete",
      label:partial ? "部分完成" : "已抓取完成",
      detail:message || (
        kind==="cc"
          ? (ccDone===ccTotal ? ccTotal+"/"+ccTotal+" 語純逐字稿已齊全。" : ccDetail)
          : list.length
            ? "雲端目前有 "+list.length+" 個音檔。"
            : "工作已完成，正在同步雲端檔案。"
      )
    };
  }
  if(status==="error"){
    if(kind==="cc" && ccDone){
      return {
        key:"partial",
        label:"部分完成",
        detail:ccDetail+(message ? "｜最近一次錯誤："+message : "")
      };
    }
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
    if(kind==="cc" && ccDone){
      return {key:"partial",label:"部分完成",detail:ccDetail+"｜目前結果需要重新確認。"};
    }
    return {
      key:list.length ? "partial" : "error",
      label:list.length ? "部分檔案已存在" : "需重新執行",
      detail:message || "目前結果已標記為過期。"
    };
  }
  if(kind==="cc"){
    if(ccDone===ccTotal){
      return {key:"complete",label:"已抓取完成",detail:ccTotal+"/"+ccTotal+" 語純逐字稿已齊全。"};
    }
    if(ccDone>0){
      return {key:"partial",label:"部分完成",detail:ccDetail};
    }
    if(list.length){
      return {
        key:"partial",
        label:"處理中資料已存在",
        detail:"Drive 已有 CC 處理檔，但尚未找到可閱讀的純逐字稿。"
      };
    }
  }
  if(list.length){
    return {key:"complete",label:"已抓取完成",detail:"Drive 已找到 "+list.length+" 個音檔。"};
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
      // CC list exposes only the pure transcript. Keep JSON / timeline TXT /
      // SRT on Drive for downstream processing but hide them from Studio.
      return (
        /\.transcript\.txt$/i.test(raw) ||
        /CC純逐字稿\.txt$/i.test(display)
      );
    }

    if(kind==="asr"){
      // Chinese source follows the same user-facing rule: only show the
      // no-timestamp transcript, not ASR JSON / timeline TXT / SRT.
      return (
        /zh-TW\.transcript\.txt$/i.test(raw) ||
        /中文純逐字稿\.txt$/i.test(display)
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
      (file.storage==="google-sheet"
        ? '<button class="secondary" type="button" data-cc-download="'+escapeHtml(file.job_id||"")+
          '" data-cc-task="'+escapeHtml(file.task_id||"")+
          '" data-cc-lang="'+escapeHtml(file.lang||"")+'">下載中央字幕</button>'
        : '<a href="'+escapeHtml(file.url||"#")+'" target="_blank" rel="noopener">開啟雲端檔案</a>')+
    '</div>';
  }).join("");
}

document.addEventListener("click",event=>{
  const button=event.target.closest("[data-cc-download]");
  if(!button)return;
  const fields={
    action:"youtube_cc_content",task_id:button.dataset.ccTask,
    job_id:button.dataset.ccDownload,language:button.dataset.ccLang
  };
  if(!bridgeClientRequest(fields) && !jsonpBridgeRequest(fields))
    alert("未能向中央控制中心請求這份字幕，請重新連線後再試。");
});

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
    badge.textContent="正在讀取中央字幕及 Drive 成果…";
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
  if(button){
    button.textContent=mode==="cc" ? "抓取 CC 字幕" : "抓取音軌";
    button.disabled=(mode==="audio"||!youtubeCCQueueEnabled||!!pendingYoutubeCapture);
  }
  if(status && !/已送出|Kaggle|完成|錯誤|處理中/.test(String(status.textContent||""))){
    status.textContent=mode==="audio"
      ? "音軌抓取尚未恢復，請先使用 CC 字幕功能；沒有送出任何音軌工作。"
      : !youtubeCCQueueEnabled
      ? "Cloud Run 尚未部署 YouTube CC 抓取佇列；目前沒有送出工作。"
      : "準備抓取本堂可取得的七語 YouTube CC；若某語言不存在，會保留實際取得的字幕。";
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
  if(mode==="audio"){
    if(status)status.textContent="音軌抓取尚未恢復，未向 Kaggle 送出任務。";
    return;
  }
  if(!youtubeCCQueueEnabled){
    if(status)status.textContent="目前 Cloud Run 尚未啟用 CC 抓取佇列；請先部署後端。";
    return;
  }

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

  if(pendingYoutubeCapture){
    if(status)status.textContent="上一次請求還沒收到控制中心回覆，請勿重複送出。";
    return;
  }
  pendingYoutubeCapture={taskId:task.id,mode};
  if(button)button.disabled=true;
  if(status)status.textContent="正在等待控制中心確認派工，還沒有啟動任何抓取工作…";
  const sent=submitBridgePost(payload);
  if(!sent){
    pendingYoutubeCapture=null;
    if(button)button.disabled=false;
    if(status)status.textContent="抓取工作未送出，請重新連線後再試。";
    return;
  }
  const pending=pendingYoutubeCapture;
  window.setTimeout(()=>{
    if(pendingYoutubeCapture===pending){
      pendingYoutubeCapture=null;
      if(button)button.disabled=false;
      if(status)status.textContent="控制中心未回覆是否接收；請先刷新中央任務狀態，不要連續送出。";
    }
  },35000);
}

function stageState(task,index){
  normalizeTask(task);
  const stage=workflow[index];
  const remote=remoteStageStatus(task,stage.key);

  if(remote){
    if(remote.status==="done") return "done";
    if(remote.status==="running") return "running";
    if(remote.status==="queued") return "queued";
    if(remote.status==="delayed") return "running";
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
  // Brand-new lessons default to all currently enabled languages. Existing lesson plans
  // remain opt-in for newly added languages: never silently rerun old lessons.
  const newLessonPlan=current.length===0;
  const defaultSixLanguages=new Set(["en","es","th","id","km","vi"]);

  return languageSettings.map(lang=>{
    const saved=byCode[lang.code] || {};
    const english = lang.code==="en";
    return {
      language_code:lang.code,
      language_name:lang.name,
      transcript_enabled:english ? true : (Object.prototype.hasOwnProperty.call(saved,"transcript_enabled") ? !!saved.transcript_enabled : (newLessonPlan&&defaultSixLanguages.has(lang.code))),
      transcript_source:english ? "human" : (saved.transcript_source || "ai"),
      audio_enabled:Object.prototype.hasOwnProperty.call(saved,"audio_enabled") ? !!saved.audio_enabled : (newLessonPlan&&defaultSixLanguages.has(lang.code)),
      audio_source:saved.audio_source || "tts"
    };
  });
}

const LANGUAGE_ZH_NAMES={
  en:"英文",th:"泰文",es:"西班牙文",id:"印尼文",vi:"越南文",
  hi:"印地語",ta:"泰米爾文",ja:"日文",ko:"韓文",km:"高棉文",
  bn:"孟加拉文",ne:"尼泊爾文",lo:"寮文",my:"緬甸文",it:"義大利文",pt:"葡萄牙文"
};

let languagePlanExpanded=false;
function languageDeliverableHtml(data,kind){
  const item=data?.[kind]||{status:"pending",label:"尚未查詢",url:""};
  const linked=(item.status==="ready"||item.status==="review") && !!item.url;
  const reason=item.reason
    ? '<small class="language-review-reason">待驗收：'+escapeHtml(item.reason)+'</small>' : "";
  if(linked){
    const url=escapeHtml(item.url);
    return '<div class="language-file-output '+(item.status==="review"?"review":"ready")+'">'+
      '<a href="'+url+'" target="_blank" rel="noopener noreferrer">'+escapeHtml(item.label)+'</a>'+
      '<button class="mini ghost" type="button" data-language-file-copy="'+url+'" aria-label="複製檔案連結">複製</button>'+
      reason+'</div>';
  }
  return '<span class="language-file-output pending">'+escapeHtml(item.label)+reason+'</span>';
}
function refreshLanguageDeliveryStatus(task){
  if(!task || task.id!==selectedTaskId) return;
  const list=document.getElementById("language-plan-list");
  if(!list || !window.SoulKeyLanguageDelivery) return;
  const course=courseFilesCache[task.id];
  const share=ttsShareLinksCache[task.id];
  list.querySelectorAll(".language-plan-row").forEach(row=>{
    const code=row.dataset.langPlan;
    const result=window.SoulKeyLanguageDelivery.resolve(task,code,course,share);
    ["doc","audio"].forEach(kind=>{
      const target=row.querySelector('[data-lang-delivery="'+kind+'"]');
      if(target) target.innerHTML=languageDeliverableHtml(result,kind);
    });
  });
  if(course?.ok){
    const status=document.getElementById("language-plan-status");
    const selected=list.querySelectorAll("[data-plan-enabled]:checked").length;
    if(status) status.textContent="已勾選 "+selected+" 種語言；Drive 成果已更新。更改勾選後請記得儲存。";
  }
}
function updateLanguagePlanExpansion(){
  const list=document.getElementById("language-plan-list");
  const btn=document.getElementById("language-plan-expand");
  if(!list || !btn) return;
  const total=list.querySelectorAll(".language-plan-row").length;
  const show=total>6;
  btn.hidden=!show;
  list.classList.toggle("expanded",languagePlanExpanded);
  btn.textContent=languagePlanExpanded?"收合語言":"顯示其餘 "+Math.max(0,total-6)+" 種語言";
  btn.setAttribute("aria-expanded",languagePlanExpanded?"true":"false");
  btn.onclick=()=>{languagePlanExpanded=!languagePlanExpanded;updateLanguagePlanExpansion();};
}
function attachLanguageFileCopy(list){
  list.onclick=event=>{
    const button=event.target.closest("[data-language-file-copy]");
    if(!button || !list.contains(button)) return;
    event.preventDefault();
    const url=button.dataset.languageFileCopy;
    if(!url) return;
    const completed=()=>{button.textContent="已複製";};
    if(navigator.clipboard && window.isSecureContext){
      navigator.clipboard.writeText(url).then(completed).catch(()=>window.prompt("請複製檔案連結：",url));
    }else window.prompt("請複製檔案連結：",url);
  };
}
function renderLanguagePlan(task){
  const list=document.getElementById("language-plan-list");
  const status=document.getElementById("language-plan-status");
  if(!list || !task) return;

  const plan=normalizedLanguagePlan(task);
  list.innerHTML=plan.map(item=>{
    const code=item.language_code;
    const english=code==="en";
    // Legacy plans may have chosen manuscript only. The unified UI migrates
    // such a selection to BOTH outputs only when the user saves the new plan.
    const selected=english ? item.audio_enabled :
      (item.transcript_enabled || item.audio_enabled);
    const zh=LANGUAGE_ZH_NAMES[code]||code;
    const local=item.language_name||code;
    return '<div class="language-plan-row" data-lang-plan="'+escapeHtml(code)+'">'+
      '<label class="language-selection"><input type="checkbox" data-plan-enabled aria-label="選擇'+escapeHtml(zh)+'，產生文稿與音檔" '+(selected?"checked":"")+'>'+
      '<span class="language-name"><b>'+escapeHtml(zh)+'</b><small>'+escapeHtml(local)+' · '+escapeHtml(code)+'</small></span></label>'+
      '<div class="language-delivery" data-lang-delivery="doc">尚未查詢</div>'+
      '<div class="language-delivery" data-lang-delivery="audio">尚未查詢</div>'+
    '</div>';
  }).join("");

  const refreshSelectionCount=()=>{
    if(!status) return;
    const selected=list.querySelectorAll("[data-plan-enabled]:checked").length;
    status.textContent=selected
      ? "已勾選 "+selected+" 種語言；每種均製作文稿＋音檔，請記得儲存。"
      : "未選擇額外輸出；英文人工 Final 仍會保留。";
  };
  list.querySelectorAll("[data-plan-enabled]").forEach(toggle=>{
    toggle.addEventListener("change",refreshSelectionCount);
  });
  attachLanguageFileCopy(list);
  updateLanguagePlanExpansion();
  refreshLanguageDeliveryStatus(task);
  refreshSelectionCount();
}

function collectLanguagePlan(){
  return [...document.querySelectorAll(".language-plan-row")].map(row=>{
    const code=row.dataset.langPlan;
    const lang=languageSettings.find(x=>x.code===code) || {name:code};
    const selected=!!row.querySelector("[data-plan-enabled]")?.checked;
    const english=code==="en";
    return {
      language_code:code,
      language_name:lang.name || code,
      transcript_enabled:english || selected,
      transcript_source:english ? "human" : "ai",
      audio_enabled:selected,
      audio_source:"tts"
    };
  });
}

function saveLanguagePlanForSelectedTask(){
  const task=tasks.find(x=>x.id===selectedTaskId);
  if(!task) return;

  const plan=collectLanguagePlan();
  task.languagePlan=plan;
  save(STORE.tasks,tasks);

  const selected=plan.filter(x=>x.audio_enabled);
  const status=document.getElementById("language-plan-status");

  if(!selected.length){
    if(status) status.textContent="已儲存：未選額外輸出；英文人工定稿仍保留。";
  }else{
    if(status) status.textContent="已儲存 "+selected.length+" 種語言（每種皆含文稿＋自然語音），正在同步控制中心…";
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

const COURSE_FILES_COLLAPSED_KEY="soulkey_course_files_collapsed";

function courseFilesCollapsed(){
  try{
    return localStorage.getItem(COURSE_FILES_COLLAPSED_KEY)!=="0";
  }catch(_){
    return true;
  }
}

function setCourseFilesCollapsed(collapsed,persist=true){
  const panel=document.getElementById("course-files-panel");
  const body=document.getElementById("course-files-body");
  const toggle=document.getElementById("course-files-toggle");
  const isCollapsed=!!collapsed;

  panel?.classList.toggle("collapsed",isCollapsed);
  if(body) body.hidden=isCollapsed;
  if(toggle){
    toggle.textContent=isCollapsed ? "顯示檔案總覽" : "隱藏檔案總覽";
    toggle.setAttribute("aria-expanded",isCollapsed ? "false" : "true");
  }

  if(persist){
    try{
      localStorage.setItem(COURSE_FILES_COLLAPSED_KEY,isCollapsed ? "1" : "0");
    }catch(_){}
  }
}

function renderCourseFiles(task){
  const host=document.getElementById("course-files-list");
  const badge=document.getElementById("course-files-state");
  const folderLink=document.getElementById("course-files-folder-link");
  if(!host || !task) return;

  const payload=courseFilesCache[task.id];
  if(!payload){
    if(courseFilesLoadingTask===task.id){
      host.innerHTML='<div class="empty">正在讀取 Google Drive 檔案…</div>';
      if(badge){
        badge.textContent="讀取中";
        badge.className="badge";
      }
    }else{
      host.innerHTML='<div class="empty">尚未載入這堂課的檔案。</div>';
      if(badge){
        badge.textContent="尚未載入";
        badge.className="badge";
      }
    }
    if(folderLink) folderLink.hidden=true;
    return;
  }

  const groups=Array.isArray(payload.groups) ? payload.groups : [];
  const total=Number(payload.total_files||0);
  if(badge){
    badge.textContent=total+" 個檔案";
    badge.className="badge complete";
  }
  if(folderLink){
    folderLink.hidden=!payload.lesson_folder_url;
    folderLink.href=payload.lesson_folder_url || "#";
  }

  host.innerHTML=groups.map(group=>{
    const files=Array.isArray(group.files) ? group.files : [];
    const rows=files.length ? files.map(file=>{
      const updated=file.updated_at ? new Date(file.updated_at).toLocaleString() : "";
      const size=formatCaptureFileSize(file.size);
      const url=String(file.url||"");
      const timingNote=file.needs_timing_review ? "尚未完成影片對時" : "";
      return '<div class="course-file-row">'+
        '<div class="course-file-main">'+
          '<b>'+escapeHtml(file.display_name||file.name||"未命名檔案")+'</b>'+
          '<span>'+escapeHtml([size,updated,timingNote].filter(Boolean).join("・"))+'</span>'+
        '</div>'+
        '<div class="course-file-actions">'+
          '<a href="'+escapeHtml(url||"#")+'" target="_blank" rel="noopener">開啟</a>'+
          '<button class="mini ghost" type="button" data-course-file-copy="'+escapeHtml(url)+'">複製連結</button>'+
        '</div>'+
      '</div>';
    }).join("") : '<div class="course-file-empty">目前沒有檔案</div>';

    return '<section class="course-file-group">'+
      '<div class="course-file-group-head">'+
        '<div><b>'+escapeHtml(group.label||group.key||"檔案")+'</b><span>'+files.length+' 個</span></div>'+
        (group.folder_url
          ? '<a href="'+escapeHtml(group.folder_url)+'" target="_blank" rel="noopener">開啟資料夾</a>'
          : '')+
      '</div>'+
      rows+
    '</section>';
  }).join("");

  host.querySelectorAll("[data-course-file-copy]").forEach(button=>{
    button.addEventListener("click",()=>{
      const url=String(button.dataset.courseFileCopy||"");
      if(!url) return;
      const done=()=>{
        const old=button.textContent;
        button.textContent="已複製";
        window.setTimeout(()=>{ button.textContent=old; },1200);
      };
      if(navigator.clipboard && window.isSecureContext){
        navigator.clipboard.writeText(url).then(done).catch(()=>{
          window.prompt("請複製檔案連結：",url);
        });
      }else{
        window.prompt("請複製檔案連結：",url);
      }
    });
  });
}

function setTtsShareCollapsed(collapsed){
  const panel=document.getElementById("tts-share-panel");
  const body=document.getElementById("tts-share-content");
  const toggle=document.getElementById("tts-share-toggle");
  panel?.classList.toggle("collapsed",!!collapsed);
  if(body) body.hidden=!!collapsed;
  if(toggle){
    toggle.textContent=collapsed?"展開分享訊息":"收合分享訊息";
    toggle.setAttribute("aria-expanded",collapsed?"false":"true");
  }
}
function renderTtsShare(task){
  const panel=document.getElementById("tts-share-panel");
  const textarea=document.getElementById("tts-share-text");
  const button=document.getElementById("tts-share-copy");
  const badge=document.getElementById("tts-share-count");
  const note=document.getElementById("tts-share-note");
  const state=document.getElementById("tts-share-copy-state");
  if(!panel || !textarea || !button || !task || !window.SoulKeyTTSShare) return;

  const result=window.SoulKeyTTSShare.build(
    task,ttsShareLinksCache[task.id] || courseFilesCache[task.id]
  );
  panel.hidden=!result.eligible;
  if(!result.eligible) return;
  const toggle=document.getElementById("tts-share-toggle");
  if(toggle) toggle.onclick=()=>setTtsShareCollapsed(!document.getElementById("tts-share-content")?.hidden);
  if(panel.dataset.taskId!==String(task.id)){
    panel.dataset.taskId=String(task.id);
    setTtsShareCollapsed(true);
  }

  const changedLesson=textarea.dataset.taskId!==String(task.id);
  // Preserve edits when the same lesson receives a new Drive snapshot.
  const previous=String(textarea.dataset.generatedMessage||"");
  if(changedLesson || !previous || textarea.value===previous){
    textarea.value=result.message;
  }
  textarea.dataset.taskId=String(task.id);
  textarea.dataset.generatedMessage=result.message;
  if(badge){
    const formalCount=Math.max(0,result.readyCount-(result.reviewCount||0));
    badge.textContent=result.expectedCount
      ? formalCount+" / "+result.expectedCount+" 正式音檔"+
        (result.reviewCount?"・"+result.reviewCount+" 個試聽待驗收":"")
      : "正在核對正式音檔";
    badge.className="badge"+(result.allReady?" complete":"");
  }
  if(note){
    note.textContent=result.allReady
      ? "所有已勾選的 TTS 語言都有 Google Drive 正式 MP3 連結。可直接複製分享。"
      : result.readyCount
        ? "已取得 "+Math.max(0,result.readyCount-(result.reviewCount||0))+" 個正式音檔連結；"+
          (result.reviewCount?result.reviewCount+" 個試聽版仍待驗收；":"")+
          "其餘語言以「待確認／待驗收」標示。分享前請確認未驗收項目。"
        : "TTS 階段已更新，但尚未取得正式 MP3 連結。按「更新音檔連結」重新核對 Drive。";
  }
  if(note && result.reviewCount && !result.allReady){
    note.textContent="已取得 "+result.readyCount+" 個可分享音檔連結，其中 "+
      result.reviewCount+" 個（尚未與原影片時長同步）。";
  }
  if(note && ttsShareLinkErrors[task.id]){
    note.textContent="音檔查詢未完成："+ttsShareLinkErrors[task.id]+
      "。請按「更新音檔連結」重新查詢；既有已驗證連結仍可使用。";
  } else if(note && ttsShareLoadingTask===task.id) {
    note.textContent="正在核對六種語言的正式音檔（最多等待20秒）…";
  }
  button.disabled=!result.hasLinks;
  button.onclick=()=>{
    const text=textarea.value;
    if(!result.hasLinks || !text.trim()) return;
    const mark=message=>{if(state) state.textContent=message;};
    if(navigator.clipboard && window.isSecureContext){
      navigator.clipboard.writeText(text).then(()=>mark("整則音檔訊息已複製，可貼到 LINE／WhatsApp。"))
        .catch(()=>{window.prompt("請複製整則課程音檔訊息：",text);mark("請在彈出的視窗複製訊息。");});
    }else{
      window.prompt("請複製整則課程音檔訊息：",text);
      mark("請在彈出的視窗複製訊息。");
    }
  };
  const refresh=document.getElementById("tts-share-refresh");
  if(refresh) refresh.onclick=()=>{
    if(state) state.textContent="正在從 Google Drive 核對音檔連結…";
    requestTtsShareLinks(task.id,true);
  };
  if(changedLesson && state) state.textContent="";
}

function ttsShareLinksFailed(taskId,reason) {
  const id=String(taskId||"");
  if(!id || ttsShareLoadingTask!==id) return;
  ttsShareLoadingTask="";
  ttsShareLinkErrors[id]=String(reason||"讀取逾時");
  const task=tasks.find(x=>String(x.id)===id);
  if(task && currentView==="task-detail" && selectedTaskId===id) {
    renderTtsShare(task);
  }
}
function requestTtsShareLinks(taskId,force=false){
  const id=String(taskId||"").trim();
  if(!id) return false;
  if(!force && ttsShareLinksCache[id] &&
    Date.now() - Number(ttsShareLinksFetchedAt[id]||0)<60000) return true;
  if(ttsShareLoadingTask===id && !force) return true;
  ttsShareLoadingTask=id;
  delete ttsShareLinkErrors[id];
  const task=tasks.find(x=>String(x.id)===id);
  if(task && currentView==="task-detail") renderTtsShare(task);
  const sent=jsonpBridgeRequest({action:"tts_share_links",task_id:id});
  if(!sent) ttsShareLinksFailed(id,"控制中心未連線");
  return sent;
}
function courseFilesLoadFailed(taskId,reason){
  const id=String(taskId||"").trim();
  if(!id || courseFilesLoadingTask!==id) return;
  courseFilesLoadingTask="";
  const task=tasks.find(x=>String(x.id)===id);
  if(!task || currentView!=="task-detail" || String(selectedTaskId)!==id) return;
  const badge=document.getElementById("course-files-state");
  if(badge){badge.textContent="讀取失敗・可重試";badge.className="badge";}
  const note=document.getElementById("tts-share-note");
  if(note){
    note.textContent=(courseFilesCache[id]
      ? "Drive 更新失敗，保留上次查到的正式音檔；"
      : "未能取得 Google Drive 的正式音檔清單；")+
      "請按「更新音檔連結」重試。原因："+String(reason||"連線逾時");
  }
  const state=document.getElementById("tts-share-copy-state");
  if(state) state.textContent="查詢失敗，並非音檔已消失；可稍後重試。";
  const languageStatus=document.getElementById("language-plan-status");
  if(languageStatus) languageStatus.textContent="成果查詢失敗；原有勾選與已取得的連結均保留，可稍後重試。";
}
function requestCourseFiles(taskId,force=false){
  const id=String(taskId||"").trim();
  if(!id) return false;

  const age=Date.now()-Number(courseFilesFetchedAt[id]||0);
  if(!force && courseFilesCache[id] && age<30000){
    const task=tasks.find(x=>String(x.id)===id);
    if(task){renderCourseFiles(task);refreshLanguageDeliveryStatus(task);}
    return true;
  }
  if(courseFilesLoadingTask===id && !force) return true;

  courseFilesLoadingTask=id;
  const task=tasks.find(x=>String(x.id)===id);
  if(task) renderCourseFiles(task);

  const fields={action:"course_files",task_id:id};
  // A successful postMessage only proves the iframe received a request;
  // JSONP gives us a bounded response deadline and explicit error callback.
  const sent=jsonpBridgeRequest(fields);
  if(!sent){
    courseFilesLoadFailed(id,"控制中心未連線");
    const badge=document.getElementById("course-files-state");
    if(badge){
      badge.textContent="尚未連線控制中心";
      badge.className="badge";
    }
  }
  return sent;
}

function renderTaskDetail(task){
  normalizeTask(task);
  // Prefetch as soon as the task detail appears, before the user taps either
  // review editor. Concurrent source reads do not use GPU or Google Drive.
  prefetchReviewPayloads(task.id);
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
    const stageFailure=remoteErrorReason(remote);
    const reviewStage=["zh","en-review"].includes(stage.key);
    return '<button class="detail-stage '+state+'" data-detail-stage="'+i+'" '+(state==="locked"?"disabled":"")+'>'+
      '<span class="detail-stage-number">'+String(i+1).padStart(2,"0")+'</span>'+
      '<div><b>'+escapeHtml(stage.label)+'</b><small>'+label+'・'+escapeHtml(stage.hint)+
      (stageFailure ? '｜失敗原因：'+escapeHtml(stageFailure) : '')+'</small></div>'+
      (reviewStage?'<em>'+(stage.key==="en-review"?"英文定稿":"中文定稿")+'</em>':'')+
    '</button>';
  }).join("")+
    '<button class="detail-stage file-overview" type="button" data-course-files-jump>'+
      '<span class="detail-stage-number">05</span>'+
      '<div><b>檔案總覽</b><small>查看這堂課目前已產生的 Drive 檔案與固定連結</small></div>'+
      '<em>檔案</em>'+
    '</button>'+
    '<button class="detail-stage" type="button" data-source-reverify>'+
      '<span class="detail-stage-number">↻</span>'+
      '<div><b>驗證更換影片</b><small>重新上傳同一堂課時，比對音訊內容；相同則沿用原 ASR，不同才重跑</small></div>'+
      '<em>驗證</em>'+
    '</button>';

  renderCourseFiles(task);
  renderTtsShare(task);
  const deliveryRefresh=document.getElementById("language-delivery-refresh");
  if(deliveryRefresh) deliveryRefresh.onclick=()=>{
    const status=document.getElementById("language-plan-status");
    if(status) status.textContent="正在更新文稿與音檔清單，原語言勾選維持不變…";
    requestCourseFiles(task.id,true);
    requestTtsShareLinks(task.id,true);
  };
  setCourseFilesCollapsed(courseFilesCollapsed(),false);

  const filesRefresh=document.getElementById("course-files-refresh");
  if(filesRefresh) filesRefresh.onclick=()=>requestCourseFiles(task.id,true);

  const filesToggle=document.getElementById("course-files-toggle");
  if(filesToggle){
    filesToggle.onclick=()=>{
      const nextCollapsed=!courseFilesCollapsed();
      setCourseFilesCollapsed(nextCollapsed,true);
      if(!nextCollapsed && !courseFilesCache[task.id]){
        requestCourseFiles(task.id);
      }
    };
  }

  const current=next || workflow[workflow.length-1];
  const currentRemote = next ? remoteStageStatus(task,next.key) : null;
  const currentFailure = remoteErrorReason(currentRemote);
  const zhRemote = next && next.key==="zh" ? remoteStageStatus(task,"zh") : null;
  const isChineseReview = next && next.key==="zh" && zhRemote && zhRemote.status==="needs_review";
  const isEnglishReview = next && next.key==="en-review";
  document.getElementById("detail-current-title").textContent=
    next ? next.label : "全部流程完成";

  if(!next){
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message success"><b>這堂課已全部完成</b><span>所有流程均已完成。</span></div>';
  }else if(currentFailure){
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message error">'+
        '<div><b>這一步執行失敗</b><span><strong>失敗原因：</strong>'+escapeHtml(currentFailure)+'</span></div>'+
      '</div>';
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
  nextBtn.disabled=!next || cloudStageUnavailable(next) || pendingRunStageRequest?.taskId===task.id || !!(nextRemote && ["queued","running","delayed"].includes(nextRemote.status));
  const humanReviewNext=next && next.key==="en-review";
  const zhNeedsReview=next && next.key==="zh" && nextRemote && nextRemote.status==="needs_review";
  nextBtn.textContent=next
    ? (cloudStageUnavailable(next) ? "此步驟尚未接回" : zhNeedsReview ? "進入：人工中文定稿" : humanReviewNext ? "進入："+next.label : nextRemote && nextRemote.status==="delayed" ? "已派送，待確認" : "執行下一步："+next.label)
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

  document.querySelector("[data-course-files-jump]")?.addEventListener("click",()=>{
    setCourseFilesCollapsed(false,true);
    if(!courseFilesCache[task.id]) requestCourseFiles(task.id);
    document.getElementById("course-files-panel")?.scrollIntoView({
      behavior:"smooth",
      block:"start"
    });
  });
  document.querySelector("[data-source-reverify]")?.addEventListener("click",()=>{
    verifyReuploadedCourse(task.id);
  });
}

function verifyReuploadedCourse(taskId){
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;
  if(!confirmedRemoteTaskIds.has(taskId)){
    alert("課程尚未由中央控制表確認，無法驗證來源。");
    return;
  }
  const remote=remoteStageStatus(task,"zh");
  if(remote && ["queued","running"].includes(remote.status)){
    alert("這堂課已有中文工作進行中，請勿重複執行。");
    return;
  }
  if(!confirm(
    task.id+"｜"+task.lesson+"\\n\\n"+
    "確定要驗證目前的 YouTube 影片與既有中文逐字稿是否相同？\\n\\n"+
    "內容、時間軸相同：沿用原 ASR，不重新辨識。\\n"+
    "內容不同或無法比對：會重新執行 ASR。\\n\\n"+
    "原有人工定稿檔案不會刪除，但來源變動後可能需要重新確認。"
  )) return;

  const sent=submitBridgePost({
    action:"run_stage",
    task_id:task.id,
    stage:"zh",
    lang:"",
    langs:""
  });
  if(!sent){
    alert("來源驗證未送出，請檢查控制中心連線。");
    return;
  }
  task.completedStep=-1;
  task.status="來源版本驗證已送出";
  task.remoteStages=task.remoteStages||{};
  task.remoteStages.zh={status:"queued",message:"比較 YouTube 來源與現有 ASR"};
  save(STORE.tasks,tasks);
  renderTasks();
  renderTaskDetail(task);
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
  if(bridgeIsCloudRecovery){
    // Cloud Run cannot yet reconcile an actual server-side rollback. Do not
    // fabricate a locally completed rollback that contradicts central Sheet.
    alert("目前 Cloud Run 尚未恢復正式退回功能，因此沒有更改任何課程進度。\n\n需要修改稿件時，請使用人工中文或英文定稿；資料會保留在原課程。");
    return;
  }

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
  // Audio sharing has its own targeted six-language lookup.
  // Full file-overview Drive scan is only needed when that panel is open.
  // Do NOT auto-start the huge course_files scan on opening a lesson.
  // The file overview has its own explicit refresh / expand control.
  showView("task-detail");
  requestTtsShareLinks(task.id);
}

let zhVideoFloatFrame=0;

function updateZhReviewVideoFloat(){
  if(zhVideoFloatFrame) return;
  zhVideoFloatFrame=requestAnimationFrame(()=>{
    zhVideoFloatFrame=0;
    const anchor=document.getElementById("zh-review-media-anchor");
    const bar=document.getElementById("zh-review-media-bar");
    if(!anchor || !bar) return;

    const desktop=window.innerWidth>900;
    const active=currentView==="review";
    if(!desktop || !active){
      bar.classList.remove("floating-video");
      anchor.style.height="";
      return;
    }

    const rect=anchor.getBoundingClientRect();
    const shouldFloat=rect.top<76;
    if(shouldFloat){
      if(!bar.classList.contains("floating-video")){
        anchor.style.height=bar.offsetHeight+"px";
        bar.classList.add("floating-video");
      }
    }else{
      bar.classList.remove("floating-video");
      anchor.style.height="";
    }
  });
}

window.addEventListener("scroll",updateZhReviewVideoFloat,{passive:true});
window.addEventListener("resize",updateZhReviewVideoFloat);

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
  window.setTimeout(updateZhReviewVideoFloat,0);
  loadZhReviewFromGithub(task.id);
  // Metadata-only check: never wait for Drive before rendering GitHub.
  if(bridgeAuthenticated){
    jsonpBridgeRequest({action:"review_cache_status",task_id:task.id});
  }
}

function confirmNextStage(taskId){
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;
  if(!confirmedRemoteTaskIds.has(taskId)){
    alert("此課程尚未在 Google Sheets 中央控制表確認建立。\n\n請重新連線控制中心，並從「建立任務」重新送出課程網址，確認同步後再執行 Kaggle。");
    requestTasksFromControlCenter();
    return;
  }
  normalizeTask(task);
  const next=nextStageFor(task);
  if(!next) return;

  const currentRemote=remoteStageStatus(task,next.key);
  if(next.key==="zh" && currentRemote && currentRemote.status==="needs_review") return openTaskReview(task.id);

  // Cookies are an optional fallback only. Production source acquisition
  // now tries bgutil guest PO tokens / anonymous clients first, so missing
  // YOUTUBE_COOKIES_B64 must never block a normal Chinese-stage launch.
  if(next.key==="en-review") return openEnglishReview(task.id);
  if(cloudStageUnavailable(next)){
    alert("新 Cloud Run 尚未恢復「"+next.label+"」的正式派送，沒有建立工作；既有稿件不受影響。");
    return;
  }
  if(currentRemote && ["queued","running","delayed"].includes(currentRemote.status)){
    alert("此課程已派送或尚未回報；請先核對中央佇列與 GitHub Actions，不要重複派送。");
    requestTaskStatuses();
    return;
  }

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
    (bridgeIsCloudRecovery
      ? "確認後僅寫入中央翻譯佇列，由 GitHub Actions 排程領取；成果回讀驗證後才算完成。"
      : "確認後會送到 GitHub Actions，再啟動 Kaggle Web Worker。完成前下一步會保持鎖定。")
  );
  if(!ok) return;

  const dispatchStage=next.key==="zh" ? "zh" : next.key;
  pendingRunStageRequest={taskId:task.id,stage:dispatchStage};
  const sent=submitBridgePost({
    action:"run_stage",
    task_id:task.id,
    stage:dispatchStage,
    lang:"",
    langs
  });

  if(!sent){
    pendingRunStageRequest=null;
    alert("控制中心尚未接受這項派工；沒有建立 Kaggle 工作。");
    return;
  }

  // HTTP request sent is not the same as a GitHub/Kaggle queue receipt.
  // Wait for the explicit run_stage ACK before marking the lesson queued.
  task.status="正在核對派工回覆："+next.label;
  save(STORE.tasks,tasks);
  renderTasks();
  if(currentView==="task-detail" && selectedTaskId===task.id)
    renderTaskDetail(task);
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

document.getElementById("period").addEventListener("input",updateTaskCodes);

document.getElementById("task-form").addEventListener("submit",async e=>{
  e.preventDefault();
  if(!bridgeAuthenticated || bridgeProtocolVersion<REQUIRED_BRIDGE_PROTOCOL){
    alert("請先在總覽連線控制中心並完成驗證。未連線不能新增、修改或暫存課程。");
    showView("dashboard");
    return;
  }

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

  const sentToCloud=submitBridgePost({
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

  if(!sentToCloud){
    alert("中央儲存尚未確認，請保留原始網址後重新連線確認；未送出本機修改。");
    return;
  }
  created.forEach(t=>t.status="本機草稿：等待 Google Sheets 確認");
  save(STORE.tasks,tasks);
  renderTasks();

  // 只清除本次填寫內容，保留期數，方便同一期分批補課程。
  for(const entry of entries){
    document.getElementById("youtube-url-"+entry.lessonNo).value="";
  }
  document.getElementById("task-note").value="";
  document.getElementById("period").value=period;
  updateTaskCodes();

  alert("第 "+period+" 期課程已送出雲端同步。\n\n尚未確認建立成功；請等待中央控制表回覆，確認前不能執行 Kaggle。");
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

document.getElementById("create-en-review-share")?.addEventListener("click",()=>{
  if(!selectedTaskId){
    alert("請先選擇一堂課。");
    return;
  }

  const task=tasks.find(x=>x.id===selectedTaskId);
  if(!task) return;

  const shareUrl=quickReviewUrl(task,"en");
  const state=document.getElementById("en-review-share-state");
  const copied=()=>{
    if(state) state.textContent="已複製英文定稿固定連結";
  };

  if(navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(shareUrl).then(copied).catch(()=>{
      window.prompt("請複製這堂課的英文定稿連結：",shareUrl);
    });
  }else{
    window.prompt("請複製這堂課的英文定稿連結：",shareUrl);
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
    "系統會先存到本堂中央 Google Sheet 並回讀驗證，Drive 另行同步。"
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

  // Never navigate away or claim a saved Chinese Final until the server
  // returns a confirmed, read-back-verified Sheet revision.
  zhFinalPendingTaskId=task.id;
  setZhFinalizeEnabled(false);
  setZhReviewLoadState("正在驗證本堂中文中央定稿寫入…","working");
  const sent=submitBridgePost({
    action:"review_save",
    task_id:task.id,
    kind:"zh",
    segments_json:JSON.stringify(segments),
    terms_json:"[]",
    source_video_id:youtubeVideoIdFromUrl(task.url)
  });
  if(!sent){
    zhFinalPendingTaskId="";
    setZhFinalizeEnabled(true);
    setZhReviewLoadState("中文定稿尚未送出；目前修改保留於畫面","error");
  }
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

function englishReviewItemsFromGithub(payload,fromEnglishCache=false){
  // An en.json is a persisted passage layout (AI Final or human draft),
  // whereas zh.json is a sentence-level fallback that may need grouping.
  const prealigned=fromEnglishCache ||
    payload?.alignment_method==="english_sentence_chinese_time_v1";
  const segments=repairReviewTimings(
    Array.isArray(payload?.segments) ? payload.segments : []
  );

  return segments.map((item,i)=>{
    const zhText=String(item.text||"").trim();
    const sourceEn=String(item.source_en||"").trim();
    const editableEn=String(item.en_text===undefined||item.en_text===null ? sourceEn : item.en_text).trim();
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
      pre_aligned:prealigned,
      ids:Array.isArray(item.zh_ids) ? item.zh_ids.map(Number) : [Number(item.id??i)],
      en_confirmed:item.en_confirmed===true,
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

function markVerifiedEnglishStage(taskId,source="sheet"){
  const task=tasks.find(x=>x.id===taskId);
  if(!task)return;
  task.remoteStages=task.remoteStages||{};
  task.remoteStages["en-review"]={
    task_id:taskId,stage:"en-review",status:"done",progress:"100",
    message:source==="sheet"
      ?"Google Sheet 中央英文定稿已回讀驗證；Drive 待同步"
      :"Google Drive 英文定稿已回讀驗證",
    finished_at:new Date().toISOString(),updated_at:new Date().toISOString()
  };
  task.en="完成";
  if(remoteStageStatus(task,"zh")?.status==="done"||task.completedStep>=0)
    task.completedStep=Math.max(task.completedStep,1);
  save(STORE.tasks,tasks);
  renderTasks();
}
function syncEnglishFinalizeButton(task){
  const button=document.getElementById("finalize-en");
  if(!button || !task) return;
  const sheetFinal=englishSheetFinalizedThisSession.has(task.id);
  const finalized=sheetFinal || englishFinalizedThisSession.has(task.id) ||
    remoteStageStatus(task,"en-review")?.status==="done";
  const pending=englishFinalizePendingTaskId===task.id;
  button.dataset.finalized=finalized?"1":"0";
  button.disabled=pending || (!finalized && englishCanonicalLoadedTaskId!==task.id);
  const backup=(()=>{try{return JSON.parse(localStorage.getItem(
    ENGLISH_FINAL_PENDING_PREFIX+task.id)||"null");}catch(_){return null;}})();
  button.textContent=pending
    ?"正在儲存…"
    :finalized?"✓ 已定稿・進入下一步 →"
      :backup?.backup_saved?"英文已備存・Drive 待定稿"
      :"英文定稿";
}

function showEnglishDraftRecovery(taskId){
  const button=document.getElementById("en-review-restore-unsaved");
  if(!button) return;
  let backup=null;
  try{backup=JSON.parse(localStorage.getItem(
    ENGLISH_UNCONFIRMED_BACKUP_PREFIX+taskId
  )||"null");}catch(_){}
  const exists=backup?.task_id===taskId &&
    Array.isArray(backup.segments)&&backup.segments.length;
  button.hidden=!exists;
  button.onclick=()=>{
    if(!window.confirm("將本機尚未核實的英文草稿載回畫面，請逐句確認後再儲存。確定恢復？"))return;
    let restored;
    try{restored=JSON.parse(localStorage.getItem(
      ENGLISH_UNCONFIRMED_BACKUP_PREFIX+taskId
    )||"null");}catch(_){}
    if(!restored?.segments?.length)return;
    const existing=new Map(currentEnglishReview.map(x=>[Number(x.id),x]));
    const edits=restored.segments.map(x=>{
      const old=existing.get(Number(x.id));
      return old && String(old.en||"")!==String(x.en_text||"")
        ? {...old,en:String(x.en_text||""),en_confirmed:false} : null;
    }).filter(Boolean);
    const map=new Map(edits.map(x=>[Number(x.id),x]));
    edits.forEach(x=>englishReviewDirtyIds.add(Number(x.id)));
    renderEnglishReview(currentEnglishReview.map(x=>map.get(Number(x.id))||x));
    const state=document.getElementById("en-review-share-state");
    if(state)state.textContent="已取回 "+edits.length+
      " 筆本機草稿差異，尚未寫入雲端；請檢查並逐句確認。";
    button.hidden=true;
  };
}
function requestEnglishCloudOverrides(taskId){
  return jsonpBridgeRequest({
    action:"review_en_draft_status",task_id:taskId,include_edits:"1"
  });
}
// The new Cloud Run CC queue persists source-verified English in Sheet,
// while the legacy review_load(en) still looks for Drive en.json. Restore the
// editor from the existing read-only Bridge endpoints, without re-fetching
// YouTube, generating AI text, or touching any Chinese Final.
let englishCcRecoveryPromise=null;
function readEnglishCcBridge(fields){
  return new Promise((resolve,reject)=>{
    if(!jsonpBridgeRequest(fields,{onResult:resolve,onError:reject}))
      reject(new Error("bridge_not_connected"));
  });
}
async function recoverEnglishCcIntoEditor(taskId){
  if(englishCcRecoveryPromise?.taskId===taskId)
    return englishCcRecoveryPromise.promise;
  const pending=(async()=>{
    const task=tasks.find(t=>t.id===taskId);
    if(!task)throw Error("lesson_not_registered");
    const video=youtubeVideoIdFromUrl(task.url||"");
    if(!video)throw Error("lesson_video_missing");
    const status=document.getElementById("en-review-share-state");
    if(status)status.textContent="正在載入中央已保存的英文 CC 與本堂中文 Final，不重抓 YouTube…";
    const chinese=[];
    for(let chunk=0;chunk<30;chunk++){
      const reply=await readEnglishCcBridge({
        action:"review_load",task_id:taskId,kind:"zh",chunk_index:chunk
      });
      if(!reply?.ok||reply.type!=="review_data"||reply.kind!=="zh"||
         reply.task_id!==taskId||!Array.isArray(reply.segments))
        throw Error("中文 Final 來源驗證失敗");
      chinese.push(...reply.segments);
      if(!reply.has_more)break;
      if(chunk===29)throw Error("中文 Final 分頁數量超出限制");
    }
    if(!chinese.length)throw Error("找不到本堂中文 Final");
    // Prefer the read-only Sheet manifest. On Cloud Run deployments where
    // Drive folder lookup is unavailable, obtain the same task's completed CC
    // job ID from the authenticated status API instead.
    let manifest=null;
    try{manifest=await readEnglishCcBridge({
      action:"youtube_capture_files",task_id:taskId
    });}catch(_){}
    if(manifest?.ok && (manifest.task_id!==taskId||
       manifest.video_id!==video))throw Error("字幕清單的影片身分不符");
    let verified=(manifest?.cc_files||[]).find(file=>
      file.name==="en.transcript.txt" &&
      file.task_id===taskId &&
      file.storage==="google-sheet" &&
      /^[0-9a-f-]{36}$/i.test(String(file.job_id||""))
    );
    if(!verified){
      const state=await readEnglishCcBridge({
        action:"status",task_id:taskId
      });
      const ccStage=state?.tasks?.[taskId]?.stages?.cc;
      if(!state?.ok||ccStage?.status!=="done"||
         !/^[0-9a-f-]{36}$/i.test(String(ccStage?.run_id||"")))
        throw Error("中央 Sheet 尚無可使用的本堂英文 CC");
      verified={job_id:ccStage.run_id};
    }
    const caption=await readEnglishCcBridge({
      action:"youtube_cc_content",task_id:taskId,
      job_id:verified.job_id,language:"en"
    });
    if(!caption?.ok||caption.task_id!==taskId||
       caption.lang!=="en"||!String(caption.content||"").trim())
      throw Error("中央英文 CC 回讀驗證失敗");
    const mapper=window.SoulKeyEnglishCCAlignment?.alignmentRows;
    if(typeof mapper!=="function")throw Error("英文 CC 對照模組未載入");
    const aligned=mapper(chinese,caption.content,{
      video_id:video,job_id:verified.job_id
    });
    if(selectedTaskId!==taskId||currentView!=="en-review" ||
       englishDraftSavePendingId!==null ||
       englishDraftSaveQueuedIds.size || englishReviewDirtyIds.size ||
       currentEnglishReview.length) return;
    englishCanonicalLoadedTaskId=taskId;
    renderEnglishReview(aligned);
    syncEnglishFinalizeButton(task);
    if(status)status.textContent=
      "已載入中央英文 CC 原文，共 "+aligned.length+
      " 個中文對照段落。原 CC 無時間碼，對齊位置為估算；請逐段核對後確認儲存。";
    requestEnglishCloudOverrides(taskId);
  })().catch(error=>{
    if(selectedTaskId!==taskId||currentView!=="en-review"||
       currentEnglishReview.length)return;
    const status=document.getElementById("en-review-share-state");
    if(status)status.textContent=
      "已保存的英文 CC 尚未載入編輯器："+String(error.message||error).slice(0,160);
  });
  englishCcRecoveryPromise={taskId,promise:pending};
  try{await pending;}finally{
    if(englishCcRecoveryPromise?.promise===pending)englishCcRecoveryPromise=null;
  }
}
async function openEnglishReview(taskId){
  if(!bridgeAuthenticated){
    setDashboardBridgeState("請先連線控制中心，才能編輯英文定稿。","error");
    showView("dashboard");
    return;
  }
  if(selectedTaskId!==taskId &&
     (englishDraftSavePendingId!==null||englishReviewDirtyIds.size)){
    alert("這堂課仍有未確認的英文修改，請先完成確認或複製備份再切換課程。");
    return;
  }
  if(selectedTaskId===taskId &&
     (englishReviewDirtyIds.size||englishDraftSavePendingId!==null)){
    // Never discard a same-lesson unsaved edit just to refresh its source.
    showView("en-review");
    return;
  }
  if(selectedTaskId!==taskId)englishReviewDirtyIds.clear();
  // Clear stale rows even when reopening the very same lesson.
  currentEnglishReview=[];
  englishCanonicalLoadedTaskId="";
  selectedTaskId=taskId;
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;

  const shareState=document.getElementById("en-review-share-state");
  if(shareState) shareState.textContent="";
  showEnglishDraftRecovery(taskId);
  requestEnglishCloudOverrides(taskId);
  // Reset the shared action on EVERY lesson switch. A previously finalized
  // lesson must never leave the next lesson with a disabled "已定稿" button.
  syncEnglishFinalizeButton(task);
  if(shareState && document.getElementById("finalize-en")?.dataset.finalized==="1"){
    shareState.textContent="此堂英文已定稿；可按右上角查看後續流程，不會重新覆蓋定稿。";
  }
  const context=document.getElementById("en-review-task-context");
  context.innerHTML=
    '<b>'+escapeHtml(task.id)+'</b>'+
    '<span>第'+escapeHtml(task.period)+'期・'+escapeHtml(task.lesson)+'</span>'+
    '<small>'+escapeHtml(task.url)+'</small>';

  const list=document.getElementById("en-review-list");
  list.innerHTML='<div class="empty">正在核對本堂 Google Drive／中央英文資料，禁止使用其他堂的快取…</div>';
  showView("en-review");

  // Do not display cached English or a local Drive ACK before validating the
  // current lesson's Drive/Sheet source. Previously these previews could
  // display P259-L03 content under the P259-L04 heading after a switch.
  if(!requestReviewData(taskId,"en",0)){
    list.innerHTML='<div class="empty">本堂英文資料驗證失敗，沒有載入或儲存其他堂內容。</div>';
  }
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
    return {...item,__englishCleaned:cleaned};
  });
}

function englishSentenceEnded(text){
  return /[.!?][\"'’”\)\]]*$/.test(String(text||"").trim());
}

function groupEnglishReviewItems(items){
  const sourceRows=(Array.isArray(items)?items:[]).filter(Boolean);
  // Sentence boundaries have already been reconciled against the Chinese
  // Final timeline. Never regroup a verified 1:1 bilingual paragraph cache.
  if(sourceRows.length && sourceRows.every(item=>item.pre_aligned===true)){
    return sourceRows.map(item=>({
      ...item,
      ids:Array.isArray(item.ids)&&item.ids.length ? item.ids : [Number(item.id)]
    }));
  }
  const rows=dedupeEnglishRows(sourceRows,item=>item.en||"");
  const groups=[];
  let current=null;

  const flush=()=>{
    if(!current) return;
    current.en=mergeEnglishTextParts(current.enParts);
    current.source_en=mergeEnglishTextParts(current.sourceParts);
    current.original=current.originalParts.join("");
    delete current.enParts;
    delete current.sourceParts;
    delete current.originalParts;
    groups.push(current);
    current=null;
  };

  rows.forEach((item,index)=>{
    const en=String(item.__englishCleaned||"").replace(/\s+/g," ").trim();
    const start=Number(item.start||0);
    const end=Number(item.end||start);

    if(!current){
      current={
        id:Number(item.id??index),
        ids:[Number(item.id??index)],
        start,
        end,
        time:item.time||"",
        enParts:[en],
        sourceParts:[String(item.source_en||en)],
        originalParts:[String(item.original||"")],
        terms:Array.isArray(item.terms)?item.terms.slice():[],
        en_confirmed:item.en_confirmed===true
      };
    }else{
      current.ids.push(Number(item.id??index));
      current.end=Math.max(current.end,end);
      current.enParts.push(en);
      current.sourceParts.push(String(item.source_en||en));
      current.originalParts.push(String(item.original||""));
      current.en_confirmed=current.en_confirmed && item.en_confirmed===true;
      (item.terms||[]).forEach(term=>{
        const key=String(term.zh||"")+"|||"+String(term.en||"");
        if(!current.terms.some(x=>String(x.zh||"")+"|||"+String(x.en||"")===key)){
          current.terms.push(term);
        }
      });
    }

    const merged=mergeEnglishTextParts(current.enParts);
    const next=rows[index+1];
    const nextGap=next ? Number(next.start||0)-current.end : Infinity;
    const duration=current.end-current.start;
    const shouldBreak=
      englishSentenceEnded(merged) ||
      merged.length>=900 ||
      duration>=60 ||
      nextGap>2.2 ||
      !next;

    if(shouldBreak) flush();
  });

  flush();
  return groups;
}

function englishReviewDraftPayload(){
  const task=tasks.find(x=>x.id===selectedTaskId);
  return {
    version:6,
    task_id:String(selectedTaskId||""),
    alignment_method:"english_sentence_chinese_time_v1",
    source_video_id:youtubeVideoIdFromUrl(task?.url||""),
    english_cc_available:true,
    english_cc_language:"en",
    english_cc_source:"youtube_or_ai_review",
    segments:(currentEnglishReview||[]).map((item,index)=>({
      id:Number(item.id??index),
      start:Number(item.start||0),
      end:Number(item.end||item.start||0),
      time:String(item.time||formatClock(item.start)),
      raw:"",
      text:String(item.original||""),
      confirmed:true,
      source_en:String(item.source_en||item.en||""),
      en_text:String(item.en||""),
      en_confirmed:item.en_confirmed===true,
      pre_aligned:item.pre_aligned===true || Array.isArray(item.ids),
      zh_ids:(Array.isArray(item.ids)&&item.ids.length
        ? item.ids : [Number(item.id??index)]).map(Number)
    }))
  };
}

function markEnglishConfirmResult(id,saved,message=""){
  const row=document.querySelector(
    '#en-review-list .en-review-row[data-en-segment="'+String(id)+'"]'
  );
  const button=row?.querySelector("[data-confirm-en-segment]");
  const item=currentEnglishReview.find(x=>Number(x.id)===Number(id));
  if(!item || !button) return;
  item.en_confirmed=!!saved;
  row.classList.toggle("confirmed",!!saved);
  button.classList.toggle("confirmed",!!saved);
  button.textContent=saved?"✓ 已確認":(message||"重試確認");
  button.disabled=!!saved;
}

function englishSavedPayloadSnapshot(){
  // Used only after a real backend ACK. Never mark unsaved pending edits
  // as durable when a different row is still queued.
  return JSON.parse(JSON.stringify(englishReviewDraftPayload()));
}

function englishDraftQueueCount(){
  return englishDraftSavePendingIds.size+englishDraftSaveQueuedIds.size;
}
function finishEnglishReviewDraftSave(data){
  const currentId=String(selectedTaskId||"");
  if(currentId!==String(data.task_id||"") ||
     englishDraftSavePendingId===null ||
     !englishDraftSaveRequestId ||
     String(data.request_id||"")!==englishDraftSaveRequestId) return;
  const state=document.getElementById("en-review-share-state");
  const pendingIds=[...englishDraftSavePendingIds];
  const submitted=englishDraftSavedSnapshot;
  englishDraftSavePendingId=null;
  englishDraftSavePendingIds=new Set();
  englishDraftSavedSnapshot=null;
  englishDraftSaveRequestId="";
  window.clearTimeout(englishDraftSaveWatchdog);
  if(data.ok){
    const byId=new Map((submitted?.segments||[]).map(x=>[Number(x.id),x]));
    const cloudStore=englishCloudOverridesByTask[currentId] || (englishCloudOverridesByTask[currentId]={});
    pendingIds.forEach(id=>{
      const saved=byId.get(id);
      if(saved){
        // This receipt becomes the base revision for subsequent edits to
        // this very same sentence, preventing false edit_conflict failures.
        cloudStore[String(id)]={en_text:String(saved.en_text||""),
          en_confirmed:true,request_id:String(data.request_id||""),
          updated_at:String(data.saved_at||"")};
      }
      const current=currentEnglishReview.find(x=>Number(x.id)===id);
      const unchanged=!!saved && !!current && current.en_confirmed===true &&
        String(current.en||"")===String(saved.en_text||"");
      markEnglishConfirmResult(id,unchanged,unchanged?"":"確認此句");
      if(unchanged) englishReviewDirtyIds.delete(id);
    });
    if(submitted && Array.isArray(submitted.segments)){
      const ack={...submitted,
        draft_saved_at:String(data.saved_at||new Date().toISOString()),
        github_synced:data.github_synced!==false};
      try{
        // Save the exact server-acknowledged version, not later unsent edits.
        if(!englishReviewDirtyIds.size && !englishDraftSaveQueuedIds.size){
          localStorage.setItem(ENGLISH_DRIVE_ACK_PREFIX+currentId,
            JSON.stringify(ack));
          localStorage.removeItem(ENGLISH_UNCONFIRMED_BACKUP_PREFIX+currentId);
        }
        // This ACK attests the confirmed row(s) only. Unsent rows in a
        // full snapshot must never be advertised as Drive-confirmed.
      }catch(_){}
    }
    if(state) state.textContent="本批 "+pendingIds.length+
      " 筆英文已通過中央 Google Sheet 回讀驗證"+(englishDraftSaveQueuedIds.size
        ?"；繼續儲存後續確認…":"");
  }else{
    pendingIds.forEach(id=>markEnglishConfirmResult(id,false,"重試確認"));
    if(state) state.textContent="本批儲存失敗："+String(data.message||data.error||"未知錯誤")+
      "。英文文字仍保留在本頁，請按「重試確認」。";
  }
  if(englishDraftSaveQueuedIds.size){
    const next=englishDraftSaveQueuedIds.values().next().value;
    window.setTimeout(()=>saveEnglishReviewDraft(next),0);
  }
}
function resumeQueuedEnglishSaves(){
  if(englishDraftSavePendingId!==null || !englishDraftSaveQueuedIds.size ||
     !selectedTaskId || !bridgeAuthenticated || !bridgeKeyValue())return;
  const next=englishDraftSaveQueuedIds.values().next().value;
  const item=currentEnglishReview.find(row=>Number(row.id)===Number(next));
  if(!item)return;
  item.en_confirmed=true;
  window.setTimeout(()=>saveEnglishReviewDraft(next),250);
}
window.addEventListener("online",()=>{
  if(bridgeKeyValue() && !bridgeAuthenticated)requestStatusHealth();
  resumeQueuedEnglishSaves();
});
document.addEventListener("visibilitychange",()=>{
  if(document.visibilityState==="visible")resumeQueuedEnglishSaves();
});
function saveEnglishReviewDraft(confirmedId){
  if(!selectedTaskId || !currentEnglishReview.length) return false;
  const id=Number(confirmedId);
  englishDraftSaveQueuedIds.add(id);
  if(englishDraftSavePendingId!==null){
    const state=document.getElementById("en-review-share-state");
    if(state) state.textContent="前一批儲存中；其餘 "+
      englishDraftSaveQueuedIds.size+" 筆確認已排入佇列…";
    return true;
  }
  const ids=[...englishDraftSaveQueuedIds];
  englishDraftSaveQueuedIds.clear();
  englishDraftSavePendingIds=new Set(ids);
  englishDraftSavePendingId=ids[0];
  const currentId=selectedTaskId;
  const requestId=String(Date.now())+"-"+Math.random().toString(36).slice(2);
  englishDraftSaveRequestId=requestId;
  englishDraftSavedSnapshot=englishSavedPayloadSnapshot();
  englishDraftSavedSnapshot.save_request_id=requestId;
  englishDraftSavedSnapshot.confirmed_segment_ids=ids;
  const state=document.getElementById("en-review-share-state");
  if(state) state.textContent="正在安全儲存 "+ids.length+" 筆英文修改…";
  try{
    localStorage.setItem(ENGLISH_UNCONFIRMED_BACKUP_PREFIX+currentId,
      JSON.stringify(englishDraftSavedSnapshot));
  }catch(_){}
  const selected=new Set(ids.map(Number));
  const compactPayload={
    ...englishDraftSavedSnapshot,
    segments:englishDraftSavedSnapshot.segments
      .filter(x=>selected.has(Number(x.id)))
      .map(x=>({
        ...x,
        base_request_id:String(
          englishCloudOverridesByTask[currentId]?.[String(x.id)]?.request_id||""
        )
      }))
  };
  const endpoint=bridgeEndpointValue();
  const secret=bridgeKeyValue();
  if(!endpoint || !secret || !bridgeAuthenticated){
    // No write was attempted: keep the same confirmation in the local queue.
    ids.forEach(x=>englishDraftSaveQueuedIds.add(x));
    englishDraftSavePendingId=null;
    englishDraftSavePendingIds=new Set();
    englishDraftSaveRequestId="";
    englishDraftSavedSnapshot=null;
    if(state) state.textContent="暫時離線：修改和確認已留在本機；恢復連線後會重新送出。";
    return true;
  }
  const body=new URLSearchParams({
    action:"review_en_draft_save",task_id:currentId,
    bridge_key:secret,payload_json:JSON.stringify(compactPayload)
  });
  const stillPending=()=>selectedTaskId===currentId &&
    englishDraftSaveRequestId===requestId;
  const probe=()=>{
    if(stillPending())jsonpBridgeRequest({
      action:"review_en_draft_status",task_id:currentId,request_id:requestId
    });
  };
  // Direct CORS POST returns a verifiable ACK. Reuse the *same* request ID
  // on retries so an interrupted response can never create a second edit.
  // The receipt polls are only a fallback if the POST ACK is lost.
  const send=async()=>{
    for(let attempt=0;attempt<3;attempt++){
      if(!stillPending())return;
      if(attempt)await new Promise(resolve=>
        window.setTimeout(resolve,attempt===1?1600:4200));
      if(!stillPending())return;
      const controller=new AbortController();
      const cutoff=window.setTimeout(()=>controller.abort(),20000);
      try{
        const response=await fetch(endpoint,{
          method:"POST",mode:"cors",credentials:"omit",
          headers:{"Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"},
          body:body.toString(),redirect:"follow",cache:"no-store",
          signal:controller.signal
        });
        const data=await response.json();
        if(!stillPending())return;
        if(data?.type==="english_review_draft_saved" &&
           String(data.request_id||"")===requestId){
          finishEnglishReviewDraftSave(data);
          return;
        }
        if(response.status===401 || response.status===429){
          finishEnglishReviewDraftSave({
            type:"english_review_draft_saved",task_id:currentId,
            request_id:requestId,ok:false,
            message:response.status===429
              ?"伺服器限制登入嘗試，請稍後再試"
              :"共用 Bridge Key 驗證失敗，請重新連線"
          });
          return;
        }
        if(state)state.textContent="雲端暫時未確認儲存，正自動重試（"+
          (attempt+1)+"/3）；本機草稿安全保留。";
      }catch(error){
        if(!stillPending())return;
        if(state)state.textContent="網路中斷或回應逾時，正自動重試（"+
          (attempt+1)+"/3）；英文修改沒有清除。";
      }finally{window.clearTimeout(cutoff);}
    }
    if(stillPending()){
      if(state)state.textContent="正在核對雲端是否已收到修改；本機草稿已保存，請勿關閉編輯頁。";
      probe();
    }
  };
  send();
  [8000,23000,43000,65000,85000].forEach(delay=>
    window.setTimeout(probe,delay));
  window.clearTimeout(englishDraftSaveWatchdog);
  englishDraftSaveWatchdog=window.setTimeout(()=>{
    if(!stillPending())return;
    const waiting=[...englishDraftSavePendingIds,...englishDraftSaveQueuedIds];
    waiting.forEach(x=>markEnglishConfirmResult(x,false,"重試確認"));
    englishDraftSavePendingId=null;
    englishDraftSavePendingIds=new Set();
    englishDraftSaveQueuedIds.clear();
    englishDraftSaveRequestId="";
    englishDraftSavedSnapshot=null;
    if(state)state.textContent=
      "雲端仍未回覆儲存憑證。所有英文修改已備份在此裝置；請按「重試確認」，不要重新翻譯。";
  },100000);
  return true;
}

function englishReviewDisplayChinese(text){
  // The upstream bilingual display sometimes joins an identical complete
  // paragraph twice. Fold ONLY exact adjacent duplicates in the UI; retain
  // the raw original in the manuscript and all saved payloads.
  const raw=String(text||"");
  const flat=raw.replace(/\s+/g,"").trim();
  if(flat.length>=24 && flat.length%2===0){
    const half=flat.length/2;
    if(flat.slice(0,half)===flat.slice(half))return flat.slice(0,half);
  }
  return raw;
}
function renderEnglishReview(items){
  const groupedItems=groupEnglishReviewItems(items);
  const cloud=englishCloudOverridesByTask[selectedTaskId]||{};
  currentEnglishReview=groupedItems.map(row=>{
    const id=Number(row.id),edit=cloud[String(id)];
    if(!edit||englishReviewDirtyIds.has(id)||
       englishDraftSavePendingIds.has(id)||englishDraftSaveQueuedIds.has(id))
      return row;
    return {...row,en:String(edit.en_text),en_confirmed:edit.en_confirmed===true};
  });
  document.getElementById("en-review-head")?.classList.add("hide-vernacular");
  document.getElementById("en-review-list")?.classList.add("hide-vernacular");
  const list=document.getElementById("en-review-list");
  const termBox=document.getElementById("en-term-learning");
  if(!list || !termBox) return;

  list.innerHTML=currentEnglishReview.map((item,index)=>
    '<article class="en-review-row" data-en-segment="'+item.id+'" data-en-ids="'+escapeHtml(item.ids.join(","))+'" data-start="'+escapeHtml(item.start ?? 0)+'" data-end="'+escapeHtml(item.end ?? 0)+'">'+
      '<div class="en-review-meta">'+
        '<span>句 '+(index+1)+'</span><span>'+escapeHtml(item.time)+'</span>'+
        (item.ids.length>1 ? '<span>合併 '+item.ids.length+' 個原始片段</span>' : '')+
      '</div>'+
      '<div class="en-review-pair">'+
        '<div class="zh-source original-column">'+escapeHtml(englishReviewDisplayChinese(item.original))+'</div>'+
        '<textarea class="en-draft">'+escapeHtml(item.en)+'</textarea>'+
      '</div>'+
      '<div class="segment-actions">'+
        '<button class="mini confirm" data-confirm-en-segment="'+item.id+'" '+(item.en_confirmed?"disabled":"")+'>'+
          (item.en_confirmed?"已確認":"確認此句")+
        '</button>'+
      '</div>'+
    '</article>'
  ).join("");

  const pairs=[];
  groupedItems.forEach(item=>{
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

  document.querySelectorAll("#en-review-list .en-review-row").forEach(row=>{
    const id=Number(row.dataset.enSegment);
    const item=currentEnglishReview.find(x=>Number(x.id)===id);
    const textarea=row.querySelector(".en-draft");
    const btn=row.querySelector("[data-confirm-en-segment]");

    if(item?.en_confirmed) row.classList.add("confirmed");

    // Keep the complete English paragraph visible beside the matching
    // Chinese text; fixed-height textareas hide the alignment while editing.
    const fitEnglishHeight=()=>{
      if(!textarea) return;
      textarea.style.height="auto";
      textarea.style.height=Math.max(112,textarea.scrollHeight+2)+"px";
    };
    fitEnglishHeight();

    textarea?.addEventListener("input",()=>{
      fitEnglishHeight();
      if(!item) return;
      item.en=textarea.value;
      item.en_confirmed=false;
      englishReviewDirtyIds.add(Number(item.id));
      try{
        localStorage.setItem(ENGLISH_UNCONFIRMED_BACKUP_PREFIX+selectedTaskId,
          JSON.stringify(englishReviewDraftPayload()));
      }catch(_){}
      row.classList.remove("confirmed");
      if(btn){
        btn.disabled=false;
        btn.textContent="確認此句";
      }
      const state=document.getElementById("en-review-share-state");
      if(state) state.textContent="有尚未確認的英文修改";
    });

    btn?.addEventListener("click",()=>{
      if(!item) return;
      item.en=String(textarea?.value||item.en||"").trim();
      item.en_confirmed=true;
      row.classList.add("confirmed");
      btn.textContent="儲存中…";
      btn.disabled=true;
      if(!saveEnglishReviewDraft(id)){
        item.en_confirmed=false;
        row.classList.remove("confirmed");
        btn.textContent="確認此句";
        btn.disabled=false;
      }
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
  // A confirmed final is a navigation action, not a second Drive write.
  if(document.getElementById("finalize-en")?.dataset.finalized==="1" ||
     remoteStageStatus(task,"en-review")?.status==="done"){
    if(englishSheetFinalizedThisSession.has(task.id))
      markVerifiedEnglishStage(task.id,"sheet");
    openTaskDetail(task.id);
    requestTaskStatuses();
    return;
  }

  if(englishCanonicalLoadedTaskId!==task.id){
    alert("尚未從中央資料確認本堂英文稿，已阻止跨堂英文定稿。請重新開啟這一堂。");
    return;
  }
  document.querySelectorAll("#en-review-list .en-review-row").forEach(row=>{
    const item=currentEnglishReview.find(
      x=>Number(x.id)===Number(row.dataset.enSegment)
    );
    if(item){
      item.en=String(row.querySelector(".en-draft")?.value||"").trim();
    }
  });

  const segments=(currentEnglishReview||[]).map((item,index)=>({
    id:Number(item.id??index),
    start:Number(item.start||0),
    end:Number(item.end||item.start||0),
    text:String(item.en||"").trim()
  })).filter(x=>x.text);

  if(!segments.length){
    alert("目前沒有可定稿的英文段落。");
    return;
  }

  const ok=confirm(
    task.id+"｜"+task.lesson+"\n\n"+
    "確定英文稿已人工確認完成並定稿？\n"+
    "系統會先驗證中央 Google Sheet 正式定稿；Drive 另行同步。"
  );
  if(!ok) return;

  const button=document.getElementById("finalize-en");
  const state=document.getElementById("en-review-share-state");
  if(button){
    button.disabled=true;
    button.textContent="正在儲存…";
  }
  const fullTerms=[...document.querySelectorAll("[data-term-en-input]")].map(input=>({
    zh:String(input.dataset.termEnInput||"").trim(),
    en:String(input.value||"").trim()
  })).filter(x=>x.zh&&x.en);
  try{
    localStorage.setItem(ENGLISH_FINAL_PENDING_PREFIX+task.id,
      JSON.stringify({task_id:task.id,kind:"en",segments,terms:fullTerms,
        backup_saved:false,queued_at:new Date().toISOString()}));
  }catch(_){}
  if(state) state.textContent=
    "正在提交英文全文。Drive 正式儲存尚未恢復時，系統只會雲端備存，不會假裝定稿完成。";
  englishFinalizePendingTaskId=task.id;
  englishFinalizePriorFinishedAt=String(
    remoteStageStatus(task,"en-review")?.finished_at || ""
  );
  window.clearTimeout(englishFinalizeWatchdog);
  // An Apps Script Drive write can take longer than iframe startup. A status
  // probe is an independent acknowledgement if cross-origin postMessage fails.
  englishFinalizeWatchdog=window.setTimeout(()=>{
    if(englishFinalizePendingTaskId!==task.id) return;
    const pending=document.getElementById("en-review-share-state");
    if(pending) pending.textContent=
      "仍在向 Google Drive 儲存／核對中。請勿再次提交，已保留本頁編輯內容。";
    requestTaskStatuses();
  },35000);
  window.setTimeout(()=>requestTaskStatuses(),8000);

  const sent=submitBridgePost({
    action:"review_save",
    task_id:task.id,
    kind:"en",
    segments_json:JSON.stringify(segments),
    terms_json:JSON.stringify(fullTerms),
    source_video_id:youtubeVideoIdFromUrl(task.url)
  });

  if(!sent){
    englishFinalizePendingTaskId="";
    window.clearTimeout(englishFinalizeWatchdog);
    if(button){
      button.disabled=false;
      button.textContent="英文定稿";
    }
    if(state) state.textContent="儲存失敗：Bridge 尚未連線";
  }
});

function submitBridgePost(fields){
  const endpoint=bridgeEndpointValue();
  const key=bridgeKeyValue();

  if(!endpoint || !key || !bridgeAuthenticated ||
     bridgeProtocolVersion<REQUIRED_BRIDGE_PROTOCOL){
    setDashboardBridgeState("控制中心尚未驗證；已禁止所有儲存與修改。","error");
    return false;
  }

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

  // Google Cloud replacement returns JSON over CORS. The former Apps Script
  // hidden iframe cannot receive that response, so deliver its ACK through the
  // same event dispatcher used by the existing UI.
  if(/^https:\/\/soulkey-bridge-[a-z0-9-]+\.(?:asia-east1\.run\.app|a\.run\.app)/.test(endpoint)){
    fetch(endpoint,{
      method:"POST",
      headers:{"Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"},
      body:new URLSearchParams({...fields,bridge_key:key}),
      mode:"cors",cache:"no-store"
    }).then(async response=>{
      const body=await response.json();
      window.dispatchEvent(new MessageEvent("message",{data:body}));
    }).catch(error=>{
      const message="雲端寫入請求失敗："+String(error?.message||error);
      // A failed final-submit fetch does not revoke the shared Bridge login.
      // The full manuscript was already backed up locally before POST.
      if(fields?.action==="review_save"){
        window.dispatchEvent(new MessageEvent("message",{data:{
          source:"soulkey-bridge",type:"review_saved",ok:false,
          kind:String(fields.kind||""),task_id:String(fields.task_id||""),
          error:"request_failed",message:message+
            "。此裝置仍保留英文全文備份，請確認網路後重試。"
        }}));
        return;
      }
      setDashboardBridgeState(message,"error");
      const details=document.getElementById("dashboard-bridge-message");
      if(details)details.textContent=message;
    });
    return true;
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
  // Previously the response iframe was destroyed after only 10 seconds.
  // Google Drive saves regularly take longer; removing the iframe discarded
  // the success event, leaving the button stuck at "正在儲存".
  const responseWindowMs=fields && fields.action==="review_save" ? 180000 : 120000;
  window.setTimeout(()=>{
    form.remove();
    frame.remove();
  },responseWindowMs);
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

function bridgeSyncRequestFailed(action,reason){
  if(firebaseSnapshotReadOnly)return;
  if(action==="status_health" || action==="tasks_get"){
    const wasAuthenticated=bridgeAuthenticated;
    // A transient background poll failure is not a revoked Bridge Key.
    // Keep the current editor and save permission alive until the server
    // explicitly reports unauthorized. Never discard unsaved English edits.
    if(!wasAuthenticated) bridgeAuthenticated=false;
    const humanReason=String(reason||"無法取得控制中心回應");
    setDashboardBridgeState(
      wasAuthenticated
        ? "網路暫時無法同步："+humanReason+"。編輯內容已暫存在本機，可繼續修改；系統將於恢復連線後重試。"
        : "無法同步控制中心："+humanReason+"。請按「連線控制中心」重試；原本 Google Sheet 資料不會消失。",
      wasAuthenticated?"working":"error"
    );
    const apiState=document.getElementById("api-state");
    if(apiState){
      apiState.textContent="控制中心無法連線";
      apiState.className="warn";
    }
  }
}

function jsonpBridgeRequest(fields,options={}){
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

  const action=String(fields.action||"");
  const timeoutMs=action==="status_health"?20000:
    action==="tasks_get"?45000:
      action==="tts_share_links"?20000:
      action==="course_files"?45000:90000;
  let settled=false;
  let watchdog=0;
  const cleanup=()=>{
    if(settled) return false;
    settled=true;
    if(watchdog) window.clearTimeout(watchdog);
    try{delete window[callbackName];}catch(_){}
    script.remove();
    return true;
  };

  window[callbackName]=(data)=>{
    if(!cleanup()) return;
    if(typeof options.onResult==="function")options.onResult(data);
    else window.dispatchEvent(new MessageEvent("message",{data}));
  };

  const fail=(reason)=>{
    if(!cleanup()) return;
    const isCentralSync=["status_health","tasks_get","status_batch"].includes(action);
    if(isCentralSync){
      const syncState=document.getElementById("status-sync-state");
      const syncText=document.getElementById("status-sync-text");
      if(syncState){
        syncState.textContent="背景同步暫時失敗";
        syncState.className="warn";
      }
      if(syncText){
        syncText.textContent="雲端暫時無法同步："+reason;
      }
    }
    if(typeof options.onError==="function"){
      options.onError(new Error(reason));
      return;
    }
    bridgeSyncRequestFailed(action,reason);
    if(action==="course_files") courseFilesLoadFailed(String(fields.task_id||""),reason);
    if(action==="tts_share_links") ttsShareLinksFailed(String(fields.task_id||""),reason);
  };
  // Six-character shared keys use CORS POST. Avoid putting a short shared
  // passcode in URL query strings, browser history, and request access logs.
  if(key.length===6){
    const controller=new AbortController();
    params.delete("callback");
    params.delete("_t");
    watchdog=window.setTimeout(()=>{
      controller.abort();
      fail("逾時 "+Math.round(timeoutMs/1000)+" 秒，請稍後再試");
    },timeoutMs);
    fetch(endpoint,{
      method:"POST",mode:"cors",cache:"no-store",
      headers:{"Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"},
      body:params.toString(),signal:controller.signal
    }).then(response=>response.json()).then(data=>{
      if(!cleanup())return;
      if(typeof options.onResult==="function")options.onResult(data);
      else window.dispatchEvent(new MessageEvent("message",{data}));
    }).catch(error=>fail("Cloud Run 連線失敗："+String(error?.message||error)));
    return true;
  }
  script.onerror=()=>fail("控制中心可能拒絕存取或暫時無法連線");
  watchdog=window.setTimeout(
    ()=>fail("逾時 "+Math.round(timeoutMs/1000)+" 秒，請檢查控制中心部署權限"),
    timeoutMs
  );

  const sep=endpoint.includes("?") ? "&" : "?";
  script.src=endpoint+sep+params.toString();
  document.head.appendChild(script);
  return true;
}

function completeEnglishFinalizeUi(taskId,confirmationSource){
  if(!taskId || englishFinalizePendingTaskId!==taskId) return;
  englishFinalizePendingTaskId="";
  englishFinalizePriorFinishedAt="";
  if(confirmationSource==="sheet")englishSheetFinalizedThisSession.add(taskId);
  else englishFinalizedThisSession.add(taskId);
  markVerifiedEnglishStage(taskId,confirmationSource);
  window.clearTimeout(englishFinalizeWatchdog);
  const state=document.getElementById("en-review-share-state");
  const task=tasks.find(x=>x.id===taskId);
  if(state) state.textContent=confirmationSource==="sheet"
    ? "英文全文已完成 Google Sheet 中央定稿及回讀驗證；Google Drive 尚待同步。"
    : "英文定稿已寫入 Google Drive"+
      (confirmationSource==="status"?"（中央狀態已確認）":"");
  syncEnglishFinalizeButton(task);
  // Never loop back to the editor after the save acknowledgement.
  if(currentView==="en-review" && selectedTaskId===taskId){
    openTaskDetail(taskId);
    requestTaskStatuses();
  }
}

function applyRemoteStatuses(payload){
  const remoteTasks=payload && payload.tasks ? payload.tasks : {};
  let changed=false;

  let shouldRefreshTtsFiles=false;
  for(const task of tasks){
    const remote=remoteTasks[task.id];
    if(!remote || !remote.stages) continue;
    if(currentView==="task-detail" && selectedTaskId===task.id){
      const prior=task.remoteStages || {};
      const changes=Object.keys(remote.stages).some(key=>
        /^tts(?::[a-z]{2})?$/i.test(key) &&
        ["done","needs_review"].includes(String(remote.stages[key]?.status||"")) &&
        String(prior[key]?.status||"")!==String(remote.stages[key]?.status||"")
      );
      if(changes) shouldRefreshTtsFiles=true;
    }
    task.remoteStages=remote.stages;
    task.remoteUpdatedAt=payload.server_time || new Date().toISOString();
    syncCompletedFromRemote(task);
    changed=true;
  }

  if(englishFinalizePendingTaskId){
    const pendingTask=tasks.find(x=>x.id===englishFinalizePendingTaskId);
    const done=remoteStageStatus(pendingTask,"en-review");
    if(done && done.status==="done" &&
       done.finished_at &&
       String(done.finished_at)!==englishFinalizePriorFinishedAt){
      completeEnglishFinalizeUi(englishFinalizePendingTaskId,"status");
    }
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
  // Polling may finish a language while the detail page is open: refresh
  // Drive links once on transition without re-running TTS or duplicating jobs.
  if(shouldRefreshTtsFiles && selectedTaskId){
    requestCourseFiles(selectedTaskId,true);
  }

  if(currentView==="en-review" && selectedTaskId){
    syncEnglishFinalizeButton(tasks.find(x=>x.id===selectedTaskId));
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
  if(!bridgeAuthenticated) return false;
  const key=bridgeKeyValue();
  const endpoint=bridgeEndpointValue();
  if(!key || !endpoint || !tasks.length) return false;

  // The Bridge accepts at most 20 task IDs per status_batch. Do not drop
  // P258+ lessons when earlier periods already occupy the first 20 rows.
  // Send the currently selected period first so the visible cards refresh
  // promptly; then refresh every remaining task in bounded batches.
  const selected=tasksForSelectedPeriod();
  const prioritized=[...selected,...tasks.filter(t=>!selected.includes(t))];
  // Reviewing a manuscript does not require polling every lesson in
  // the school. Do not compete with ongoing sentence saves.
  const ids=currentView==="en-review" && selectedTaskId
    ? [String(selectedTaskId)]
    : [...new Set(prioritized.map(t=>String(t.id||"").trim()).filter(Boolean))];
  let sent=false;
  for(let i=0;i<ids.length;i+=20){
    const ok=jsonpBridgeRequest({
      action:"status_batch",
      task_ids:ids.slice(i,i+20).join(",")
    });
    sent=ok || sent;
  }
  return sent;
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
  if(firebaseSnapshotReadOnly)return; // stale Apps Script events must never erase verified fallback tasks

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
    if(data.error==="unauthorized"){
      bridgeAuthenticated=false;
      confirmedRemoteTaskIds.clear();
      tasks=[];
      renderTasks();
    }
    const reason=data.message || data.error || "未知錯誤";
    if(courseFilesLoadingTask) courseFilesLoadFailed(courseFilesLoadingTask,reason);
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
    const bridgeErrorText=data.error==="unauthorized"
      ? "Bridge Key 驗證失敗。若使用原本 Apps Script 六碼，請確認管理者已在授權電腦執行一次「SoulKey-啟用共用6碼登入.cmd」，再核對輸入。"
      : data.error==="rate_limited"
        ? "登入嘗試太多，請在一小時後再試，或請管理者檢查金鑰。"
      : "Bridge 錯誤："+reason;
    // An unimplemented feature is not a lost login. Keep the English
    // editor active when some unrelated Cloud Run action returns 409.
    const revoked=["unauthorized","rate_limited"].includes(String(data.error||""));
    if(revoked) setDashboardBridgeState(bridgeErrorText,"error");
    // A 409 from an unavailable function is unrelated to authentication.
    // Leave global connection state untouched and report only locally.
    // Optional, currently unsupported Cloud Run functions must not
    // turn a healthy connection indicator red.
    if(revoked){
      const syncState=document.getElementById("status-sync-state");
      const syncText=document.getElementById("status-sync-text");
      if(syncState){
        syncState.textContent="驗證失敗";
        syncState.className="warn";
      }
      if(syncText) syncText.textContent=bridgeErrorText;
    }
  }

  if(data.type==="tasks_saved"){
    if(data.ok){
      const saved=Array.isArray(data.tasks) ? data.tasks : [];
      saved.forEach(item=>confirmedRemoteTaskIds.add(String(item.id||"")));
      requestTasksFromControlCenter();
      if(saved.length) alert("Google Sheets 中央控制表已確認建立 "+saved.length+" 堂課。其他裝置同步後即可看到。");
    }else{
      alert("中央控制表儲存失敗，課程目前只存在本機："+String(data.message||data.error||"未知錯誤")+"\n\n請保留 YouTube 網址並重試，勿啟動 Kaggle。");
      renderTasks();
    }
  }

  if(data.type==="tasks_result"){
    const apiState=document.getElementById("api-state");
    if(data.ok){
      if(apiState){
        apiState.textContent="任務已同步";
        apiState.className="ok";
      }
      bridgeAuthenticated=true; // first verified central snapshot
      mergeRemoteTasks(data.tasks||[]);
      resumeQueuedEnglishSaves();
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
      bridgeSyncRequestFailed("tasks_get",String(data.message||data.error||"任務讀取失敗"));
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
    if(data.kind==="en" &&
       (String(data.task_id||"")!==String(selectedTaskId||"") ||
        currentView!=="en-review"))return;
    const browserElapsed=reviewElapsedMs(data.task_id,data.kind,chunkIndex);
    if(!data.ok){
      if(data.kind==="zh"){
        zhReviewLoading=false;
        setZhRefreshButtonState(false);
        setZhFinalizeEnabled(false);
        const isMissing=String(data.error||"")==="review_files_missing";
        const reason=String(data.message || data.error || "未知錯誤");
        setZhReviewLoadState(
          isMissing ? "尚未產生中文逐字稿／AI 校稿" : "雲端讀取失敗",
          "error"
        );
        const editor=document.getElementById("segment-list");
        if(editor){
          editor.innerHTML='<div class="empty">'+
            (isMissing
              ? "此課程尚未有可供人工定稿的中文逐字稿與校稿報告。請回到任務總覽執行「中文定稿」，等待 Kaggle 真正產生檔案後再開啟。"
              : "人工定稿雲端讀取失敗："+escapeHtml(reason))+
            '</div>';
        }
        if(!isMissing) alert("讀取人工校正資料失敗："+reason);
      }else if(data.kind==="en"){
        englishCanonicalLoadedTaskId="";
        syncEnglishFinalizeButton(tasks.find(x=>x.id===data.task_id));
        // A missing *base* JSON must never hide already-loaded manuscripts:
        // Drive's independent human-edits store works without en.json.
        if(Array.isArray(currentEnglishReview) && currentEnglishReview.length &&
           String(data.task_id||"")===String(selectedTaskId||"")){
          const state=document.getElementById("en-review-share-state");
          if(state)state.textContent="已載入現有中英稿；Drive 尚未有整堂 JSON，逐句修改仍可獨立儲存";
          requestEnglishCloudOverrides(data.task_id);
        }else{
          const msg=String(data.message||data.error||"未知錯誤");
          if(/尚未產生英文稿|尚未有.*English CC/.test(msg)){
            const list=document.getElementById("en-review-list");
            if(list)list.innerHTML='<div class="empty">正在從中央 Google Sheet 讀取已抓取的英文 CC，準備中英對照草稿…</div>';
            recoverEnglishCcIntoEditor(data.task_id);
          }else{
            showNoEnglishCcFallback(data.task_id || selectedTaskId);
            const status=document.getElementById("en-fallback-status");
            if(status)status.textContent="英文資料讀取失敗："+msg;
          }
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
      if(String(data.task_id||"")!==String(selectedTaskId||"")) return;
      // A late Drive response must not discard the user's in-flight edit.
      if(englishDraftSavePendingId!==null ||
         englishDraftSaveQueuedIds.size>0) return;
      // Bridge's current Drive English draft wins over an old GitHub cache.
      // review_load returns {original,en,ids,...}, unlike GitHub en.json.
      if(data.sheet_finalized){
        englishSheetFinalizedThisSession.add(String(data.task_id));
        markVerifiedEnglishStage(String(data.task_id),"sheet");
        syncEnglishFinalizeButton(tasks.find(x=>x.id===data.task_id));
      }
      const loaded=Array.isArray(data.segments)?data.segments:[];
      englishCanonicalLoadedTaskId=loaded.length?String(data.task_id||""):"";
      syncEnglishFinalizeButton(tasks.find(x=>x.id===data.task_id));
      const dirty=new Map(currentEnglishReview
        .filter(row=>englishReviewDirtyIds.has(Number(row.id)))
        .map(row=>[Number(row.id),row]));
      renderEnglishReview(loaded.map(row=>{
        const edited=dirty.get(Number(row.id));
        return edited
          ? {...row,en:edited.en,en_confirmed:edited.en_confirmed}
          : row;
      }));
      if(data.source==="en.review.draft.json" ||
         data.source==="en.final.json"){
        try{
          if(!englishReviewDirtyIds.size)
            localStorage.removeItem(ENGLISH_DRIVE_ACK_PREFIX+data.task_id);
        }catch(_){}
      }
      const state=document.getElementById("en-review-share-state");
      if(state) state.textContent=data.sheet_finalized
        ? "已讀取中央 Google Sheet 正式英文定稿（Google Drive 尚待同步）"
        : (data.manuscript_source==="youtube.en.json"
          ? "已依中文 Final 時間軸載入 YouTube English CC 初稿（尚未人工定稿）"
          : "已取得英文稿；正在核對中央 Google Sheet 逐句人工修改")+
        (englishReviewDirtyIds.size?"；本機尚未儲存的修改已保留":"");
      requestEnglishCloudOverrides(data.task_id);
      // For earlier Drive-completed lessons, seed a separate GitHub /en.json
      // only once. Future opening is fast and will not touch Chinese /zh.json.
      if(bridgeAuthenticated && data.task_id &&
         !["en.review.draft.json","youtube.en.json","google-sheet-final"].includes(String(data.manuscript_source||"")) &&
         Array.isArray(data.segments) && data.segments.length &&
         !englishCacheSeedRequested.has(data.task_id)){
        englishCacheSeedRequested.add(data.task_id);
        submitBridgePost({action:"review_cache_seed_en",task_id:data.task_id});
      }
    }
  }

  if(data.type==="english_review_draft_saved"){
    finishEnglishReviewDraftSave(data);
  }
  if(data.type==="review_en_draft_status"){
    const taskId=String(data.task_id||"");
    if(data.ok && data.edits && typeof data.edits==="object" &&
       taskId===String(selectedTaskId||"")){
      englishCloudOverridesByTask[taskId]=data.edits;
      if(englishDraftSavePendingId===null && !englishReviewDirtyIds.size &&
         Array.isArray(currentEnglishReview) && currentEnglishReview.length){
        renderEnglishReview(currentEnglishReview);
        const state=document.getElementById("en-review-share-state");
        if(state)state.textContent="已從中央 Google Sheet 核對 "+
          Object.keys(data.edits).length+" 筆逐句人工定稿";
      }
    }
    const verifiedNew=data.committed===true;
    const verifiedLegacy=data.committed===undefined &&
      Boolean(data.saved_at) && !data.error;
    if(data.ok && englishDraftSaveRequestId &&
       taskId===String(selectedTaskId||"") &&
       String(data.request_id||"")===englishDraftSaveRequestId &&
       (verifiedNew || verifiedLegacy || Boolean(data.error))){
      finishEnglishReviewDraftSave({
        source:"soulkey-bridge",type:"english_review_draft_saved",
        ok:(verifiedNew||verifiedLegacy)&&!data.error,task_id:taskId,
        request_id:data.request_id,saved_at:data.saved_at,
        error:data.error||"",message:data.message||"",github_synced:false
      });
      if(verifiedNew)requestEnglishCloudOverrides(taskId);
    }
  }

  if(data.type==="review_saved"){
    if(data.kind==="zh" && data.ok && data.sheet_finalized &&
       zhFinalPendingTaskId===String(data.task_id||"")){
      const id=zhFinalPendingTaskId;
      zhFinalPendingTaskId="";
      setZhFinalizeEnabled(true);
      setZhReviewLoadState("本堂中文定稿已存中央 Sheet 並回讀驗證；Drive 待同步","ok");
      const task=tasks.find(x=>x.id===id);
      if(task){
        task.zh_review="完成";
        task.status="中文中央定稿已驗證";
        save(STORE.tasks,tasks);
      }
      requestTaskStatuses();
      if(currentView==="review"&&selectedTaskId===id)openTaskDetail(id);
      return;
    }
    if(data.kind==="zh" && !data.ok){
      zhFinalPendingTaskId="";
      setZhFinalizeEnabled(true);
      setZhReviewLoadState("中文定稿沒有寫入："+(data.message||data.error||"未知錯誤"),"error");
      return;
    }
    const state=document.getElementById("en-review-share-state");
    const button=document.getElementById("finalize-en");

    if(data.ok && data.kind==="en" && data.sheet_finalized){
      const id=String(data.task_id||"");
      markVerifiedEnglishStage(id,"sheet");
      try{localStorage.removeItem(ENGLISH_FINAL_PENDING_PREFIX+id);}catch(_){}
      if(englishFinalizePendingTaskId===id)completeEnglishFinalizeUi(id,"sheet");
      else{
        englishSheetFinalizedThisSession.add(id);
        syncEnglishFinalizeButton(tasks.find(x=>x.id===id));
        if(state)state.textContent=String(data.message||"英文已保存到 Google Sheet");
      }
    }else if(data.ok && data.drive_saved===true && data.kind==="en"){
      const id=String(data.task_id||"");
      markVerifiedEnglishStage(id,"drive");
      try{localStorage.removeItem(ENGLISH_FINAL_PENDING_PREFIX+id);}catch(_){}
      if(englishFinalizePendingTaskId===id)completeEnglishFinalizeUi(id,"callback");
    }else if(data.backup_saved===true && data.kind==="en"){
      const taskId=String(data.task_id||"");
      englishFinalizePendingTaskId="";
      englishFinalizePriorFinishedAt="";
      window.clearTimeout(englishFinalizeWatchdog);
      try{
        const backup=JSON.parse(localStorage.getItem(
          ENGLISH_FINAL_PENDING_PREFIX+taskId)||"null");
        if(backup?.task_id===taskId){
          backup.backup_saved=true;
          backup.backup_id=String(data.backup_id||"");
          backup.backup_at=new Date().toISOString();
          localStorage.setItem(ENGLISH_FINAL_PENDING_PREFIX+taskId,JSON.stringify(backup));
        }
      }catch(_){}
      syncEnglishFinalizeButton(tasks.find(x=>x.id===taskId));
      if(state) state.textContent=
        "英文全文 "+Number(data.segment_count||0)+" 段已備份到中央 Google Sheet，未遺失。"+
        "Google Drive 正式檔案尚未完成，系統不會標記為定稿。";
    }else if(data.ok){
      requestTaskStatuses();

      if(
        data.kind==="en" &&
        englishFinalizePendingTaskId &&
        String(data.task_id||"")===String(englishFinalizePendingTaskId)
      ){
        try{localStorage.removeItem(ENGLISH_FINAL_PENDING_PREFIX+data.task_id);}catch(_){}
        completeEnglishFinalizeUi(data.task_id,"callback");
      }
    }else{
      if(englishFinalizePendingTaskId){
        englishFinalizePendingTaskId="";
        window.clearTimeout(englishFinalizeWatchdog);
        if(button){
          button.disabled=false;
          button.textContent="英文定稿";
        }
        if(state) state.textContent="英文定稿儲存失敗："+(data.message||data.error||"未知錯誤");
      }else{
        alert("人工定稿寫入失敗："+(data.message || data.error || "未知錯誤"));
      }
    }
  }

  if(data.type==="run_stage"){
    const youtube=pendingYoutubeCapture;
    if(youtube && data.stage==="cc" &&
       (!data.task_id || data.task_id===youtube.taskId)){
      pendingYoutubeCapture=null;
      const status=document.getElementById("youtube-audio-status");
      const button=document.getElementById("youtube-audio-run");
      if(button)button.disabled=false;
      if(data.ok){
        if(status)status.textContent=youtube.mode==="cc"
          ?"中央佇列已確認，等待 GitHub Actions 抓取本堂可用的七語 CC"
          :"中央佇列已確認";
        setCaptureState("cc",{key:"working",label:"已排隊",
          detail:"只在 Worker 領取後執行；結果儲存在中央 Sheet，Drive 待同步"});
        requestTaskStatuses();
      }else{
        const error=String(data.message||data.error||"功能尚未恢復");
        if(status)status.textContent="沒有建立 YouTube 抓取工作："+error;
        setCaptureState(youtube.mode==="cc"?"cc":"audio",
          {key:"error",label:"未送出",detail:error});
        alert("YouTube "+(youtube.mode==="cc"?"CC 字幕":"音軌")+
          "工作沒有送出："+error);
      }
      return;
    }
    const pending=pendingRunStageRequest;
    pendingRunStageRequest=null;
    if(data.ok){
      if(pending &&
         (!data.task_id || String(data.task_id)===pending.taskId) &&
         (!data.stage || String(data.stage)===pending.stage)){
        const job=tasks.find(x=>x.id===pending.taskId);
        if(job){
          job.status="排隊中："+(workflow.find(x=>x.key===pending.stage)?.label||pending.stage);
          job.remoteStages=job.remoteStages||{};
          job.remoteStages[pending.stage]={
            task_id:job.id,stage:pending.stage,status:"queued",progress:"0",
            message:data.queue_mode==="scheduled-github-actions"
              ?"已寫入中央翻譯佇列，等待 GitHub CPU Worker 領取"
              :"已收到 GitHub/Kaggle 派工回覆"
          };
          save(STORE.tasks,tasks);
          renderTasks();
          if(currentView==="task-detail"&&selectedTaskId===job.id)
            renderTaskDetail(job);
        }
      }
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
      if(pending){
        const job=tasks.find(x=>x.id===pending.taskId);
        if(job){
          job.status="派工未成功（英文定稿資料不受影響）";
          save(STORE.tasks,tasks);
          renderTasks();
          if(currentView==="task-detail"&&selectedTaskId===job.id)
            renderTaskDetail(job);
        }
      }
      alert("多語／音檔工作尚未送出："+(data.message || data.error || "未知錯誤")+
        "。英文中央定稿仍已保存，沒有啟動或重跑 Kaggle。");
    }
  }

  if(data.type==="youtube_cc_content"){
    if(data.ok && String(data.content||"")){
      const fileName=String(data.name||"captions.txt").replace(/[^A-Za-z0-9._-]/g,"_");
      const blob=new Blob([data.content],{type:"text/plain;charset=utf-8"});
      const link=document.createElement("a"),url=URL.createObjectURL(blob);
      link.href=url;link.download=fileName;document.body.appendChild(link);link.click();
      link.remove();window.setTimeout(()=>URL.revokeObjectURL(url),10000);
    }else alert("字幕未通過本堂來源驗證，無法下載："+(data.message||data.error||"未知錯誤"));
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

  if(data.type==="review_cache_status" && data.ok){
    const id=String(data.task_id||"");
    if(data.stale && selectedTaskId===id &&
       !reviewCacheSeedRequested.has(id)){
      reviewCacheSeedRequested.add(id);
      setZhReviewLoadState(
        "偵測到 GitHub 中文快取版本較舊・正在同步 Drive Final…",
        "working"
      );
      submitBridgePost({action:"review_cache_seed",task_id:id});
    }
  }

  if(data.type==="review_cache_seeded"){
    const id=String(data.task_id||"");
    if(data.ok){
      invalidateReviewFetch(id,"zh");
      if(selectedTaskId===id && currentView==="review"){
        loadZhReviewFromGithub(id);
      }
    }else if(selectedTaskId===id && currentView==="review"){
      setZhReviewLoadState(
        "Drive 資料已保留・GitHub 快取等待自動修復","working"
      );
    }
  }

  if(data.type==="tts_share_links"){
    const id=String(data.task_id||"");
    if(id && ttsShareLoadingTask===id) ttsShareLoadingTask="";
    if(data.ok && id){
      ttsShareLinksCache[id]=data;
      ttsShareLinksFetchedAt[id]=Date.now();
      delete ttsShareLinkErrors[id];
    }else if(id){
      ttsShareLinkErrors[id]=data.message||data.error||"伺服器未傳回音檔資料";
    }
    const selected=tasks.find(x=>String(x.id)===id);
    if(selected && currentView==="task-detail" && selectedTaskId===id){
      renderTtsShare(selected);
      refreshLanguageDeliveryStatus(selected);
    }
  }

  if(data.type==="course_files"){
    if(!data.ok) courseFilesLoadFailed(data.task_id||courseFilesLoadingTask,data.message||data.error||"後端讀取失敗");
    else courseFilesLoadingTask="";
    const badge=document.getElementById("course-files-state");

    if(data.ok && data.task_id){
      courseFilesCache[data.task_id]=data;
      courseFilesFetchedAt[data.task_id]=Date.now();
      const selected=tasks.find(x=>String(x.id)===String(data.task_id));
      if(
        selected &&
        currentView==="task-detail" &&
        String(selectedTaskId)===String(data.task_id)
      ){
        renderCourseFiles(selected);
        renderTtsShare(selected);
        refreshLanguageDeliveryStatus(selected);
      }
    }else if(badge){
      badge.textContent="檔案讀取失敗";
      badge.className="badge";
    }
  }

  if(data.type==="period_reordered"){
    const state=document.getElementById("schedule-state");
    const status=document.getElementById("schedule-status");
    const button=document.getElementById("schedule-apply-order");
    if(button) button.disabled=false;

    if(data.ok){
      if(state){
        state.textContent=data.changed===false ? "順序未變" : "排序完成";
        state.className="badge complete";
      }
      if(status){
        status.textContent=data.message || "同一期課程排序完成。";
      }
      scheduleDraftPeriod=Number(data.period)||scheduleDraftPeriod;
      scheduleDraftOrder=Array.isArray(data.ordered_task_ids)
        ? data.ordered_task_ids.map(String)
        : [];
      requestTasksFromControlCenter();
      window.setTimeout(()=>requestTaskStatuses(),200);
    }else{
      if(state){
        state.textContent="排序失敗";
        state.className="badge";
      }
      if(status){
        status.textContent="期內排序失敗："+(data.message||data.error||"未知錯誤");
      }
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
      scheduleDraftPeriod=null;
      scheduleDraftOrder=[];
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
      if(selectedTaskId===task.id){
        renderLanguagePlan(task);
        if(currentView==="task-detail") renderTtsShare(task);
      }
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
      driveOwnerConfigured=data.drive_owner_configured===true;
      youtubeCCQueueEnabled=data.youtube_cc_queue_enabled===true;
      bridgeIsCloudRecovery=String(data.bridge_protocol||"")==="cloud-recovery";
      syncYoutubeCaptureModeUi();
      bridgeProtocolVersion=String(data.bridge_protocol||"")==="cloud-recovery"
        ? REQUIRED_BRIDGE_PROTOCOL : Number(data.bridge_protocol||0);
      const protocolOk=bridgeProtocolVersion>=REQUIRED_BRIDGE_PROTOCOL;
      if(syncState){
        syncState.textContent=protocolOk ? "狀態表已連線" : "控制中心版本過舊";
        syncState.className=protocolOk ? "ok" : "warn";
      }
      const apiState=document.getElementById("api-state");
      if(apiState){
        apiState.textContent=protocolOk
          ? (String(data.bridge_protocol||"")==="cloud-recovery"?"Cloud Run 已連線":"Apps Script 已連線")
          : "控制中心版本需更新";
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
        setDashboardBridgeState("已驗證控制中心；正在載入正式任務…","working");
      }else{
        setDashboardBridgeState(
          "控制中心可讀取，但 Apps Script 部署版本落後；請重新部署 Code.gs 後再執行新工作。",
          "error"
        );
      }
      if(protocolOk){
        requestTasksFromControlCenter();
        requestLanguageSettings();
      }
    }else{
      const reason=data.error==="unauthorized"
        ? "Bridge Key 驗證失敗。原 Apps Script 六碼可在管理者完成一次「SoulKey-啟用共用6碼登入.cmd」後於此直接使用。"
        : data.error==="rate_limited"
          ? "登入嘗試過多，請稍後再試或通知管理者。"
        : (data.message || data.error || "未知錯誤");
      bridgeSyncRequestFailed("status_health",reason);
      if(syncState){
        syncState.textContent="狀態表連線失敗";
        syncState.className="warn";
      }
      if(syncText) syncText.textContent="狀態表連線失敗："+reason;
    }
  }
});

document.getElementById("schedule-period-select")?.addEventListener("change",event=>{
  resetScheduleDraft(Number(event.target.value)||0);
});
document.getElementById("schedule-reset-order")?.addEventListener("click",()=>{
  resetScheduleDraft(Number(document.getElementById("schedule-period-select")?.value)||0);
  const status=document.getElementById("schedule-status");
  if(status) status.textContent="已還原成控制中心目前順序，尚未送出任何變更。";
});
document.getElementById("schedule-apply-order")?.addEventListener("click",applyPeriodReorder);

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
  updateAdvancedSchedulePreview();
});
document.getElementById("schedule-new-period")?.addEventListener("input",updateAdvancedSchedulePreview);
document.getElementById("schedule-new-lesson")?.addEventListener("change",updateAdvancedSchedulePreview);
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
    if(!bridgeAuthenticated) return;
    requestTaskStatuses();
  },STATUS_POLL_MS);

  window.setInterval(()=>{
    if(!bridgeAuthenticated) return;
    // Background dashboard refresh is irrelevant to a long-lived English
    // editing session, and must not disrupt local unsaved edits.
    if(currentView==="en-review") return;
    requestTasksFromControlCenter();
  },180000);
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
  document.getElementById("dashboard-firebase-connect")?.addEventListener("click",restoreFirebaseSnapshot);
  document.getElementById("dashboard-firebase-key")?.addEventListener("keydown",e=>{
    if(e.key==="Enter"){e.preventDefault();restoreFirebaseSnapshot();}
  });
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
    setDashboardBridgeState("已保留 Bridge Key，正在驗證控制中心；驗證前禁止修改。","working");
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

const cfg = window.SOULKEY_CONFIG || {};

const STORE = {
  tasks: "soulkey_studio_tasks_v2",
  terms: "soulkey_studio_terms_v1",
  gpu: "soulkey_studio_gpu_v1"
};

const BRIDGE_ENDPOINT_KEY = "soulkey_bridge_endpoint_v1";
const BRIDGE_SESSION_KEY = "soulkey_bridge_key_session_v1";
const STATUS_POLL_MS = 12000;

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

const WORKFLOW_VERSION = 4;

const workflow = [
  {key:"metadata", label:"來源資訊", short:"來源", hint:"免 GPU"},
  {key:"asr", label:"ASR 逐字稿", short:"逐字稿", hint:"GPU"},
  {key:"polish", label:"AI 中文校稿", short:"AI校稿", hint:"GPU"},
  {key:"review", label:"人工中文定稿", short:"中定稿", hint:"人工"},
  {key:"vernacular", label:"AI 白話文", short:"白話AI", hint:"GPU"},
  {key:"vernacular-review", label:"人工白話文定稿", short:"白定稿", hint:"人工"},
  {key:"en", label:"英文翻譯", short:"英文", hint:"GPU"},
  {key:"en-review", label:"人工英文定稿", short:"英定稿", hint:"人工"},
  {key:"multi", label:"各國語言翻譯", short:"多語", hint:"依選擇"},
  {key:"tts", label:"各國語言音檔", short:"音檔", hint:"依選擇"}
];

function load(key, fallback){
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}
function save(key, value){ localStorage.setItem(key, JSON.stringify(value)); }

let tasks = load(STORE.tasks, []);
let terms = load(STORE.terms, seedTerms);
let languageSettings = [
  {code:"th",name:"ภาษาไทย",can_ai_translate:true,can_tts:true},
  {code:"es",name:"Español",can_ai_translate:true,can_tts:true},
  {code:"id",name:"Bahasa Indonesia",can_ai_translate:true,can_tts:true},
  {code:"vi",name:"Tiếng Việt",can_ai_translate:true,can_tts:true}
];
let selectedTaskId = null;
let selectedPeriod = null;
let currentView = "dashboard";
const viewHistory = [];

if(!localStorage.getItem(STORE.terms)) save(STORE.terms, terms);

const titles = {
  dashboard:"任務總覽",
  "new-task":"建立任務",
  "task-detail":"課程任務",
  review:"中文逐字稿校稿",
  "vernacular-review":"人工白話文定稿",
  "en-review":"人工英文定稿",
  glossary:"專有名詞庫",
  knowledge:"經典知識庫",
  system:"系統狀態"
};

function escapeHtml(s){
  return String(s ?? "").replace(/[&<>"']/g,m=>({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[m]));
}

function updateBackButton(){
  const button=document.getElementById("back-button");
  if(!button) return;
  button.hidden=currentView==="dashboard";
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

  // v2：英文翻譯後加入「人工英文定稿」。
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

  t.workflowVersion=version;
  if(t.completedStep >= workflow.length) t.completedStep=workflow.length-1;
  if(!t.status) t.status="等待執行";
  return t;
}

function remoteStageStatus(task, stageKey){
  return task && task.remoteStages && task.remoteStages[stageKey]
    ? task.remoteStages[stageKey]
    : null;
}

function syncCompletedFromRemote(task){
  normalizeTask(task);
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
            '<div><b>'+escapeHtml(t.id)+'</b>'+
            '<small>第'+escapeHtml(t.period)+'期</small></div>'+
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
          '<button class="ghost task-review-btn" data-review-task="'+escapeHtml(t.id)+'">校正逐字稿</button>'+
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

    document.querySelectorAll("[data-next-task]").forEach(btn=>{
      btn.addEventListener("click",e=>{
        e.stopPropagation();
        confirmNextStage(btn.dataset.nextTask);
      });
    });
  }

  document.getElementById("stat-tasks").textContent=tasks.length;
  document.getElementById("stat-terms").textContent=terms.length;
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

  return languageSettings
    .filter(lang=>lang.code!=="en")
    .map(lang=>{
      const saved=byCode[lang.code] || {};
      return {
        language_code:lang.code,
        language_name:lang.name,
        transcript_enabled:!!saved.transcript_enabled,
        transcript_source:saved.transcript_source || "ai",
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
    return '<article class="language-plan-row" data-lang-plan="'+escapeHtml(item.language_code)+'">'+
      '<div class="language-name"><b>'+escapeHtml(item.language_name)+'</b><small>'+escapeHtml(item.language_code)+'</small></div>'+
      '<div class="language-output-cell">'+
        '<label class="output-toggle"><input type="checkbox" data-plan-transcript '+(item.transcript_enabled?"checked":"")+'> 需要文稿</label>'+
        '<select data-plan-transcript-source '+(!item.transcript_enabled?"disabled":"")+'>'+
          '<option value="ai" '+(item.transcript_source==="ai"?"selected":"")+' '+(aiDisabled?"disabled":"")+'>AI 翻譯</option>'+
          '<option value="human" '+(item.transcript_source==="human"?"selected":"")+'>真人翻譯／人工提供</option>'+
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
  return submitBridgePost({action:"language_settings"});
}

function requestLanguagePlan(taskId){
  if(!taskId) return false;
  return submitBridgePost({action:"language_plan_get",task_id:taskId});
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
    const reviewStage=["polish","review","vernacular-review","en-review"].includes(stage.key);
    return '<button class="detail-stage '+state+'" data-detail-stage="'+i+'" '+(state==="locked"?"disabled":"")+'>'+
      '<span class="detail-stage-number">'+String(i+1).padStart(2,"0")+'</span>'+
      '<div><b>'+escapeHtml(stage.label)+'</b><small>'+label+'・'+escapeHtml(stage.hint)+'</small></div>'+
      (reviewStage?'<em>'+(stage.key==="en-review"?"英文定稿":stage.key==="vernacular-review"?"白話定稿":"中文校稿")+'</em>':'')+
    '</button>';
  }).join("");

  const current=next || workflow[workflow.length-1];
  const isChineseReview = next && ["polish","review"].includes(next.key);
  const isVernacularReview = next && next.key==="vernacular-review";
  const isEnglishReview = next && next.key==="en-review";
  document.getElementById("detail-current-title").textContent=
    next ? next.label : "全部流程完成";

  if(!next){
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message success"><b>這堂課已全部完成</b><span>所有流程均已完成。</span></div>';
  }else if(isChineseReview){
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message review-ready">'+
        '<div><b>現在要進行中文校稿</b><span>進入後可查看 ASR 原文、AI 修改、待人工確認與逐段修正。</span></div>'+
        '<button class="primary" data-open-review-inline="'+escapeHtml(task.id)+'">進入中文校稿</button>'+
      '</div>';
  }else if(isVernacularReview){
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message review-ready">'+
        '<div><b>現在要進行人工白話文定稿</b><span>逐段比較中文原文與 AI 白話文，修正完成後才會開放英文翻譯。</span></div>'+
        '<button class="primary" data-open-vernacular-review-inline="'+escapeHtml(task.id)+'">進入人工白話文定稿</button>'+
      '</div>';
  }else if(isEnglishReview){
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message review-ready">'+
        '<div><b>現在要進行人工英文定稿</b><span>逐段查看中文白話底稿與英文翻譯，修正後同步學習專有名詞的正式英文譯法。</span></div>'+
        '<button class="primary" data-open-en-review-inline="'+escapeHtml(task.id)+'">進入人工英文定稿</button>'+
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
  reviewBtn.hidden = task.completedStep < 1;
  reviewBtn.onclick=()=>openTaskReview(task.id);

  const nextBtn=document.getElementById("detail-next-btn");
  const nextRemote=next ? remoteStageStatus(task,next.key) : null;
  nextBtn.disabled=!next || !!(nextRemote && ["queued","running"].includes(nextRemote.status));
  const humanReviewNext=next && ["vernacular-review","en-review"].includes(next.key);
  nextBtn.textContent=next ? (humanReviewNext ? "進入："+next.label : "執行下一步："+next.label) : "已全部完成";
  nextBtn.onclick=()=>{
    if(!next) return;
    if(next.key==="vernacular-review") return openVernacularReview(task.id);
    if(next.key==="en-review") return openEnglishReview(task.id);
    return confirmNextStage(task.id);
  };

  document.querySelectorAll("[data-open-review-inline]").forEach(btn=>{
    btn.addEventListener("click",()=>openTaskReview(btn.dataset.openReviewInline));
  });

  document.querySelectorAll("[data-open-vernacular-review-inline]").forEach(btn=>{
    btn.addEventListener("click",()=>openVernacularReview(btn.dataset.openVernacularReviewInline));
  });

  document.querySelectorAll("[data-open-en-review-inline]").forEach(btn=>{
    btn.addEventListener("click",()=>openEnglishReview(btn.dataset.openEnReviewInline));
  });

  document.querySelectorAll("[data-detail-stage]").forEach(btn=>{
    btn.addEventListener("click",()=>{
      const index=Number(btn.dataset.detailStage);
      const stage=workflow[index];
      if(["polish","review"].includes(stage.key)){
        openTaskReview(task.id);
      }else if(stage.key==="vernacular-review"){
        openVernacularReview(task.id);
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
  showView("review");
}

function confirmNextStage(taskId){
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;
  normalizeTask(task);
  const next=nextStageFor(task);
  if(!next) return;

  const ok=confirm(
    task.id+"｜"+task.lesson+"\n\n"+
    "確定執行下一步驟：\n"+next.label+"？\n\n"+
    (cfg.apiBaseUrl
      ? "確認後會送出後端工作。"
      : "目前是 UI 原型，先記錄流程狀態；後端接上後這顆按鈕會真正啟動 Kaggle。")
  );
  if(!ok) return;

  task.status="已確認："+next.label;

  if(cfg.apiBaseUrl){
    task.status="排隊中："+next.label;
    fetch(cfg.apiBaseUrl.replace(/\/$/,"")+"/jobs/"+encodeURIComponent(task.id)+"/run",{
      method:"POST",
      headers:{"content-type":"application/json"},
      body:JSON.stringify({stage:next.key})
    }).then(r=>{
      if(!r.ok) throw new Error("API "+r.status);
      task.completedStep+=1;
      task.status="完成："+next.label;
      save(STORE.tasks,tasks);
      renderTasks();
    }).catch(err=>{
      task.status="送出失敗："+err.message;
      save(STORE.tasks,tasks);
      renderTasks();
    });
  }else{
    task.completedStep+=1;
    task.status="完成："+next.label;
    save(STORE.tasks,tasks);
    renderTasks();
    if(currentView==="task-detail" && selectedTaskId===task.id){
      renderTaskDetail(task);
    }
  }
}

function updateTaskCodes(){
  const period=Number(document.getElementById("period").value)||0;
  for(let i=1;i<=4;i++){
    document.getElementById("task-code-"+i).textContent=
      "P"+period+"-L"+String(i).padStart(2,"0");
  }
}
document.getElementById("dashboard-period")?.addEventListener("change",e=>{
  selectedPeriod=Number(e.target.value)||null;
  renderTasks();
});

document.getElementById("period").addEventListener("input",updateTaskCodes);

document.getElementById("task-form").addEventListener("submit",async e=>{
  e.preventDefault();

  const period=Number(document.getElementById("period").value);
  const note=document.getElementById("task-note").value.trim();
  const urls=[1,2,3,4].map(i=>document.getElementById("youtube-url-"+i).value.trim());

  if(urls.some(x=>!x)){
    alert("四堂課都要填入 YouTube 網址。");
    return;
  }

  const created=[];
  for(let i=1;i<=4;i++){
    const id="P"+period+"-L"+String(i).padStart(2,"0");
    const existing=tasks.find(t=>t.id===id);

    const task=existing || {
      id,
      period,
      lesson:"第"+i+"堂",
      completedStep:-1,
      workflowVersion:WORKFLOW_VERSION,
      createdAt:new Date().toISOString()
    };

    task.url=urls[i-1];
    task.note=note;
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

  e.target.reset();
  document.getElementById("period").value=period;
  updateTaskCodes();

  alert(
    "第 "+period+" 期四堂課已建立：\n"+
    created.map(t=>"• "+t.id+" "+t.lesson).join("\n")
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

function renderSegments(items){
  const el=document.getElementById("segment-list");

  if(!items.length){
    el.innerHTML='<div class="empty">沒有符合目前篩選條件的段落。</div>';
    return;
  }

  el.innerHTML=items.map((s,i)=>
    '<div class="segment '+s.flags.join(" ")+'" data-time="'+escapeHtml(s.time)+'">'+
      '<div class="segment-meta">'+
        '<span>'+escapeHtml(s.time)+'</span>'+
        '<span>'+s.flags.map(x=>x==="uncertain"?"⚠ 待人工確認":"AI 已修改").join(" · ")+'</span>'+
      '</div>'+
      '<div class="muted">ASR：'+escapeHtml(s.raw)+'</div>'+
      '<textarea>'+escapeHtml(s.text)+'</textarea>'+
      '<div class="segment-actions">'+
        '<button class="mini term">加入詞庫</button>'+
        '<button class="mini confirm">確認此句</button>'+
      '</div>'+
    '</div>'
  ).join("");

  document.getElementById("stat-uncertain").textContent=
    demoSegments.filter(x=>x.flags.includes("uncertain")).length;

  document.querySelectorAll(".segment").forEach(seg=>{
    seg.addEventListener("click",()=>{
      document.getElementById("current-time").textContent=seg.dataset.time||"--:--";
    });
  });
}

document.getElementById("load-demo").addEventListener(
  "click",()=>renderSegments(demoSegments)
);

document.querySelectorAll("[data-filter]").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll("[data-filter]").forEach(
    x=>x.classList.toggle("active",x===b)
  );
  const filter=b.dataset.filter;
  renderSegments(
    filter==="all"
      ? demoSegments
      : demoSegments.filter(x=>x.flags.includes(filter))
  );
}));

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
    "定稿後，這堂課下一步會進入「全文白話化」。"
  );
  if(!ok) return;

  task.completedStep=Math.max(task.completedStep,3);
  task.status="中文已定稿";
  save(STORE.tasks,tasks);
  renderTasks();
  alert("已標記中文定稿。下一步："+workflow[4].label);
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

  showView("vernacular-review");
}

function renderVernacularReview(items){
  const list=document.getElementById("vernacular-review-list");
  if(!list) return;

  list.innerHTML=items.map(item=>
    '<article class="vernacular-review-row" data-vernacular-segment="'+item.id+'">'+
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
    "確定白話文已逐段人工確認完成並定稿？\n"+
    "定稿後，英文翻譯只能使用這份人工白話文 Final。"
  );
  if(!ok) return;

  task.completedStep=Math.max(task.completedStep,5);
  task.status="白話文已定稿";
  task.workflowVersion=WORKFLOW_VERSION;
  save(STORE.tasks,tasks);
  renderTasks();

  alert("白話文已定稿。下一步："+workflow[6].label);
  openTaskDetail(task.id);
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

function openEnglishReview(taskId){
  selectedTaskId=taskId;
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;

  const context=document.getElementById("en-review-task-context");
  context.innerHTML=
    '<b>'+escapeHtml(task.id)+'</b>'+
    '<span>第'+escapeHtml(task.period)+'期・'+escapeHtml(task.lesson)+'</span>'+
    '<small>'+escapeHtml(task.url)+'</small>';

  showView("en-review");
}

function renderEnglishReview(items){
  const list=document.getElementById("en-review-list");
  const termBox=document.getElementById("en-term-learning");
  if(!list || !termBox) return;

  list.innerHTML=items.map(item=>
    '<article class="en-review-row" data-en-segment="'+item.id+'">'+
      '<div class="en-review-meta">'+
        '<span>#'+item.id+'</span><span>'+escapeHtml(item.time)+'</span>'+
      '</div>'+
      '<div class="en-review-pair">'+
        '<div class="zh-source original-column">'+escapeHtml(item.original)+'</div>'+
        '<div class="zh-source vernacular-column">'+escapeHtml(item.vernacular)+'</div>'+
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
          description:"由人工英文定稿同步學習",
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

document.getElementById("load-en-demo")?.addEventListener(
  "click",()=>renderEnglishReview(demoEnglishReview)
);

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
    "確定英文翻譯已人工確認完成並定稿？\n"+
    "定稿後，後續泰文／西文／印尼文／越南文都只使用這份英文 Final 作為 Pivot。"
  );
  if(!ok) return;

  task.completedStep=Math.max(task.completedStep,7);
  task.status="英文已定稿";
  task.workflowVersion=WORKFLOW_VERSION;
  save(STORE.tasks,tasks);
  renderTasks();

  alert("英文已定稿。下一步："+workflow[8].label);
  openTaskDetail(task.id);
});

function submitBridgePost(fields){
  const endpoint=
    document.getElementById("bridge-endpoint")?.value.trim() ||
    localStorage.getItem(BRIDGE_ENDPOINT_KEY) ||
    cfg.bridgeEndpoint ||
    "";
  const key=
    document.getElementById("bridge-key")?.value.trim() ||
    sessionStorage.getItem(BRIDGE_SESSION_KEY) ||
    "";

  if(!endpoint || !key) return false;

  const form=document.createElement("form");
  form.method="POST";
  form.action=endpoint;
  form.target="soulkey-bridge-target";
  form.style.display="none";

  const payload={...fields,bridge_key:key};
  for(const [name,value] of Object.entries(payload)){
    const input=document.createElement("input");
    input.type="hidden";
    input.name=name;
    input.value=String(value ?? "");
    form.appendChild(input);
  }

  document.body.appendChild(form);
  form.submit();
  window.setTimeout(()=>form.remove(),2000);
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
  const key=sessionStorage.getItem(BRIDGE_SESSION_KEY) || "";
  const endpoint=localStorage.getItem(BRIDGE_ENDPOINT_KEY) || cfg.bridgeEndpoint || "";
  if(!key || !endpoint || !tasks.length) return false;

  const ids=tasks.map(t=>t.id).filter(Boolean).slice(0,20);
  if(!ids.length) return false;

  return submitBridgePost({
    action:"status_batch",
    task_ids:ids.join(",")
  });
}

function requestStatusHealth(){
  return submitBridgePost({action:"status_health"});
}

window.addEventListener("message",event=>{
  const data=event.data || {};
  if(data.source!=="soulkey-bridge") return;

  if(data.type==="status_result"){
    if(data.ok){
      applyRemoteStatuses(data);
    }else{
      const syncState=document.getElementById("status-sync-state");
      if(syncState){
        syncState.textContent="同步失敗";
        syncState.className="warn";
      }
    }
  }

  if(data.type==="language_settings" && data.ok){
    const received=Array.isArray(data.languages) ? data.languages : [];
    if(received.length){
      languageSettings=received.filter(x=>x.code!=="en");
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
      if(status) status.textContent="已同步到中央控制表。";
    }else if(status){
      status.textContent="語言設定同步失敗，請稍後再試。";
    }
  }

  if(data.type==="status_health"){
    const syncState=document.getElementById("status-sync-state");
    const syncText=document.getElementById("status-sync-text");
    if(data.ok){
      if(syncState){
        syncState.textContent="狀態表已連線";
        syncState.className="ok";
      }
      if(syncText){
        syncText.textContent="執行狀態表目前 "+String(data.rows||0)+" 筆紀錄";
      }
      requestTaskStatuses();
      requestLanguageSettings();
    }else if(syncState){
      syncState.textContent="狀態表連線失敗";
      syncState.className="warn";
    }
  }
});

document.getElementById("save-language-plan")?.addEventListener("click",saveLanguagePlanForSelectedTask);
document.getElementById("refresh-language-settings")?.addEventListener("click",()=>{
  requestLanguageSettings();
  if(selectedTaskId) requestLanguagePlan(selectedTaskId);
});

function initStatusPolling(){
  window.setTimeout(()=>{
    requestStatusHealth();
    requestTaskStatuses();
  },1200);

  window.setInterval(()=>{
    requestTaskStatuses();
  },STATUS_POLL_MS);
}

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
  const endpointInput=document.getElementById("bridge-endpoint");
  const keyInput=document.getElementById("bridge-key");
  const testButton=document.getElementById("bridge-test");
  if(!endpointInput || !keyInput || !testButton) return;

  endpointInput.value=localStorage.getItem(BRIDGE_ENDPOINT_KEY) || cfg.bridgeEndpoint || "";
  keyInput.value=sessionStorage.getItem(BRIDGE_SESSION_KEY) || "";

  if(endpointInput.value){
    setBridgeStatus("Apps Script Web App URL 已設定，可以輸入 Bridge Key 後測試。","ready");
  }

  endpointInput.addEventListener("change",()=>{
    const value=endpointInput.value.trim();
    if(value){
      localStorage.setItem(BRIDGE_ENDPOINT_KEY,value);
      setBridgeStatus("Apps Script Web App URL 已儲存。","ready");
    }else{
      localStorage.removeItem(BRIDGE_ENDPOINT_KEY);
      setBridgeStatus("尚未設定 Apps Script Web App URL。","idle");
    }
  });

  keyInput.addEventListener("input",()=>{
    const value=keyInput.value.trim();
    if(value){
      sessionStorage.setItem(BRIDGE_SESSION_KEY,value);
      window.setTimeout(()=>requestStatusHealth(),250);
    }else{
      sessionStorage.removeItem(BRIDGE_SESSION_KEY);
    }
  });

  testButton.addEventListener("click",()=>{
    const endpoint=endpointInput.value.trim();
    const key=keyInput.value.trim();

    if(!endpoint){
      setBridgeStatus("請先貼上 Apps Script Web App URL。","error");
      endpointInput.focus();
      return;
    }
    if(!key){
      setBridgeStatus("請輸入 Bridge Key。","error");
      keyInput.focus();
      return;
    }

    localStorage.setItem(BRIDGE_ENDPOINT_KEY,endpoint);
    sessionStorage.setItem(BRIDGE_SESSION_KEY,key);

    testButton.disabled=true;
    setBridgeStatus("正在送出網頁 → GitHub → Kaggle 測試…","sending");
    submitBridgePost({action:"smoke"});

    window.setTimeout(()=>{
      testButton.disabled=false;
      setBridgeStatus(
        "測試已送出。現在到 GitHub Actions 查看是否自動出現新的「Kaggle Run Bridge Test」。",
        "sent"
      );
      requestStatusHealth();
    },1500);
  });
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

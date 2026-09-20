const cfg = window.SOULKEY_CONFIG || {};

const STORE = {
  tasks: "soulkey_studio_tasks_v2",
  terms: "soulkey_studio_terms_v1",
  gpu: "soulkey_studio_gpu_v1"
};

const BRIDGE_ENDPOINT_KEY = "soulkey_bridge_endpoint_v1";
const BRIDGE_SESSION_KEY = "soulkey_bridge_key_session_v1";

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
  status:"正式詞庫"
}));

const workflow = [
  {key:"metadata", label:"來源資訊", short:"來源", hint:"免 GPU"},
  {key:"asr", label:"ASR 逐字稿", short:"逐字稿", hint:"GPU"},
  {key:"polish", label:"AI 中文校稿", short:"AI校稿", hint:"GPU"},
  {key:"review", label:"人工中文定稿", short:"定稿", hint:"人工"},
  {key:"vernacular", label:"全文白話化", short:"白話", hint:"GPU"},
  {key:"en", label:"英文翻譯", short:"英文", hint:"GPU"},
  {key:"multi", label:"四語翻譯", short:"四語", hint:"GPU"},
  {key:"tts", label:"各國音檔", short:"音檔", hint:"GPU"},
  {key:"video", label:"完成影片", short:"影片", hint:"最後"}
];

function load(key, fallback){
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}
function save(key, value){ localStorage.setItem(key, JSON.stringify(value)); }

let tasks = load(STORE.tasks, []);
let terms = load(STORE.terms, seedTerms);
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
  if(!t.status) t.status="等待執行";
  return t;
}

function nextStageFor(task){
  const t=normalizeTask(task);
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
            '<span class="muted">'+escapeHtml(t.status)+'</span>'+
          '</div>'+
        '</div>'+
        '<div class="course-task-actions">'+
          '<button class="ghost task-review-btn" data-review-task="'+escapeHtml(t.id)+'">校正逐字稿</button>'+
          '<button class="primary task-next-btn" data-next-task="'+escapeHtml(t.id)+'" '+(complete?"disabled":"")+'>'+
            (complete?"已完成":"執行下一步")+
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
  if(index<=task.completedStep) return "done";
  if(index===task.completedStep+1) return "current";
  return "locked";
}

function renderTaskDetail(task){
  normalizeTask(task);
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
    const label=state==="done"?"已完成":state==="current"?"目前步驟":"尚未開放";
    const reviewStage=stage.key==="polish" || stage.key==="review";
    return '<button class="detail-stage '+state+'" data-detail-stage="'+i+'" '+(state==="locked"?"disabled":"")+'>'+
      '<span class="detail-stage-number">'+String(i+1).padStart(2,"0")+'</span>'+
      '<div><b>'+escapeHtml(stage.label)+'</b><small>'+label+'・'+escapeHtml(stage.hint)+'</small></div>'+
      (reviewStage?'<em>中文校稿</em>':'')+
    '</button>';
  }).join("");

  const current=next || workflow[workflow.length-1];
  const isChineseReview = next && ["polish","review"].includes(next.key);
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
  }else{
    document.getElementById("detail-current-body").innerHTML=
      '<div class="stage-message">'+
        '<div><b>下一步：'+escapeHtml(next.label)+'</b><span>'+escapeHtml(next.hint)+' 工作。確認後才會執行這堂課的下一階段。</span></div>'+
      '</div>';
  }

  const reviewBtn=document.getElementById("detail-review-btn");
  reviewBtn.hidden = task.completedStep < 1;
  reviewBtn.onclick=()=>openTaskReview(task.id);

  const nextBtn=document.getElementById("detail-next-btn");
  nextBtn.disabled=!next;
  nextBtn.textContent=next ? "執行下一步："+next.label : "已全部完成";
  nextBtn.onclick=()=>confirmNextStage(task.id);

  document.querySelectorAll("[data-open-review-inline]").forEach(btn=>{
    btn.addEventListener("click",()=>openTaskReview(btn.dataset.openReviewInline));
  });

  document.querySelectorAll("[data-detail-stage]").forEach(btn=>{
    btn.addEventListener("click",()=>{
      const index=Number(btn.dataset.detailStage);
      const stage=workflow[index];
      if(["polish","review"].includes(stage.key)){
        openTaskReview(task.id);
      }
    });
  });
}

function openTaskDetail(taskId){
  selectedTaskId=taskId;
  const task=tasks.find(x=>x.id===taskId);
  if(!task) return;
  renderTaskDetail(task);
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
    !q||[t.name,t.category,t.aliases,t.description].join(" ").toLowerCase().includes(q)
  );

  document.getElementById("term-body").innerHTML=rows.map(t=>
    '<tr>'+
      '<td><b>'+escapeHtml(t.name)+'</b></td>'+
      '<td>'+escapeHtml(t.category)+'</td>'+
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

  endpointInput.value=localStorage.getItem(BRIDGE_ENDPOINT_KEY) || "";
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

    const form=document.createElement("form");
    form.method="POST";
    form.action=endpoint;
    form.target="soulkey-bridge-target";
    form.style.display="none";

    const fields={
      action:"smoke",
      bridge_key:key
    };

    for(const [name,value] of Object.entries(fields)){
      const input=document.createElement("input");
      input.type="hidden";
      input.name=name;
      input.value=value;
      form.appendChild(input);
    }

    document.body.appendChild(form);
    testButton.disabled=true;
    setBridgeStatus("正在送出網頁 → GitHub → Kaggle 測試…","sending");
    form.submit();

    window.setTimeout(()=>{
      form.remove();
      testButton.disabled=false;
      setBridgeStatus(
        "測試已送出。現在到 GitHub Actions 查看是否自動出現新的「Kaggle Run Bridge Test」。",
        "sent"
      );
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
pingBackend();

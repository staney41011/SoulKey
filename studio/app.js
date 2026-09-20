const cfg = window.SOULKEY_CONFIG || {};
const STORE = {
  tasks: "soulkey_studio_tasks_v1",
  terms: "soulkey_studio_terms_v1",
  gpu: "soulkey_studio_gpu_v1"
};

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
].map((x,i)=>({id:"seed-"+i,name:x[0],category:x[1],aliases:x[2],description:"",status:"正式詞庫"}));

const pipeline = [
  ["01","來源資訊","免 GPU","ready"],
  ["02","ASR 辨識","GPU 工作","ready"],
  ["03","AI 中文校稿","GPU 工作","ready"],
  ["04","人工確認","網頁操作","ready"],
  ["05","多語翻譯","中文定稿後","locked"],
  ["06","字幕","翻譯後","locked"],
  ["07","TTS","GPU 工作","locked"],
  ["08","完成影片","最後階段","locked"]
];

function load(key, fallback){
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function save(key, value){ localStorage.setItem(key, JSON.stringify(value)); }
let tasks = load(STORE.tasks, []);
let terms = load(STORE.terms, seedTerms);
if(!localStorage.getItem(STORE.terms)) save(STORE.terms, terms);

const titles = {
  dashboard:"任務總覽", "new-task":"建立任務", review:"中文逐字稿校稿",
  glossary:"專有名詞庫", knowledge:"經典知識庫", system:"系統狀態"
};

function showView(name){
  document.querySelectorAll(".view").forEach(x=>x.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(x=>x.classList.toggle("active",x.dataset.view===name));
  document.getElementById("view-"+name).classList.add("active");
  document.getElementById("view-title").textContent=titles[name]||"SoulKey Studio";
}
document.querySelectorAll("[data-view]").forEach(b=>b.addEventListener("click",()=>showView(b.dataset.view)));
document.querySelectorAll("[data-go]").forEach(b=>b.addEventListener("click",()=>showView(b.dataset.go)));

function renderPipeline(){
  document.getElementById("pipeline").innerHTML=pipeline.map(x=>
    '<div class="step '+x[3]+'"><span>STEP '+x[0]+'</span><b>'+x[1]+'</b><small>'+x[2]+'</small></div>'
  ).join("");
}

function renderTasks(){
  const el=document.getElementById("task-list");
  if(!tasks.length){
    el.innerHTML='<div class="empty">尚無任務。先到「建立任務」貼入 YouTube 網址。</div>';
  }else{
    el.innerHTML=tasks.slice().reverse().map(t=>
      '<div class="task-row"><b>'+escapeHtml(t.id)+'</b><div><strong>第'+t.period+'期・'+escapeHtml(t.lesson)+'</strong><br><span class="muted">'+escapeHtml(t.url)+'</span></div><span class="badge">'+escapeHtml(t.stage)+'</span><span class="muted">'+new Date(t.createdAt).toLocaleString("zh-TW")+'</span></div>'
    ).join("");
  }
  document.getElementById("stat-tasks").textContent=tasks.length;
  document.getElementById("stat-terms").textContent=terms.length;
}

function escapeHtml(s){
  return String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));
}

document.getElementById("task-form").addEventListener("submit", async e=>{
  e.preventDefault();
  const url=document.getElementById("youtube-url").value.trim();
  const period=Number(document.getElementById("period").value);
  const lesson=document.getElementById("lesson").value;
  const note=document.getElementById("task-note").value.trim();
  const id='P'+period+'-L'+String(parseInt(lesson.replace(/\D/g,""))).padStart(2,"0")+'-'+Date.now().toString().slice(-5);
  const task={id,url,period,lesson,note,stage:cfg.apiBaseUrl?"queued":"前端草稿",createdAt:new Date().toISOString()};
  if(cfg.apiBaseUrl){
    try{
      const r=await fetch(cfg.apiBaseUrl.replace(/\/$/,"")+"/jobs",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(task)});
      if(!r.ok) throw new Error("API "+r.status);
      const data=await r.json();
      task.id=data.jobId||task.id; task.stage=data.status||"queued";
    }catch(err){
      alert("後端送出失敗，已保留為本機草稿："+err.message);
      task.stage="本機草稿";
    }
  }
  tasks.push(task); save(STORE.tasks,tasks); renderTasks();
  e.target.reset(); document.getElementById("period").value=period;
  showView("dashboard");
});

function renderTerms(filter=""){
  const q=filter.trim().toLowerCase();
  const rows=terms.filter(t=>!q||[t.name,t.category,t.aliases,t.description].join(" ").toLowerCase().includes(q));
  document.getElementById("term-body").innerHTML=rows.map(t=>
    '<tr><td><b>'+escapeHtml(t.name)+'</b></td><td>'+escapeHtml(t.category)+'</td><td>'+escapeHtml(t.aliases||"—")+'</td><td><span class="badge">'+escapeHtml(t.status||"正式詞庫")+'</span></td><td><button class="mini term" data-delete-term="'+escapeHtml(t.id)+'">刪除</button></td></tr>'
  ).join("");
  document.querySelectorAll("[data-delete-term]").forEach(b=>b.addEventListener("click",()=>{
    if(!confirm("刪除這個本機詞彙？"))return;
    terms=terms.filter(t=>t.id!==b.dataset.deleteTerm); save(STORE.terms,terms); renderTerms(document.getElementById("term-search").value); renderTasks();
  }));
}
document.getElementById("term-search").addEventListener("input",e=>renderTerms(e.target.value));
const dlg=document.getElementById("term-dialog");
document.getElementById("add-term").addEventListener("click",()=>dlg.showModal());
document.getElementById("save-term").addEventListener("click",e=>{
  const form=document.getElementById("term-form");
  if(!form.reportValidity()){e.preventDefault();return;}
  const t={id:"term-"+Date.now(),name:document.getElementById("term-name").value.trim(),category:document.getElementById("term-category").value,aliases:document.getElementById("term-aliases").value.trim(),description:document.getElementById("term-description").value.trim(),status:"正式詞庫"};
  terms.push(t);save(STORE.terms,terms);renderTerms();renderTasks();form.reset();
});

const demoSegments=[
  {time:"08:20",raw:"尤其是白楊棋裡面更是為法律主",text:"尤其是白陽期裡面更是為關法律主",flags:["changed"]},
  {time:"08:51",raw:"老母慈悲！暗猜鮮活！來跟你指點迷津",text:"老母慈悲！暗猜鮮活！來跟你指點迷津",flags:["uncertain"]},
  {time:"16:07",raw:"我們聽過一句成語叫做學護五車",text:"我們聽過一句成語叫做學富五車",flags:["changed"]},
  {time:"26:10",raw:"大家要扮演上善若水！胡園補缺就對了",text:"大家要扮演上善若水！扶圓補缺就對了",flags:["changed"]}
];

function renderSegments(items){
  const el=document.getElementById("segment-list");
  el.innerHTML=items.map((s,i)=>
    '<div class="segment '+s.flags.join(" ")+'" data-segment="'+i+'"><div class="segment-meta"><span>'+s.time+'</span><span>'+s.flags.map(x=>x==="uncertain"?"⚠ 待人工確認":"AI 已修改").join(" · ")+'</span></div><div class="muted">ASR：'+escapeHtml(s.raw)+'</div><textarea>'+escapeHtml(s.text)+'</textarea><div class="segment-actions"><button class="mini term">加入詞庫</button><button class="mini confirm">確認此句</button></div></div>'
  ).join("");
  document.getElementById("stat-uncertain").textContent=items.filter(x=>x.flags.includes("uncertain")).length;
  document.querySelectorAll(".segment").forEach(seg=>seg.addEventListener("click",()=>{document.getElementById("current-time").textContent=demoSegments[Number(seg.dataset.segment)]?.time||"--:--";}));
}
document.getElementById("load-demo").addEventListener("click",()=>renderSegments(demoSegments));
document.querySelectorAll("[data-filter]").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll("[data-filter]").forEach(x=>x.classList.toggle("active",x===b));
  const f=b.dataset.filter; renderSegments(f==="all"?demoSegments:demoSegments.filter(x=>x.flags.includes(f)));
}));
document.getElementById("finalize-zh").addEventListener("click",()=>alert("正式版會先檢查所有『待人工確認』是否清空，再鎖定中文版本並開放五語翻譯。"));

async function pingBackend(){
  if(!cfg.apiBaseUrl)return;
  try{
    const r=await fetch(cfg.apiBaseUrl.replace(/\/$/,"")+"/health");
    if(!r.ok)throw new Error();
    document.getElementById("backend-text").textContent="後端已連線";
    document.querySelector(".backend-pill .status-dot").style.background="#56b981";
    document.getElementById("api-state").textContent="已連線";
    document.getElementById("api-state").className="ok";
  }catch{
    document.getElementById("backend-text").textContent="後端離線";
  }
}

renderPipeline();renderTasks();renderTerms();pingBackend();

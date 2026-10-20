const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
global.SoulKeyTTSShare=require("../tts-share-message.js");
const api=require("../language-delivery.js");
const root=path.resolve(__dirname,"..");
function file(name,props={}){
  const id=props.id||"1AbcdeFGHijKlMNO123456";
  return {id,name,canonical_name:name,url:"https://drive.google.com/file/d/"+id+"/view",size:1045,...props};
}
const doc=file("th.final.txt");
const english=file("en.final.txt");
const audio=file("th.mp3");
const preview=file("hi.preview.mp3",{needs_timing_review:true,audio_kind:"standalone_preview"});
const videoRecording=file("youtube.en.mp3");
const payload={ok:true,groups:[
 {key:"transcript",files:[doc,english]},
 {key:"audio",files:[audio,preview,videoRecording]}
]};
const task={id:"P258-L02",remoteStages:{tts:{status:"done"},"tts:th":{status:"done"}}};
let actual=api.resolve(task,"th",payload,null);
assert.equal(actual.doc.status,"ready");
assert.equal(actual.doc.label,"開啟定稿");
assert.equal(actual.audio.status,"ready");
assert.equal(actual.audio.label,"開啟正式 MP3");
actual=api.resolve(task,"en",payload,null);
assert.equal(actual.doc.status,"ready");
assert.equal(actual.audio.status,"pending","YouTube reference audio is not formal narration");
actual=api.resolve(task,"hi",payload,null);
assert.equal(actual.audio.status,"review");
assert.equal(actual.audio.label,"開啟試聽 MP3");
assert.match(actual.audio.url,/drive.google.com/);
assert.ok(actual.audio.reason.includes("試聽"),"Preview is not formal-ready");
actual=api.resolve(task,"ko",payload,null);
assert.equal(actual.audio.label,"待產生","Unrelated language preview must not contaminate status");
actual=api.resolve({remoteStages:{tts:{status:"needs_review"},"tts:th":{status:"needs_review"}}},"th",payload,null);
assert.equal(actual.audio.status,"pending");
assert.match(actual.audio.label,/待驗收/,"No approved preview: do not mislabel old official MP3");
const thPreview=file("th.preview.mp3",{needs_timing_review:true,audio_kind:"standalone_preview"});
actual=api.resolve({remoteStages:{tts:{status:"needs_review"},
 "tts:th":{status:"needs_review",message:"自然長度=3610.0s，影片上限=3500.0s"}}},"th",
 {ok:true,groups:[{key:"audio",files:[audio,thPreview]}]},null);
assert.equal(actual.audio.status,"review","Prefer newer preview over old official MP3");
assert.ok(actual.audio.url.includes(thPreview.id));
assert.match(actual.audio.reason,/超出 1分50秒/);
actual=api.resolve({remoteStages:{tts:{status:"stale"}}},"th",payload,null);
assert.equal(actual.audio.status,"pending","Stale aggregate must block formal-ready");
actual=api.resolve(task,"th",null,null);
assert.equal(actual.doc.label,"尚未查詢");
assert.equal(actual.audio.label,"尚未查詢");
actual=api.resolve(task,"th",null,{ok:true,groups:[{key:"audio",files:[audio]}]});
assert.equal(actual.audio.status,"ready","Lightweight audio lookup may show available formal MP3");
assert.equal(actual.doc.label,"尚未查詢","Lightweight audio lookup cannot attest a document");
actual=api.resolve(task,"th",{ok:true,groups:[
 {key:"transcript",files:[file("th.final.txt",{url:"https://evil.example/file/d/1AbcdeFGHijKlMNO123456/view"})]}
]},null);
assert.equal(actual.doc.status,"pending","Reject untrusted links");
const html=fs.readFileSync(path.join(root,"index.html"),"utf8");
const main=fs.readFileSync(path.join(root,"app-20260923-48.js"),"utf8");
const css=fs.readFileSync(path.join(root,"styles.css"),"utf8");
for(const id of ["language-delivery-refresh","language-plan-expand","language-plan-list",
"tts-share-toggle","tts-share-content","course-files-toggle","course-files-body",
"save-language-plan","tts-share-copy","course-files-folder-link"]){
  assert.ok(html.includes('id="'+id+'"'),id+" exists");
}
assert.ok(html.indexOf("language-delivery.js")<html.indexOf("app-20260923-48.js"));
assert.ok(main.includes("refreshLanguageDeliveryStatus(selected)"));
assert.ok(main.includes("requestCourseFiles(task.id,true)"));
assert.ok(main.includes("requestTtsShareLinks(task.id,true)"));
assert.ok(!/openTaskDetail\(taskId\)\{[\s\S]*?requestCourseFiles\(task\.id\)/.test(
  main.slice(main.indexOf("function openTaskDetail("),main.indexOf("let zhVideoFloatFrame"))
),"Do not scan all Drive folders immediately on task open");
assert.ok(css.includes(".language-plan-row:nth-child(n+7){display:none}"));
assert.ok(css.includes("@media(max-width:650px)"));
assert.ok(html.includes('id="tts-share-content" hidden'));
assert.ok(html.includes('id="course-files-body" class="course-files-body" hidden'));
console.log("SOULKEY_COMPACT_LANGUAGE_OUTPUTS_OK");

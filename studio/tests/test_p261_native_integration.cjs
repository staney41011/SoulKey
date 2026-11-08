const fs=require("fs"),vm=require("vm"),assert=require("assert");
const path=require("path");
const root=path.join(__dirname,"..","..");
const script=fs.readFileSync(path.join(root,"studio/native-pipeline.js"),"utf8");
const html=fs.readFileSync(path.join(root,"studio/index.html"),"utf8");
const app=fs.readFileSync(path.join(root,"studio/app-20260923-48.js"),"utf8");
const code=fs.readFileSync(path.join(root,"bridge/apps-script/Code.gs"),"utf8");
const next=fs.readFileSync(path.join(root,"bridge/apps-script/NativeNext.gs"),"utf8");
const qa=fs.readFileSync(path.join(root,"bridge/apps-script/NativeQuality.gs"),"utf8");
const audio=fs.readFileSync(path.join(root,"bridge/apps-script/NativeAudio.gs"),"utf8");
assert(html.includes("native-pipeline.js?v=20261108"));
assert(html.includes('id="native-pipeline-panel"'));
assert(app.includes('window.SoulKeyNativeUI?.render(task,'));
assert(app.includes('["multi","tts"].includes(next.key)'));
assert(app.includes('action:"glossary_upsert"'));
assert(app.includes('jsonpBridgeRequest({action:"glossary_list"})'));
assert(code.includes("p261_native_pipeline_only"));
assert(code.includes('action === "native_pipeline_get"'));
assert(code.includes('action === "period_latest"'));
assert(code.includes('action === "native_manual_review_save"'));
assert(code.includes('"native_pipeline_get"'));
assert(code.includes('["en","th","es","id","vi","hi","ta","ja"'));
for(const text of [next,qa,audio])
  assert(text.includes('soulkeyNextSelectedCodes_'),"language-plan selection must reach all pipelines");
assert(audio.includes('sheets.native_tts.'));
let listeners={},requests=[],panel={
  hidden:true,dataset:{},addEventListener(){},scrollIntoView(){}
};
const fields={
  "native-pipeline-panel":panel,
  "native-pipeline-heading":{textContent:""},
  "native-pipeline-summary":{textContent:""},
  "native-pipeline-blockers":{textContent:""},
  "native-pipeline-rows":{innerHTML:""},
  "period":{value:"260"}
};
const ctx={
  window:{
    addEventListener:(type,cb)=>(listeners[type]??=[]).push(cb),
    prompt:()=>null,confirm:()=>false,alert:()=>{}
  },
  document:{
    getElementById:k=>fields[k]||null,
    querySelectorAll:()=>[]
  },
  console
};
vm.runInNewContext(script,ctx);
assert(ctx.window.SoulKeyNativeUI.isNative({period:261}));
assert(!ctx.window.SoulKeyNativeUI.isNative({period:260}));
ctx.window.SoulKeyNativeUI.render({id:"P261-L01",period:261},{
  request:p=>(requests.push(p),true),submit:()=>true
});
assert(!panel.hidden);
assert.deepEqual(JSON.parse(JSON.stringify(requests[0])),
  {action:"native_pipeline_get",task_id:"P261-L01"});
const respond=data=>(listeners.message||[]).forEach(cb=>cb({data}));
respond({source:"soulkey-bridge",type:"period_latest",ok:true,period:261});
assert.equal(fields.period.value,"261");
respond({
 source:"soulkey-bridge",type:"native_pipeline_status",
 task_id:"P261-L01",ok:true,english_final_ready:true,
 translation_done:1,translation_required:1,qa_done:1,qa_required:1,
 audio_done:2,audio_required:2,can_publish:true,
 languages:[{lang:"es",translation_count:1,translation_total:1,
 qa_state:"approved_risk_based",audio_state:"done",
 audio_url:"https://drive.google.com/file/d/abc/view",
 draft_text_url:"https://drive.google.com/file/d/drafttxt/view",
 draft_file_url:"https://drive.google.com/file/d/draftjson/view",
 qa_report_url:"https://drive.google.com/file/d/qareport/view",
 review_items:[]}]
});
assert(fields["native-pipeline-summary"].textContent.includes("1/1"));
assert(fields["native-pipeline-rows"].innerHTML.includes("正式 MP3"));
assert(fields["native-pipeline-rows"].innerHTML.includes("下載文字草稿"));
assert(fields["native-pipeline-rows"].innerHTML.includes("QA 報告"));
respond({
 source:"soulkey-bridge",type:"native_pipeline_status",
 task_id:"P261-L01",ok:true,english_final_ready:true,
 translation_done:1,translation_required:1,qa_done:0,qa_required:1,
 audio_done:0,audio_required:1,can_publish:false,
 blockers:["es: QA 未通過","es: 配音需驗收"],
 languages:[{lang:"es",translation_count:1,translation_total:1,
 qa_state:"needs_review",audio_state:"needs_review",
 draft_text_url:"https://drive.google.com/file/d/drafttxt/view",
 draft_file_url:"https://drive.google.com/file/d/draftjson/view",
 qa_report_url:"https://drive.google.com/file/d/qareport/view",
 preview_audio_url:"https://drive.google.com/file/d/unverifiedmp3/view",
 preview_audio_label:"配音試聽檔（未驗收）",review_items:[]}]
});
assert(fields["native-pipeline-rows"].innerHTML.includes("unverifiedmp3"));
assert(fields["native-pipeline-rows"].innerHTML.includes("下載文字草稿"));
assert(fields["native-pipeline-rows"].innerHTML.includes("QA 報告"));
assert(fields["native-pipeline-blockers"].textContent.includes("尚不能正式發布"));

console.log("PASS Studio P261 native status, 261 period default, 16 audio lookup and dispatch guards");

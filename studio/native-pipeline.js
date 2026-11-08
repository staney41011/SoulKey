/* SoulKey Studio P261+ Sheets/Gemma4/private-TTS authoritative UI.
 * No secrets are stored here: all reads use the authenticated Bridge session.
 */
(function(root){
  "use strict";
  const LANG={en:"英文",th:"泰文",es:"西班牙文",id:"印尼文",
    vi:"越南文",hi:"印地語",ta:"泰米爾文",ja:"日文",ko:"韓文",
    km:"高棉文",bn:"孟加拉文",ne:"尼泊爾文",lo:"寮文",
    my:"緬甸文",it:"義大利文",pt:"葡萄牙文"};
  const last=new Map(),lastRequested=new Map();
  let activePeriod=0,request=null,submit=null;
  function escape(value){
    return String(value??"").replace(/[&<>"']/g,ch=>({
      "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
    })[ch]);
  }
  function isNative(task){
    return !!task && Number(task.period)>=261;
  }
  function qaText(item){
    if(item.lang==="en")return "英文定稿";
    const m={
      pending_translation:"待 Sheets 初譯",
      pending_qa:"等待 Gemma 4",
      stale_qa:"原文或詞庫已更新，需重審",
      needs_review:"待 QA／人工確認",
      approved_risk_based:"風險式 QA 通過",
      draft_revision_error:"初譯版本不一致"
    };
    const base=m[item.qa_state]||String(item.qa_state||"未開始");
    return base+(item.qa_required?
      " "+item.qa_reviewed+"/"+item.qa_required+" 段":"");
  }
  function audioText(item){
    return ({pending:"尚未派工",pending_source:"等待譯稿",queued:"配音佇列中",
      done:"正式 MP3 通過",needs_review:"試聽版：時長待修",
      stale_audio:"舊版音檔，需重製",error:"配音出錯",
      not_selected:"不產生配音"})[item.audio_state]||String(item.audio_state||"未開始");
  }
  function getStatus(taskId){return last.get(String(taskId))||null;}
  function refresh(taskId,force=false){
    const id=String(taskId||"");
    if(!/^P\d+-L\d+$/.test(id)||typeof request!=="function")return false;
    const now=Date.now();
    if(!force && now-(lastRequested.get(id)||0)<45000)return false;
    lastRequested.set(id,now);
    return !!request({action:"native_pipeline_get",task_id:id});
  }
  function render(task,transport){
    const panel=document.getElementById("native-pipeline-panel");
    if(!panel)return;
    panel.hidden=!isNative(task);
    if(!isNative(task))return;
    if(transport){
      request=transport.request||request;
      submit=transport.submit||submit;
    }
    panel.dataset.nativeTask=task.id;
    draw(task.id);
    refresh(task.id);
  }
  function draw(taskId){
    const panel=document.getElementById("native-pipeline-panel");
    if(!panel || panel.hidden||panel.dataset.nativeTask!==taskId)return;
    const info=last.get(taskId);
    const header=document.getElementById("native-pipeline-heading");
    const summary=document.getElementById("native-pipeline-summary");
    const rows=document.getElementById("native-pipeline-rows");
    const blocker=document.getElementById("native-pipeline-blockers");
    if(!info){
      if(header)header.textContent="第 261 期起使用新版自動翻譯／配音";
      if(summary)summary.textContent="取得中央控制中心的逐語言進度中。英文定稿後由內部排程自動接手，不需要按舊版多語翻譯。";
      if(rows)rows.innerHTML="";
      if(blocker)blocker.textContent="";
      return;
    }
    if(!info.ok){
      if(summary)summary.textContent="無法讀取最新驗收結果："+(info.error||"未知原因");
      if(rows)rows.innerHTML="";
      return;
    }
    if(header)header.textContent=info.can_publish?
      "已達風險式 QA＋音檔版本驗收條件":"新版 Sheets／Gemma 4／配音進行中";
    if(summary)summary.textContent= !info.english_final_ready?
      "等待英文人工定稿。中文及英文定稿仍由原本的網頁流程進行。":
      "初譯 "+info.translation_done+"/"+info.translation_required+
      " 語｜Gemma 4 QA "+info.qa_done+"/"+info.qa_required+
      " 語｜正式音檔 "+info.audio_done+"/"+info.audio_required+
      " 語。品質審核為「風險段落＋抽樣」，不是全文逐段語意驗收。";
    if(blocker)blocker.textContent=info.can_publish?
      "所有已選語言的文字與正式 MP3 版本一致，可進行下一步人工發布確認。":
      ((info.blockers||[]).length?
        "尚不能正式發布："+info.blockers.slice(0,5).join("；")+
        (info.blockers.length>5?"；另有 "+(info.blockers.length-5)+" 項":""):
        "已啟用自動排程，等待來源或配音進度");
    if(rows){
      rows.innerHTML=(info.languages||[]).map(item=>{
        const snippet=(item.review_items||[]).map(sid=>
          '<div class="native-review-item"><small>第 '+escape(sid.id)+
          ' 段｜'+escape(sid.grade)+'｜'+escape(sid.reason)+'</small>'+
          '<p>英文：'+escape(sid.english)+'</p>'+
          '<p>初譯：'+escape(sid.translation)+'</p>'+
          (item.qa_revision ?
          '<button type="button" class="ghost" data-native-manual="'+
          escape(item.lang)+":"+escape(sid.id)+'">人工確認／修改這段</button>':
          "")+'</div>').join("");
        const artifacts=[];
        // Review failure never removes generated output. Links do not
        // imply approval or video-synchronized audio.
        if(item.draft_text_url)artifacts.push(
          '<a href="'+escape(item.draft_text_url)+
          '" target="_blank" rel="noopener noreferrer">下載文字草稿</a>');
        if(item.draft_file_url)artifacts.push(
          '<a href="'+escape(item.draft_file_url)+
          '" target="_blank" rel="noopener noreferrer">'+
          escape(item.draft_file_label||"初譯 JSON（未驗收）")+'</a>');
        if(item.qa_report_url)artifacts.push(
          '<a href="'+escape(item.qa_report_url)+
          '" target="_blank" rel="noopener noreferrer">下載 QA 報告</a>');
        const link=item.audio_url?
          '<a href="'+escape(item.audio_url)+
          '" target="_blank" rel="noopener noreferrer">正式 MP3</a>':"";
        const preview=item.preview_audio_url?
          '<a href="'+escape(item.preview_audio_url)+
          '" target="_blank" rel="noopener noreferrer">'+
          escape(item.preview_audio_label||"配音試聽檔（未驗收）")+'</a>':"";
        const classroom=item.classroom_copy_url?
          '<a href="'+escape(item.classroom_copy_url)+
          '" target="_blank" rel="noopener noreferrer">'+
          (item.classroom_copy_tier==="formal"?
            "課堂播放副本":"課堂試聽副本（待驗收）")+
          '</a>':"";
        const classroomNote=!item.classroom_copy_url &&
          ["done","needs_review"].includes(item.audio_state)?
          '<small>課堂播放副本'+
          (item.classroom_copy_state==="retry"?"同步失敗，排程會重試":"同步中")+
          '</small>':"";
        const sourceFile=item.tts_source_url?
          '<a href="'+escape(item.tts_source_url)+
          '" target="_blank" rel="noopener noreferrer">TTS source JSON</a>':"";
        return '<tr><td><b>'+escape(LANG[item.lang]||item.lang)+
          '</b><small> '+escape(item.lang)+'</small></td>'+
          '<td>'+escape(item.translation_count||0)+"/"+
          escape(item.translation_total||0)+'</td>'+
          '<td>'+escape(qaText(item))+
          (artifacts.length?'<div class="native-artifacts">'+artifacts.join(" · ")+'</div>':"")+
          (snippet?'<details class="native-review-details"><summary>查看待確認段落</summary>'+
           snippet+'</details>':"")+'</td>'+
          '<td>'+escape(audioText(item))+
          (link?'<div class="native-artifacts">'+link+'</div>':"")+
          (preview?'<div class="native-artifacts">'+preview+'</div>':"")+
          (classroom?'<div class="native-artifacts">'+classroom+'</div>':"")+
          classroomNote+
          (sourceFile?'<div class="native-artifacts">'+sourceFile+'</div>':"")+
          (item.audio_issue?'<small>'+escape(item.audio_issue)+'</small>':"")+
          '</td></tr>';
      }).join("");
    }
    decorateLanguageRows(taskId);
  }
  function decorateLanguageRows(taskId){
    const data=last.get(taskId);
    if(!data||!data.ok || !document.getElementById("native-pipeline-panel") ||
       document.getElementById("native-pipeline-panel").dataset.nativeTask!==taskId)return;
    const byCode=Object.fromEntries((data.languages||[]).map(x=>[x.lang,x]));
    document.querySelectorAll(".language-plan-row").forEach(row=>{
      const item=byCode[row.dataset.langPlan];
      if(!item)return;
      const doc=row.querySelector('[data-lang-delivery="doc"]');
      const audio=row.querySelector('[data-lang-delivery="audio"]');
      if(doc){
        doc.replaceChildren();
        doc.appendChild(document.createTextNode(item.lang==="en"?"英文人工定稿":
          "Sheets "+item.translation_count+"/"+item.translation_total+
          "｜"+qaText(item)+" "));
        for(const [url,label] of [
          [item.draft_text_url,"草稿 TXT"],
          [item.draft_file_url,"草稿 JSON"],
          [item.qa_report_url,"QA 報告"]
        ]){
          if(!url)continue;
          const link=document.createElement("a");
          link.href=url;link.target="_blank";link.rel="noopener noreferrer";
          link.textContent=label+(item.qa_state!=="approved_risk_based"?"（未驗收）":"");
          doc.appendChild(link);
        }
      }
      if(audio){
        audio.replaceChildren();
        if(item.audio_url && item.audio_state==="done"){
          const a=document.createElement("a");
          a.href=item.audio_url;a.target="_blank";a.rel="noopener noreferrer";
          a.textContent=item.lang!=="en" && item.qa_state!=="approved_risk_based"?
            "MP3（QA 未通過，僅供預覽）":"正式 MP3（已核對版本）";
          audio.appendChild(a);
        }else if(item.preview_audio_url){
          const link=document.createElement("a");
          link.href=item.preview_audio_url;link.target="_blank";
          link.rel="noopener noreferrer";
          link.textContent=item.preview_audio_label||"試聽 MP3（未驗收）";
          audio.appendChild(link);
        }else audio.textContent=audioText(item);
        if(item.classroom_copy_url){
          const classroomLink=document.createElement("a");
          classroomLink.href=item.classroom_copy_url;
          classroomLink.target="_blank";classroomLink.rel="noopener noreferrer";
          classroomLink.textContent=item.classroom_copy_tier==="formal"?
            "課堂播放副本":"課堂試聽副本（待驗收）";
          audio.appendChild(classroomLink);
        }
        if(item.tts_source_url){
          const sourceLink=document.createElement("a");
          sourceLink.href=item.tts_source_url;
          sourceLink.target="_blank";sourceLink.rel="noopener noreferrer";
          sourceLink.textContent="TTS source JSON";
          audio.appendChild(sourceLink);
        }
      }
    });
  }
  function openManual(lang,segmentId){
    const panel=document.getElementById("native-pipeline-panel");
    const task=panel?.dataset.nativeTask;
    const info=last.get(task);
    const item=info?.languages?.find(x=>x.lang===lang);
    const segment=item?.review_items?.find(x=>Number(x.id)===Number(segmentId));
    if(!segment||!item.qa_revision)return;
    const proposed=root.prompt(
      "請對照英文及原譯文，填入確認後的完整 "+(LANG[lang]||lang)+" 翻譯。\n\n"+
      "英文："+segment.english+"\n原譯："+segment.translation+
      "\n\n若尚無法確認，請取消並保留待審。",
      segment.translation);
    if(proposed===null)return;
    const corrected=proposed.trim();
    if(corrected.length<4){
      root.alert("確認後的譯文不可為空，資料未送出。");return;
    }
    if(!root.confirm("確定以人工審稿結果取代第 "+segment.id+
      " 段譯文？版本會被記錄，必要時只重新配音受影響區塊。"))return;
    if(typeof submit!=="function" || !submit({
      action:"native_manual_review_save",task_id:task,lang:lang,
      segment_id:String(segment.id),corrected_text:corrected,
      revision_key:item.qa_revision})){
      root.alert("未連接中央控制中心，修改沒有送出。");
    }else{
      const note=document.getElementById("native-pipeline-blockers");
      if(note)note.textContent="人工確認已送出，請待中央寫入確認後重新整理狀態。";
    }
  }
  root.addEventListener("message",e=>{
    const data=e.data||{};
    if(data.source!=="soulkey-bridge")return;
    if(data.type==="native_pipeline_status" && data.task_id){
      last.set(data.task_id,data);
      draw(data.task_id);
    }
    if(data.type==="period_latest" && data.ok){
      activePeriod=Number(data.period)||activePeriod;
      const periodField=document.getElementById("period");
      if(periodField && (!periodField.value ||
           Number(periodField.value)<activePeriod))
        periodField.value=String(activePeriod);
      root.SOULKEY_NATIVE_LATEST_PERIOD=activePeriod;
    }
    if(data.type==="native_manual_review_result"){
      root.alert(data.ok?
        "第 "+data.id+" 段已保存人工 QA 修正。配音會在排程中重新核對版本。":
        "人工修正未保存："+(data.error||"未知錯誤"));
      if(data.task_id)refresh(data.task_id,true);
    }
  });
  root.addEventListener("click",e=>{
    const target=e.target.closest?.("[data-native-refresh],[data-native-manual]");
    if(!target)return;
    if(target.hasAttribute("data-native-refresh")){
      const task=document.getElementById("native-pipeline-panel")?.dataset.nativeTask;
      if(task)refresh(task,true);
    }
    if(target.hasAttribute("data-native-manual")){
      const [lang,id]=String(target.dataset.nativeManual).split(":");
      openManual(lang,id);
    }
  });
  root.SoulKeyNativeUI={
    isNative,render,refresh,getStatus,decorateLanguageRows,
    requestPeriod(fn){request=fn||request;return !!request?.({action:"period_latest"});},
    get latestPeriod(){return activePeriod;},
    init(requestFn,submitFn){request=requestFn;submit=submitFn;}
  };
})(window);

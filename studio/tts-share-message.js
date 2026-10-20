/* SoulKey – per-lesson, copyable TTS sharing text.
 * Pure formatter: source of links is the Drive-backed course_files response,
 * NOT guessed URL paths, youtube.* downloads, or preview MP3s.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.SoulKeyTTSShare = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  // Public sharing is intentionally limited to the six requested languages.
  // Other languages remain available in the translation/TTS pipeline.
  const LANGUAGES = Object.freeze([
    {code:"en",label:"🇬🇧 English 英語"},
    {code:"es",label:"🇪🇸 Español 西班牙語"},
    {code:"th",label:"🇹🇭 ภาษาไทย 泰語"},
    {code:"id",label:"🇮🇩 Bahasa Indonesia 印尼語"},
    {code:"km",label:"🇰🇭 ភាសាខ្មែរ 高棉語"},
    {code:"vi",label:"🇻🇳 Tiếng Việt 越南語"}
  ]);
  const LOOKUP = Object.fromEntries(LANGUAGES.map(l => [l.code,l]));

  function lessonNumber(task) {
    const fromId=/^P\d+-L(\d+)/i.exec(String(task?.id || ""));
    if (fromId) return Number(fromId[1]) || 0;
    const match=/(\d+)/.exec(String(task?.lesson || ""));
    return match ? Number(match[1]) : 0;
  }
  function titleInfo(task) {
    const raw=String(task?.title || "").trim();
    const parts=raw.split(/\s*[丨|｜]\s*/).map(s => s.trim()).filter(Boolean);
    const chinese=parts.length ? parts[0] : String(task?.lesson || "課程");
    // The schedule's lecturer field may identify the publishing channel
    // (e.g. "白陽文化") rather than the actual speaker.
    const namedSpeaker=parts.length > 1 && !/打開心靈的鎖匙|^\d+期$/.test(parts[1])
      ? parts[1] : "";
    const lecturer=namedSpeaker || (
      /^(白陽文化|未知|未提供|無)$/i.test(String(task?.lecturer||"").trim())
        ? "" : String(task?.lecturer || "").trim()
    );
    const english=String(task?.english_title || task?.title_en || "").trim();
    return {chinese, lecturer, english};
  }
  function canonicalMp3Code(file) {
    const canonical=String(file?.canonical_name || "").trim();
    // A canonical name takes priority over the pretty display filename.
    // Do not infer authenticity from a localized display_name.
    const name=canonical || String(file?.name || "").trim();
    const match=/^([a-z]{2})\.mp3$/i.exec(name);
    if(match && !file?.needs_timing_review) return match[1].toLowerCase();
    const preview=/^([a-z]{2})\.preview\.mp3$/i.exec(name);
    if(preview && file?.needs_timing_review &&
        file?.audio_kind==="standalone_preview") return preview[1].toLowerCase();
    // Historical Drive uploads use the fully localized official filename.
    // Only accept the exact full-length "TTS音檔.mp3" suffix; previews,
    // Youtube source recordings, WAVs and generic MP3s are excluded.
    if(canonical) return "";
    const labels={
      "英文":"en","泰文":"th","西班牙文":"es","印尼文":"id",
      "越南文":"vi","印地語":"hi","信德文":"hi",
      "泰米爾文":"ta","日文":"ja","韓文":"ko","高棉文":"km",
      "孟加拉文":"bn","尼泊爾文":"ne","寮文":"lo",
      "緬甸文":"my","義大利文":"it","葡萄牙文":"pt"
    };
    const formal=/_([^_]+)TTS音檔\.mp3$/u.exec(name);
    return formal ? (labels[formal[1]] || "") : "";
  }
  function canonicalDriveUrl(file) {
    const id=String(file?.id || "").trim();
    const url=String(file?.url || "").trim();
    const size=Number(file?.size || 0);
    // Only a nonempty, real Drive file returned by the course_files API is
    // eligible. Never expose previews or youtube-captured source audio.
    if (!/^[A-Za-z0-9_-]{12,}$/.test(id) || !(size > 0)) return "";
    if(file?.needs_timing_review &&
      !(file?.audio_kind==="standalone_preview" &&
        /^[a-z]{2}\.preview\.mp3$/i.test(String(file?.canonical_name||""))))
      return "";
    try {
      const parsed=new URL(url);
      if (parsed.protocol!=="https:" ||
          !["drive.google.com","www.drive.google.com"].includes(parsed.hostname)) return "";
      if (!(parsed.pathname.includes("/file/d/"+id) || parsed.searchParams.get("id")===id)) return "";
    } catch (_) { return ""; }
    return "https://drive.google.com/file/d/"+id+"/view";
  }
  function expectedLanguages() {
    // A shared lesson message always lists this six-language shortlist.
    // Languages without a verified full-length Drive file show pending.
    return LANGUAGES;
  }
  function reviewReason(task,code) {
    const stage=task?.remoteStages?.["tts:"+code]||{};
    const state=String(stage.status||"").toLowerCase();
    const message=String(stage.message||"").trim();
    const timing=/自然長度\s*=\s*([\d.]+)s[^；\n]*[；,，]\s*影片上限\s*=\s*([\d.]+)s/.exec(message);
    function length(sec){
      const whole=Math.max(0,Math.round(Number(sec)||0));
      return Math.floor(whole/60)+"分"+String(whole%60).padStart(2,"0")+"秒";
    }
    if(timing){
      const actual=Number(timing[1]), limit=Number(timing[2]);
      if(Number.isFinite(actual)&&Number.isFinite(limit)&&actual>limit)
        return "自然配音 "+length(actual)+"，影片上限 "+length(limit)+"，超出 "+length(actual-limit);
      return "音檔時長尚未通過驗收（請核對驗收報告）";
    }
    if(/尚未配音|等待.*multi|English Final.*multi/.test(message))
      return "翻譯稿尚未與最新英文定稿同步，配音未完成";
    if(state==="stale") return "課程文稿已更新，音檔版本需要重新確認";
    if(state==="running"||state==="queued") return "最新音檔仍在製作，這是舊試聽檔";
    if(state==="error") return "配音處理失敗，請查執行紀錄後重新驗證";
    if(/超過原片|超過影片|時長驗收/.test(message))
      return "音檔超出原影片時長，尚未符合正式交付標準";
    if(state==="needs_review") return "尚未通過時長或完整性驗收，請查看執行紀錄";
    return "自然語音試聽版，尚未確認符合原影片時長";
  }
  function build(task, courseFilesPayload) {
    const stages=task?.remoteStages || {};
    const audio=(Array.isArray(courseFilesPayload?.groups) ? courseFilesPayload.groups : [])
      .find(group => group && group.key==="audio");
    const files=Array.isArray(audio?.files) ? audio.files : [];
    const fileMap={};
    const present=[];
    files.forEach(file=>{
      const code=canonicalMp3Code(file);
      if(!LOOKUP[code]) return;
      const link=canonicalDriveUrl(file);
      if(link){
        const preview=Boolean(file.needs_timing_review);
        if(!fileMap[code]) fileMap[code]={};
        fileMap[code][preview?"review":"official"]={link,preview};
        if(!present.includes(code)) present.push(code);
      }
    });
    const languages=expectedLanguages(task,stages,present);
    const ttsStatus=String(stages.tts?.status || "").toLowerCase();
    const eligible=present.length>0 ||
      ["done","needs_review"].includes(ttsStatus) ||
      languages.some(l=>["done","needs_review"].includes(String(stages["tts:"+l.code]?.status || "")));
    const period=Number(task?.period) || Number((/^P(\d+)-/i.exec(String(task?.id || ""))||[])[1]) || 0;
    const num=lessonNumber(task);
    const title=titleInfo(task);
    const lines=[
      "🌏 第"+period+"期｜第"+num+"堂課程音檔",
      "Session "+period+" – Lesson "+String(num).padStart(2,"0"),
      "",
      "📖 "+title.chinese
    ];
    if(title.english) lines.push(title.english);
    if(title.lecturer) lines.push("","🎤 講師："+title.lecturer);
    lines.push("","🎧 多國語言配音 / Multilingual Audio");
    let readyCount=0;
    let reviewCount=0;
    let pendingCount=0;
    for(const lang of languages){
      lines.push("",lang.label);
      const status=String(stages["tts:"+lang.code]?.status || "").toLowerCase();
      // Existing Drive files can predate an upstream edit or a new TTS run.
      // A stale/error/queued/running stage must never be advertised as final.
      // A partial lesson failure must not hide independently completed files.
      // A stale aggregate still blocks release unless this language has a
      // fresh, explicitly finished stage and a real Drive-backed MP3.
      const record=fileMap[lang.code]||{};
      const candidate=status==="needs_review"
        ? record.review
        : (record.official||record.review);
      const explicitReview=Boolean(candidate?.preview);
      const validLanguageStatus=explicitReview
        ? ["done","needs_review",""].includes(status)
        : !["stale","error","queued","running","delayed","needs_review"].includes(status);
      const invalidated=(!validLanguageStatus) ||
        (ttsStatus==="stale" && status!=="done" &&
          !(explicitReview && status==="needs_review")) ||
        (ttsStatus==="error" && status!=="done" &&
          !(explicitReview && status==="needs_review"));
      if(candidate && !invalidated){
        lines.push(candidate.link);
        if(explicitReview){
          lines.push("⚠️ 待驗收："+reviewReason(task,lang.code)+"（完整試聽檔，非影片同步正式 MP3）");
          reviewCount++;
        }
        readyCount++;
      } else {
        lines.push(status==="needs_review"
          ? "音檔待驗收："+reviewReason(task,lang.code)+"；尚無可取得的試聽 MP3"
          : "音檔待確認 / Audio pending verification");
        pendingCount++;
      }
    }
    lines.push("","━━━━━━━━━━━━");
    return {
      eligible, message:lines.join("\n"),
      readyCount,pendingCount,reviewCount,expectedCount:languages.length,
      allReady:languages.length>0 && pendingCount===0 && reviewCount===0,
      hasLinks:readyCount>0,
      languages:languages.map(l=>l.code)
    };
  }
  return { LANGUAGES, build, canonicalMp3Code, canonicalDriveUrl, reviewReason, titleInfo, lessonNumber };
});

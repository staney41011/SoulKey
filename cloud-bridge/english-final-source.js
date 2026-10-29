// Authoritative source selection for English Final.
// Prefer this lesson's source-video-bound central CC + Chinese Final.
// Legacy Drive fallback is read only when central CC truly does not exist.
// Never swallow Sheets 429, because that would mislabel a quota error as
// missing source and could encourage destructive retries.
"use strict";

async function loadEnglishFinalSource({
  taskId,sourceVideoId,targetVideoId,
  chineseFinalStore,youtubeCCQueue,driveReview
}) {
  const requested=String(sourceVideoId||"");
  const target=String(targetVideoId||"");
  if(!target || requested!==target)
    throw Error("english_final_source_video_mismatch");

  const zh=await chineseFinalStore.read(taskId);
  if(zh?.manuscript?.segments?.length) {
    const captions=await youtubeCCQueue.manifest(taskId);
    if(String(captions?.video_id||"")!==target)
      throw Error("english_cc_source_video_mismatch");
    const cc=(captions.cc_files||[]).find(file=>
      file.name==="en.transcript.txt" &&
      file.task_id===taskId && file.storage==="google-sheet");
    if(cc) {
      const verified=await youtubeCCQueue.transcript(taskId,cc.job_id,"en");
      if(!verified.ok || verified.task_id!==taskId ||
         verified.lang!=="en" ||
         String(verified.content||"").trim().length<200)
        throw Error("english_cc_source_content_invalid");
      return {original:zh.manuscript.segments,recoveredCC:cc};
    }
  }

  const source=await driveReview.review({task_id:taskId,kind:"en"});
  const original=source.ok && Array.isArray(source.segments)?
    source.segments:[];
  if(!original.length)
    throw Error("english_source_missing_for_this_lesson");
  return {original,recoveredCC:null};
}
module.exports={loadEnglishFinalSource};

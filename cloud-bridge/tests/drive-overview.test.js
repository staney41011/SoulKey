"use strict";
const assert=require("node:assert/strict");
const {createDriveOverview}=require("../drive-overview");
const folders={
 source:"folder_source_000000000",transcript:"folder_transcript_000000000",
 translation:"folder_translation_000000000",audio:"folder_audio_000000000",
 video:"folder_video_000000000",lesson:"folder_lesson_000000000"
};
const fake=(id,name,size=1000)=>({id,name,size:String(size),
 mimeType:"application/octet-stream",modifiedTime:"2026-10-20T00:00:00Z"});
const entries={
 [folders.source]:[],
 [folders.transcript]:[
   fake("1ValidChineseFinal9999999","第259期_第1堂課_中文人工定稿時間軸.txt",37000),
   fake("1ChineseRaw99999999999","第259期_第1堂課_中文純逐字稿.txt",20000),
   fake("1UnlistedJson999999999","zh-TW.final.json",25000)
 ],
 [folders.translation]:[
   fake("1EnglishFinal999999999","第259期_第1堂課_英文人工定稿時間軸.txt",20000)
 ],
 [folders.audio]:[
   fake("1EnglishAudio999999999","第257期_第4堂課_英文TTS音檔.mp3",24031149),
   fake("1EnglishPrev9999999999","en.preview.mp3",23000000),
   fake("1ThaiAudio999999999999","第257期_第4堂課_泰文TTS音檔.mp3",22645293),
   fake("1NepaliAudio9999999999","第257期_第4堂課_尼泊爾文TTS音檔.mp3",26000000),
   fake("1EnglishReport99999999","第257期_第4堂課_英文TTS對齊報告.json",409),
   fake("1ThaiReport99999999999","第257期_第4堂課_泰文TTS對齊報告.json",409),
   fake("1SourceYoutube999999999","youtube.en.mp3",27000000),
   fake("1CacheZip999999999999","_soulkey_tts_cache_en_0000.zip",900000)
 ],
 [folders.video]:[fake("1FinalVideo99999999999","rendered_zh.mp4",23000000)]
};
const overview=createDriveOverview({
 context:async()=>folders,
 children:async id=>entries[id]||[],
 getJsonFile:async id=>({timeline:{mode:"continuous_total_duration",source_duration:1829,
  final_duration:id==="1EnglishReport99999999"?1501.872:1415.256,
  needs_review:false}})
});
(async()=>{
 const data=await overview.courseFiles({task_id:"P259-L01"});
 assert.equal(data.type,"course_files");
 assert.equal(data.ok,true);
 assert.equal(data.groups.length,3);
 assert.equal(data.groups[0].files.length,2);
 assert.equal(data.groups[0].files[0].canonical_name,"zh-TW.final.txt");
 assert.equal(data.groups[1].files.length,4);
 assert.equal(data.groups[2].files.length,1);
 assert.equal(data.total_files,7);
 const share=await overview.ttsShareLinks({task_id:"P259-L01"});
 assert.equal(share.type,"tts_share_links");
 assert.equal(share.total_files,4);
 assert(share.groups[0].files.some(f=>f.canonical_name==="ne.mp3"),
  "Nepali MP3 must not disappear from sharing due to the old six-language filter");
 const english=share.groups[0].files.find(f=>f.canonical_name==="en.mp3");
 assert(english && english.size>0 && english.url.includes(english.id));
 assert.equal(english.needs_timing_review,true);
 assert.equal(english.audio_kind,"length_review");
 assert.match(english.timing_review_reason,/比原影片短/);
 const thai=share.groups[0].files.find(f=>f.canonical_name==="th.mp3");
 assert.equal(thai.needs_timing_review,true);
 const preview=share.groups[0].files.find(f=>f.canonical_name==="en.preview.mp3");
 assert(preview && preview.needs_timing_review===true);
 assert.equal((await overview.courseFiles({task_id:"../../bad"})).ok,false);
 console.log("PASS: Drive overview includes real transcript, TTS and video deliverables; excludes caches and YouTube source");
})().catch(err=>{console.error(err);process.exitCode=1});

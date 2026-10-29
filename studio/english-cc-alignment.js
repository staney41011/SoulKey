/* SoulKey: deterministic, lossless English CC allocation for review.
 * When the CC store only contains plain text (no cue timestamps), these
 * paragraph positions are estimates, NEVER verified time alignment.
 * All text comes from this lesson's verified English CC. No AI translation.
 */
(function(root){
  "use strict";
  function clean(text){
    return String(text||"").replace(/\s+/g," ").trim();
  }
  function alignmentRows(chinese,english,source){
    if(!Array.isArray(chinese)||!chinese.length)throw Error("missing_chinese_final");
    if(!source||!String(source.video_id||"").match(/^[A-Za-z0-9_-]{11}$/))
      throw Error("source_video_not_verified");
    const words=clean(english).split(" ").filter(Boolean);
    if(words.length<chinese.length || words.join(" ").length<200)
      throw Error("english_caption_text_too_short");
    const ids=new Set(chinese.map((row,i)=>String(row.id??i)));
    if(ids.size!==chinese.length)throw Error("duplicate_chinese_final_ids");
    const weights=chinese.map(row=>{
      const text=String(row.text??row.original??"").replace(/\s+/g,"");
      return Math.max(8,Math.sqrt(Math.max(1,text.length))*6);
    });
    const total=weights.reduce((a,b)=>a+b,0);
    const punctuation=/[.!?][\"'’”\)]*$/;
    const soft=/[,;:][\"'’”\)]*$/;
    let accumulated=0,previous=0;
    const results=[];
    for(let i=0;i<chinese.length;i++){
      const row=chinese[i];
      const id=Number(row.id??i);
      const start=Number(row.start||0),end=Number(row.end??start);
      if(!Number.isFinite(id)||!Number.isFinite(start)||!Number.isFinite(end)||
         end<start)throw Error("invalid_chinese_final_timing");
      let cutoff=words.length;
      if(i<chinese.length-1){
        accumulated+=weights[i];
        const target=Math.round(words.length*accumulated/total);
        const lower=previous+1,upper=words.length-(chinese.length-i-1);
        const center=Math.max(lower,Math.min(upper,target));
        const window=Math.min(12,Math.max(3,Math.floor(words.length/chinese.length/3)));
        cutoff=center;
        let bestScore=Infinity;
        for(let j=Math.max(lower,center-window);j<=Math.min(upper,center+window);j++){
          const word=words[j-1]||"";
          const bonus=punctuation.test(word)?-window*1.4:soft.test(word)?-window*0.5:0;
          const score=Math.abs(j-center)+bonus;
          if(score<bestScore){bestScore=score;cutoff=j;}
        }
      }
      const en=words.slice(previous,cutoff).join(" ");
      if(!en)throw Error("empty_estimated_english_segment");
      results.push({id,start,end,time:row.time||"",
        original:String(row.text??row.original??""),vernacular:"",
        en,source_en:en,en_confirmed:false,ids:[id],terms:[],
        pre_aligned:true,estimated_cc_alignment:true,
        source_video_id:source.video_id,source_job_id:source.job_id});
      previous=cutoff;
    }
    if(previous!==words.length ||
       results.map(x=>x.en).join(" ")!==words.join(" "))
      throw Error("english_cc_lossless_alignment_failed");
    return results;
  }
  const api={alignmentRows,clean};
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.SoulKeyEnglishCCAlignment=api;
})(typeof window!=="undefined"?window:globalThis);

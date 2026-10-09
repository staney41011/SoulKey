"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const text=fs.readFileSync("studio/app-20260923-48.js","utf8");
function pick(name){
  const start=text.indexOf("function "+name+"(");
  assert.ok(start>=0, "missing "+name);
  const next=text.indexOf("\nfunction ",start+9);
  return text.slice(start,next<0?undefined:next);
}
const sandbox={
  Number,String,Array, terms:[],
  formatClock:x=>String(x),
  repairReviewTimings:items=>items.map(x=>({...x})),
  dedupeEnglishRows:()=>{throw Error("pre-aligned passages must not be regrouped")}
};
vm.createContext(sandbox);
vm.runInContext(
  pick("englishReviewItemsFromGithub")+"\n"+pick("groupEnglishReviewItems"),
  sandbox
);
const get=sandbox.englishReviewItemsFromGithub;
const group=sandbox.groupEnglishReviewItems;
const payload={
  alignment_method:"english_sentence_chinese_time_v1",
  segments:[
    {id:0,start:0,end:18,text:"中文第一句。中文第二句。",source_en:"English sentence one. Sentence two.",en_text:"English sentence one. Sentence two.",zh_ids:[0,1],pre_aligned:true},
    {id:2,start:18,end:40,text:"中文第三句。",source_en:"English sentence three.",en_text:"Corrected English sentence three.",zh_ids:[2],pre_aligned:true}
  ]
};
const items=get(payload,true);
assert.equal(items.length,2);
assert.equal(items[1].source_en,"English sentence three.");
assert.equal(items[1].en,"Corrected English sentence three.");
const rows=group(items);
assert.equal(rows.length,2);
assert.deepEqual(Array.from(rows[0].ids),[0,1]);
assert.equal(rows[0].original,"中文第一句。中文第二句。");
assert.equal(rows[1].en,"Corrected English sentence three.");

// After a human confirms and saves, Apps Script publishes an en.json draft.
// Its old schema does not retain alignment_method; the source path 'en.json'
// must still be authoritative and never regroup or erase edits.
const draft={draft_saved_at:"2026-10-09",segments:[
  {...payload.segments[0],pre_aligned:undefined,zh_ids:undefined},
  {...payload.segments[1],pre_aligned:undefined,zh_ids:undefined,en_confirmed:true}
]};
const draftItems=get(draft,true);
assert.equal(group(draftItems).length,2);
assert.equal(group(draftItems)[1].en_confirmed,true);
assert.equal(group(draftItems)[1].en,"Corrected English sentence three.");
console.log("PASS: en.json paragraphs keep Chinese/English 1:1 alignment");
console.log("PASS: English source text and human edits survive review save/reload");

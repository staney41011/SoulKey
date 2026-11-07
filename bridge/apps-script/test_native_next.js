const fs=require("fs"),vm=require("vm"),crypto=require("crypto"),assert=require("assert");
const properties={},triggers=[];
const ctx=vm.createContext({
  console,Math,Date,JSON,Number,String,Array,Object,Set,
  PropertiesService:{getScriptProperties:()=>({
    getProperty:k=>properties[k]||null,
    setProperty:(k,v)=>{properties[k]=String(v);}
  })},
  ScriptApp:{getProjectTriggers:()=>triggers,
    newTrigger:name=>({timeBased:()=>({everyMinutes:m=>({
      create:()=>triggers.push({name,getHandlerFunction(){return this.name;}})
    })})}),
    deleteTrigger:t=>triggers.splice(triggers.indexOf(t),1)
  },
  Utilities:{DigestAlgorithm:{SHA_256:"SHA_256"},Charset:{UTF_8:"UTF_8"},
    computeDigest:(algo,s)=>Array.from(crypto.createHash("sha256")
      .update(String(s)).digest()).map(n=>n>127?n-256:n),
    formatDate:()=>"2026-11-07 12:00:00"
  },
  LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})},
  Logger:{log:()=>{}},
  readTasks_:()=>[]
});
for(const f of ["NativeNext.gs","NativeQuality.gs","NativeAudio.gs"]){
  new vm.Script(fs.readFileSync(__dirname+"/"+f,"utf8"),{filename:f})
    .runInContext(ctx);
}
assert.equal(ctx.soulkeyNextInstall().ok,true);
assert.equal(triggers.length,3);
ctx.soulkeyNextInstall();
assert.equal(triggers.length,3);
assert.equal(ctx.soulkeyNextTick().lessons,0);
assert.equal(ctx.soulkeyNextQATick().reviewed,0);
const source={task:"P261-L01",segments:[
  {id:1,text:"I visited 50 restaurants.",source_hash:"a",start:0,end:4},
  {id:2,text:"Cultivate peace.",source_hash:"b",start:4,end:8},
  {id:3,text:"Be grateful.",source_hash:"c",start:8,end:12},
  {id:4,text:"Help others.",source_hash:"d",start:12,end:16}
]};
const draft={segments:source.segments.map(x=>({
  id:x.id,start:x.start,end:x.end,source_hash:x.source_hash,
  text:x.id===1?"Visit矇 60 restaurantes.":"Un mensaje de esperanza."
}))};
const audit=ctx.skNQRisks_(source,draft,"es",[]);
assert(audit[0].risk_flags.includes("numbers_or_dates"));
assert(audit.filter(a=>a.selected_for_ai).length>=3);
assert.equal(ctx.skNQSummary_(audit,{}).state,"needs_review");
const decisions={};
audit.filter(a=>a.selected_for_ai).forEach(a=>decisions[String(a.id)]={grade:"A"});
assert.equal(ctx.skNQSummary_(audit,decisions).state,"approved_risk_based");
assert.equal(ctx.soulkeyNextStop().ok,true);
assert.equal(triggers.length,0);
console.log("PASS native P261+ schedule and QA regression");

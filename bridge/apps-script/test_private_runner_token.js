"use strict";
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const audio=fs.readFileSync(__dirname+"/NativeAudio.gs","utf8");
const begin=audio.indexOf("function skAudioGithub_(");
const end=audio.indexOf("\nfunction skAudioGithubJson_(",begin);
assert(begin>0 && end>begin);
const call=audio.slice(begin,end);
const original="legacy_worker_token";
const privateToken="private_runner_token";
let observed=null;
const props={
 getProperty:key=>key==="SOULKEY_PRIVATE_GITHUB_TOKEN"?privateToken:
                key==="GITHUB_TOKEN"?original:null
};
const ctx={
  SK_AUDIO_REPO:"staney41011/SoulKey-Private-Runner",
  PropertiesService:{getScriptProperties:()=>props},
  UrlFetchApp:{fetch:(url,opts)=>{
    observed={url,opts};
    return {getResponseCode:()=>204};
  }}
};
vm.createContext(ctx);
vm.runInContext(call,ctx);
ctx.skAudioGithub_("/actions/workflows/soulkey_private_tts.yml/dispatches","post",{ref:"main"});
assert.ok(observed.url.includes("SoulKey-Private-Runner"));
assert.equal(observed.opts.headers.Authorization,"Bearer "+privateToken);
assert.ok(observed.opts.payload.includes('"ref":"main"'));
props.getProperty=key=>key==="GITHUB_TOKEN"?original:null;
ctx.skAudioGithub_("/actions/workflows/soulkey_private_tts.yml","get",null);
assert.equal(observed.opts.headers.Authorization,"Bearer "+original);
props.getProperty=()=>null;
assert.throws(()=>ctx.skAudioGithub_("/actions/workflows/x","get"),/private_github_token_missing/);
assert(audio.includes("SOULKEY_PRIVATE_GITHUB_TOKEN"));
assert(!audio.includes('Authorization:"Bearer "+String('));
const gateStart=audio.indexOf("function skAudioLatestRunFailed_(");
const gateEnd=audio.indexOf("\nfunction soulkeyNextAudioTick(",gateStart);
assert(gateStart>0 && gateEnd>gateStart);
vm.runInContext(audio.slice(gateStart,gateEnd),ctx);
const lesson={task:"P261-L02"};
const requested={sha:"f801a505123456789"};
const receipt={dispatched_at:"2026-11-15 12:00:00"};
const run={display_title:"SoulKey TTS P261-L02-en-f801a505",
           created_at:"2026-11-15T04:00:01Z",
           status:"completed",conclusion:"failure"};
assert.equal(ctx.skAudioLatestRunFailed_(lesson,"en",requested,receipt,[run]),true);
assert.equal(ctx.skAudioLatestRunFailed_(lesson,"en",requested,receipt,
             [{...run,status:"in_progress",conclusion:null}]),false);
assert.equal(ctx.skAudioLatestRunFailed_(lesson,"en",requested,receipt,
             [{...run,display_title:"SoulKey TTS P261-L02-es-f801a505"}]),false);
assert.equal(ctx.skAudioLatestRunFailed_(lesson,"en",requested,receipt,
             [{...run,created_at:"2026-11-15T03:55:00Z"}]),false);
assert.equal(ctx.skAudioLatestRunFailed_(lesson,"en",requested,receipt,
             [{...run,conclusion:"success"}]),false);
assert.equal(ctx.skAudioLatestRunFailed_(lesson,"en",requested,receipt,
             [{...run}, {...run,status:"in_progress",created_at:"2026-11-15T04:00:04Z"}]),false);
assert(audio.includes("/runs?event=workflow_dispatch&per_page=100"));
console.log("PASS: private TTS token isolation and retry only latest terminal failed run");

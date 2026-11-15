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
console.log("PASS: private TTS credential isolated from general GITHUB_TOKEN");

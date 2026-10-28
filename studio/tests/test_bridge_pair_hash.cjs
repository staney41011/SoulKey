"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

const code=fs.readFileSync(path.join(__dirname,"..","bridge-pair.js"),"utf8");
function run(url){
  const items={};
  let replaced=null;
  const window={
    location:{href:url},
    history:{state:null,replaceState(_state,_title,url){replaced=url;}},
    sessionStorage:{
      setItem(k,v){items[k]=v;},
      getItem(k){return items[k];}
    }
  };
  vm.runInNewContext(code,{window,URL,URLSearchParams});
  return {window,items,replaced};
}
{
  const token="AbC0123456789_xYzAbC0123456789_xYzAbC0123456";
  const r=run("https://staney41011.github.io/SoulKey/studio/?_fresh=x#soulkey_pair="+token);
  assert.equal(r.items.soulkey_bridge_key_session_v1,token);
  assert.equal(r.replaced,"/SoulKey/studio/?_fresh=x");
  assert.equal(r.window.SOULKEY_PAIR_IMPORTED,true);
}
{
  const r=run("https://staney41011.github.io/SoulKey/studio/#soulkey_pair=OLDKEY");
  assert.equal(r.items.soulkey_bridge_key_session_v1,undefined);
  assert.equal(r.replaced,"/SoulKey/studio/");
  assert.match(r.window.SOULKEY_PAIR_ERROR,/格式/);
}
{
  const r=run("https://staney41011.github.io/SoulKey/studio/#task=P257-L01");
  assert.equal(r.replaced,null);
  assert.equal(r.items.soulkey_bridge_key_session_v1,undefined);
}
console.log("PASS: QR fragment imported to tab memory and removed from URL; invalid secrets rejected.");

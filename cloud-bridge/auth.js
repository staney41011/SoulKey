"use strict";
const crypto=require("node:crypto");
// Shared six-character passcodes must NEVER be stored in GitHub or in plaintext
// Cloud Run environment settings. A keyed SHA-256 digest binds them to the
// separately managed strong primary bridge key.
function digest(secret,phrase){
  return crypto.createHmac("sha256",secret).update(String(phrase),"utf8").digest();
}
function createBridgeAuth(opts){
  const secret=String(opts.primaryKey||"");
  if(secret.length<24)throw Error("BRIDGE_KEY missing");
  const legacy=String(opts.legacyHmac||"").trim().toLowerCase();
  if(legacy && !/^[a-f0-9]{64}$/.test(legacy))throw Error("invalid BRIDGE_LEGACY_HMAC");
  const legacyBytes=legacy?Buffer.from(legacy,"hex"):null;
  // Fixed one-hour window per requester. A global hard lock can be
  // abused to deny service to all legitimate teachers, so we avoid it.
  // This is a best-effort control; a six-character shared key still requires
  // careful distribution and stronger edge protections when exposed publicly.
  const windowMs=60*60*1000, ipMax=6;
  const attempts=new Map();
  function valid(value){
    const input=String(value||"");
    if(!input)return false;
    const a=crypto.createHash("sha256").update(input).digest();
    const b=crypto.createHash("sha256").update(secret).digest();
    if(crypto.timingSafeEqual(a,b))return true;
    if(!legacyBytes || input.length!==6)return false;
    return crypto.timingSafeEqual(digest(secret,input),legacyBytes);
  }
  function isBlocked(addr,clock=Date.now()){
    const ip=String(addr||"unknown").slice(0,128);
    const item=attempts.get(ip);
    return Boolean(item && clock-item.start<windowMs && item.count>ipMax);
  }
  function noteFailure(addr,clock=Date.now()){
    const ip=String(addr||"unknown").slice(0,128);
    const item=attempts.get(ip)||{start:clock,count:0};
    if(clock-item.start>=windowMs){item.start=clock;item.count=0;}
    item.count++;
    attempts.set(ip,item);
    if(attempts.size>5000){
      for(const [k,v] of attempts)if(clock-v.start>=windowMs)attempts.delete(k);
    }
    return isBlocked(ip,clock);
  }
  return {valid,noteFailure,isBlocked,hasLegacy:!!legacyBytes};
}
module.exports={createBridgeAuth,digest};

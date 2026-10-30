"use strict";
const fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict");
const root=path.resolve(__dirname,"../..");
const config=fs.readFileSync(path.join(root,"studio/config.js"),"utf8");
const app=fs.readFileSync(path.join(root,"studio/app-20260923-48.js"),"utf8");
const html=fs.readFileSync(path.join(root,"studio/index.html"),"utf8");
const routing=fs.readFileSync(path.join(root,"studio/bridge-routing.js"),"utf8");
// Restoration contract: old Apps Script is the primary read/write controller.
// Firebase augments status only; Cloud Run must not be required for login.
const match=config.match(/bridgeEndpoint: "(https:\/\/script\.google\.com\/macros\/s\/[^"]+\/exec)"/);
assert(match,"Primary Studio Bridge must be Apps Script");
assert(config.includes('legacyKaggleBridgeEndpoint: "'+match[1]+'"'),
  "Kaggle dispatch must use the same original Apps Script URL");
assert.match(config,/mode: "legacy-firebase"/);
assert.match(config,/firebaseHostingUrl: "https:\/\/soulkey-control-2026\.web\.app\/"/);
assert.match(app,/if\(isAppsScriptBridge\(\)\) initBridgeClient\(\)/);
assert.match(app,/if\(isAppsScriptBridge\(\)\)\{\s*return legacyBridgeRead\(fields,options\);/);
assert.match(app,/function useTopLevelP259LegacyDispatch\(fields\)/);
assert.match(app,/form\.method="POST";/);
assert.match(app,/form\.action=endpoint;/);
assert.match(routing,/google\.script\.run/);
assert.match(html,/id="p259-rescue-start"/);
assert.match(html,/id="p259-translation-start"/);
console.log("PASS: Studio Apps Script primary, authenticated iframe reads, iOS Kaggle POST and Firebase additive");

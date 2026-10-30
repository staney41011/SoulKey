"use strict";
const fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict");
const root=path.resolve(__dirname,"../..");
const config=fs.readFileSync(path.join(root,"studio/config.js"),"utf8");
const app=fs.readFileSync(path.join(root,"studio/app-20260923-48.js"),"utf8");
const html=fs.readFileSync(path.join(root,"studio/index.html"),"utf8");
// iOS Safari must not depend on an Apps Script embedded iframe for the
// first login or task list. Keep the six-digit key in Cloud Run POST bodies.
assert.match(config,/bridgeEndpoint: "https:\/\/soulkey-bridge-[^"]+run\.app"/);
assert.match(config,/legacyKaggleBridgeEndpoint: "https:\/\/script\.google\.com\/macros\/s\/[^"]+\/exec"/);
assert.match(app,/const LEGACY_KAGGLE_ENDPOINT = String\(cfg\.legacyKaggleBridgeEndpoint/);
assert.match(app,/const legacyMachineJob=fields\?\.action==="run_stage" &&/);
assert.match(app,/const endpoint=window\.SoulKeyBridgeRoutes\.endpoint\(cfg,fields\)/);
assert.match(app,/if\(key\.length===6\)\{/);
assert.match(app,/body:params\.toString\(\),signal:controller\.signal/);
assert.match(app,/form\.method="POST";/);
assert.match(app,/form\.action=endpoint;/);
assert.match(app,/if\(isAppsScriptBridge\(\)\) initBridgeClient\(\)/);
assert.match(html,/id="p259-rescue-start"/);
assert.match(html,/id="p259-translation-start"/);
console.log("PASS: iPhone login uses stable Cloud Run POST; actual machine jobs use old Apps Script/Kaggle POST");

"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const source=fs.readFileSync(path.join(__dirname,"..","github-worker-auth.js"),"utf8");
let payload;
const mod={exports:{}};
vm.runInNewContext("(function(require,module){"+source+"})",{
 URL,console
})(name=>{
 if(name!=="jose")throw Error("unexpected module "+name);
 return {createRemoteJWKSet:()=>({}),
  jwtVerify:async()=>({payload})};
},mod);
const {verifyGithubWorker}=mod.exports;
const base={repository:"staney41011/SoulKey",ref:"refs/heads/main",
 event_name:"schedule",
 workflow_ref:"staney41011/SoulKey/.github/workflows/soulkey_translation_queue.yml@refs/heads/main"};
async function run(){
 payload={...base};
 assert.equal(await verifyGithubWorker("signed-test-token","translation"),true);
 await assert.rejects(()=>verifyGithubWorker("signed-test-token","cc"),/wrong_workflow_lane/);
 payload={...base,workflow_ref:"staney41011/SoulKey/.github/workflows/soulkey_cc_queue.yml@refs/heads/main"};
 assert.equal(await verifyGithubWorker("signed-test-token","cc"),true);
 await assert.rejects(()=>verifyGithubWorker("signed-test-token","translation"),/wrong_workflow_lane/);
 payload={...base,workflow_ref:"staney41011/SoulKey/.github/workflows/soulkey_p259_final_delivery.yml@refs/heads/main"};
 assert.equal(await verifyGithubWorker("signed-test-token","delivery"),true);
 await assert.rejects(()=>verifyGithubWorker("signed-test-token","translation"),/wrong_workflow_lane/);
 await assert.rejects(()=>verifyGithubWorker("signed-test-token","cc"),/wrong_workflow_lane/);
 payload={...base,workflow_ref:"staney41011/SoulKey/.github/workflows/soulkey_translation_queue.yml@refs/heads/main"};
 await assert.rejects(()=>verifyGithubWorker("signed-test-token","delivery"),/wrong_workflow_lane/);
 payload={...base,repository:"attacker/fork"};
 await assert.rejects(()=>verifyGithubWorker("signed-test-token","translation"),/claims_not_authorized/);
 payload={...base,event_name:"pull_request"};
 await assert.rejects(()=>verifyGithubWorker("signed-test-token","translation"),/claims_not_authorized/);
 console.log("PASS: lane-separated GitHub OIDC workflow claim validation");
}
run().catch(e=>{console.error(e);process.exitCode=1});

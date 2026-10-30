"use strict";
const {createRemoteJWKSet,jwtVerify}=require("jose");
const ISSUER="https://token.actions.githubusercontent.com";
const AUDIENCE="soulkey-bridge-translation-worker-v1";
const jwks=createRemoteJWKSet(new URL(ISSUER+"/.well-known/jwks"));
async function verifyGithubWorker(token,kind="translation"){
 if(!token||typeof token!=="string"||token.length>12000)
  throw Error("missing_github_worker_token");
 const {payload}=await jwtVerify(token,jwks,{issuer:ISSUER,audience:AUDIENCE,
  algorithms:["RS256"],clockTolerance:30});
 // A valid GitHub token is not sufficient: it must come from the official
 // workflow on main in this specific repository.
 if(payload.repository!=="staney41011/SoulKey"||
    payload.ref!=="refs/heads/main"||
    !["schedule","workflow_dispatch"].includes(payload.event_name)||
    typeof payload.workflow_ref!=="string")
  throw Error("github_worker_claims_not_authorized");
 const expected=kind==="cc"
   ? "staney41011/SoulKey/.github/workflows/soulkey_cc_queue.yml@"
   : kind==="translation"
     ? "staney41011/SoulKey/.github/workflows/soulkey_translation_queue.yml@"
     : kind==="delivery"
       ? "staney41011/SoulKey/.github/workflows/soulkey_p259_final_delivery.yml@"
       : "";
 if(!expected||!payload.workflow_ref.startsWith(expected))
  throw Error("github_worker_wrong_workflow_lane");
 return true;
}
module.exports={verifyGithubWorker,AUDIENCE};

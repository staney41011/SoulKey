"use strict";
const {createRemoteJWKSet,jwtVerify}=require("jose");
const ISSUER="https://token.actions.githubusercontent.com";
const AUDIENCE="soulkey-bridge-translation-worker-v1";
const jwks=createRemoteJWKSet(new URL(ISSUER+"/.well-known/jwks"));
async function verifyGithubWorker(token){
 if(!token||typeof token!=="string"||token.length>12000)
  throw Error("missing_github_worker_token");
 const {payload}=await jwtVerify(token,jwks,{issuer:ISSUER,audience:AUDIENCE,
  algorithms:["RS256"],clockTolerance:30});
 // A valid GitHub token is not sufficient: it must come from the official
 // workflow on main in this specific repository.
 if(payload.repository!=="staney41011/SoulKey"||
    payload.ref!=="refs/heads/main"||
    !["schedule","workflow_dispatch"].includes(payload.event_name)||
    typeof payload.workflow_ref!=="string"||
    !payload.workflow_ref.startsWith("staney41011/SoulKey/.github/workflows/soulkey_translation_queue.yml@"))
  throw Error("github_worker_claims_not_authorized");
 return true;
}
module.exports={verifyGithubWorker,AUDIENCE};

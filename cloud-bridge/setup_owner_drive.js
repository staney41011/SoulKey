"use strict";
/* Local, explicitly user-invoked authorization. No OAuth secret is printed,
 * written to GitHub, included in command arguments, or transferred to ChatGPT.
 * Depends on the already-authorized CWL_PC gcloud and clasp installations.
 */
const fs=require("node:fs");
const path=require("node:path");
const os=require("node:os");
const cp=require("node:child_process");
const project="translate-system-509202",region="asia-east1",service="soulkey-bridge";
const sampleFolder="1eGmhvzVsXoIQwBQ9YyOEGFJ17cW9pMpP";
const log=message=>process.stdout.write(String(message)+"\n");
function cmd(name,args,opts={}){
 const result=cp.spawnSync(process.platform==="win32"?name+".cmd":name,args,{
  shell:process.platform==="win32",encoding:"utf8",stdio:opts.inherit?"inherit":"pipe",input:opts.input,
  maxBuffer:1024*1024*5,timeout:opts.timeout||120000
 });
 if(result.error)throw Error(name+" unavailable: "+result.error.message);
 if(result.status!==0)throw Error(name+" "+args.slice(0,3).join(" ")+" failed; check account permissions. "+String(result.stderr||"").slice(0,250));
 return String(result.stdout||"");
}
function getCredentialFile(){
 const location=path.join(os.homedir(),".clasprc.json");
 if(!fs.existsSync(location))return null;
 const c=JSON.parse(fs.readFileSync(location,"utf8"));
 const def=c.tokens?.default||c.token||c;
 const id=def.client_id||def.clientId||c.oauth2ClientSettings?.clientId||"";
 const secret=def.client_secret||def.clientSecret||c.oauth2ClientSettings?.clientSecret||"";
 const refresh=def.refresh_token||"";
 const scopes=String(def.scope||"");
 return {id,secret,refresh,scopes};
}
function findDefaultClaspClient(){
 let root="";
 try{root=cmd("npm",["root","-g"]).trim();}catch(_){return null;}
 const home=path.join(root,"@google","clasp");
 if(!fs.existsSync(home))return null;
 const targets=[];
 function walk(dir,depth){
  if(depth>6||targets.length>1000)return;
  for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
   const item=path.join(dir,entry.name);
   if(entry.isDirectory()){
    if(!["node_modules",".git","tests"].includes(entry.name))walk(item,depth+1);
   }else if(entry.isFile()&&/oauth_client\.(?:js|ts)$/.test(entry.name))
    targets.push(item);
  }
 }
 walk(home,0);
 for(const item of targets){
  const data=fs.readFileSync(item,"utf8");
  const id=data.match(/DEFAULT_CLASP_OAUTH_CLIENT_ID\s*=\s*["']([^"']+)/);
  const secret=data.match(/DEFAULT_CLASP_OAUTH_CLIENT_SECRET\s*=\s*["']([^"']+)/);
  if(id&&secret)return{id:id[1],secret:secret[1]};
 }
 return null;
}
async function credential(){
 let cred=getCredentialFile();
 if(!cred?.refresh||!cred.scopes.split(" ").includes("https://www.googleapis.com/auth/drive")){
  log("需要授權原本的 Google 帳號存取該專案 Google Drive。將開啟一次 Google 登入同意畫面。");
  const args=["login","--extra-scopes","https://www.googleapis.com/auth/drive"];
  cmd("clasp",args,{inherit:true,timeout:240000});
  cred=getCredentialFile();
 }
 if(!cred?.refresh)throw Error("Cannot find clasp OAuth refresh token after login");
 if(!cred?.id||!cred?.secret){
  const defaults=findDefaultClaspClient();
  if(defaults){cred.id=cred.id||defaults.id;cred.secret=cred.secret||defaults.secret;}
 }
 if(!cred?.id||!cred?.secret)
  throw Error("Cannot locate clasp OAuth client details. Use clasp login --creds with a Google Desktop OAuth client and rerun.");
 if(!cred.scopes.split(" ").includes("https://www.googleapis.com/auth/drive"))
  throw Error("Google Drive full access scope was not granted");
 return cred;
}
async function validateOwner(cred){
 const form=new URLSearchParams({
  grant_type:"refresh_token",refresh_token:cred.refresh,
  client_id:cred.id,client_secret:cred.secret
 });
 const token=await fetch("https://oauth2.googleapis.com/token",{
  method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:form
 });
 if(!token.ok)throw Error("Google OAuth refresh check failed HTTP "+token.status);
 const data=await token.json();
 const resp=await fetch("https://www.googleapis.com/drive/v3/files/"+sampleFolder+
  "?fields=id,name,capabilities(canAddChildren)",{
    headers:{Authorization:"Bearer "+data.access_token}
  });
 if(!resp.ok)throw Error("Owner OAuth cannot access the course translation folder; HTTP "+resp.status);
 const meta=await resp.json();
 if(meta.capabilities?.canAddChildren!==true)
  throw Error("Owner OAuth account cannot create files under this course folder");
 log("成功驗證：已授權帳號可在既有課程資料夾建立檔案。");
}
function secretName(label){return "soulkey-drive-owner-"+label;}
function setSecret(label,value){
 const name=secretName(label);
 try{cmd("gcloud",["secrets","describe",name,"--project="+project]);}
 catch{
  cmd("gcloud",["secrets","create",name,"--project="+project,
    "--replication-policy=automatic","--quiet"]);
 }
 cmd("gcloud",["secrets","versions","add",name,"--project="+project,
  "--data-file=-"],{input:value});
}
function getServiceAccount(){
 const text=cmd("gcloud",["run","services","describe",service,"--project="+project,
  "--region="+region,"--format=json"]);
 const obj=JSON.parse(text);
 return obj.spec?.template?.spec?.serviceAccountName;
}
async function main(){
 log("SoulKey English Final ─ Owner Google Drive Authorization");
 log("No secrets will be displayed or committed to GitHub.");
 cmd("gcloud",["auth","list","--filter=status:ACTIVE","--format=value(account)"]);
 const creds=await credential();
 await validateOwner(creds);
 const serviceAccount=getServiceAccount();
 if(!serviceAccount)throw Error("Cloud Run service account is not configured");
 cmd("gcloud",["services","enable","secretmanager.googleapis.com","--project="+project]);
 for(const [label,value] of [
  ["client-id",creds.id],["client-secret",creds.secret],["refresh-token",creds.refresh]
 ]){
  setSecret(label,value);
  cmd("gcloud",["secrets","add-iam-policy-binding",secretName(label),
   "--project="+project,
   "--member=serviceAccount:"+serviceAccount,
   "--role=roles/secretmanager.secretAccessor","--quiet"]);
  log("Credential "+label+" safely stored in Secret Manager.");
 }
 // Deploy latest checked-out source and attach secrets without exposing values.
 const dirname=__dirname;
 cmd("gcloud",["run","deploy",service,"--project="+project,"--region="+region,
  "--source="+dirname,"--allow-unauthenticated","--max-instances=1","--quiet"],{timeout:480000});
 const update=[
  "GOOGLE_OWNER_CLIENT_ID="+secretName("client-id")+":latest",
  "GOOGLE_OWNER_CLIENT_SECRET="+secretName("client-secret")+":latest",
  "GOOGLE_OWNER_REFRESH_TOKEN="+secretName("refresh-token")+":latest"
 ].join(",");
 cmd("gcloud",["run","services","update",service,"--project="+project,"--region="+region,
  "--update-secrets="+update,"--quiet"],{timeout:360000});
 log("Google Drive owner authorization is now active on Cloud Run.");
 log("All editors continue using the existing six-character Bridge Key.");
 log("Next: open SoulKey, submit an English Final and confirm the three Drive files appear.");
}
main().catch(e=>{process.stderr.write("Setup failed: "+String(e.message||e)+"\n");process.exitCode=1;});

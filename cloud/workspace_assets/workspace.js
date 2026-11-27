"use strict";
const by=id=>document.getElementById(id);
let session=null, generation=0, job=null, timer=null, moduleName="cv_formatting", busy=false;
const TYPES={docx:"application/vnd.openxmlformats-officedocument.wordprocessingml.document",pdf:"application/pdf",txt:"text/plain"};
function message(text){by("message").textContent=text;}
function reset(){
  generation++;clearTimeout(timer);timer=null;session=null;job=null;busy=false;
  by("job-form").reset();by("login-form").reset();by("job-panel").hidden=true;
  by("download").hidden=true;by("submit-job").disabled=false;
  by("workspace").hidden=true;by("logout").hidden=true;by("login-panel").hidden=false;
  choose("cv_formatting");
}
function choose(name){
  moduleName=name;
  const blind=name==="cv_blinding";
  by("module-title").textContent=blind?"CV Blinding":"CV Formatting";
  by("module-description").textContent=blind?"Anonymise a CV and review the Word result.":"Upload a CV and prepare a consistent Word document.";
  by("gender-label").hidden=!blind;if(!blind)by("gender").checked=false;
  document.querySelectorAll("[data-module]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.module===name)));
}
async function api(path,options={},epoch=generation){
  const response=await fetch(path,{...options,credentials:"same-origin",cache:"no-store",redirect:"error"});
  if(epoch!==generation)throw new Error("stale");
  if(response.status===401){reset();message("Sign in again to continue.");throw new Error("stale");}
  return response;
}
async function json(response){
  if(!response.ok)throw new Error("request_failed");
  return response.json();
}
function writeHeaders(type){return {"Content-Type":type,"X-CSRF-Token":session.csrf};}
function showSession(value){
  if(!value||typeof value.csrf!=="string"||!value.csrf)throw new Error("invalid_session");
  session=value;by("login-panel").hidden=true;by("workspace").hidden=false;by("logout").hidden=false;
}
async function refresh(epoch=generation){
  if(!job||!session||epoch!==generation)return;
  clearTimeout(timer);timer=null;
  const id=job;
  try{
    const state=await json(await api("/api/jobs/"+encodeURIComponent(id),{},epoch));
    if(epoch!==generation||id!==job)return;
    if(!["queued","running","succeeded","failed","needs_review"].includes(state.state))throw new Error("invalid_state");
    by("job-state").textContent=state.state.replaceAll("_"," ");
    const review=state.state==="needs_review";
    by("review-note").hidden=!review;
    by("download").hidden=!(state.state==="succeeded"||review);
    by("download").textContent=review?"Download for human review":"Download Word document";
    by("download").dataset.review=review?"1":"0";
    if(state.state==="queued"||state.state==="running")timer=setTimeout(()=>refresh(epoch),3000);
  }catch(e){if(epoch===generation&&e.message!=="stale")message("Status unavailable. Use Refresh status to try again.");}
}
by("login-form").addEventListener("submit",async e=>{
  e.preventDefault();const epoch=generation,form=e.currentTarget,button=form.querySelector("button");
  if(button.disabled)return;button.disabled=true;message("");
  try{
    const payload=Object.fromEntries(new FormData(form));
    await json(await api("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)},epoch));
    form.reset();const me=await json(await api("/api/auth/me",{},epoch));
    if(epoch===generation)showSession(me);
  }catch(e){if(epoch===generation&&e.message!=="stale")message("Sign-in failed or service unavailable.");}
  finally{button.disabled=false;form.elements.password.value="";}
});
by("logout").addEventListener("click",async()=>{
  if(!session)return;const epoch=generation;by("logout").disabled=true;
  try{await json(await api("/api/auth/logout",{method:"POST",headers:writeHeaders("application/json")},epoch));if(epoch===generation){reset();message("Signed out.");}}
  catch(e){if(epoch===generation&&e.message!=="stale")message("Sign-out was not confirmed. Try again.");}
  finally{by("logout").disabled=false;}
});
document.querySelectorAll("[data-module]").forEach(b=>b.addEventListener("click",()=>{if(!busy)choose(b.dataset.module);}));
by("job-form").addEventListener("submit",async e=>{
  e.preventDefault();if(!session||busy)return;
  const file=by("file").files[0],ext=file?.name.split(".").pop().toLowerCase();
  if(!file||!Object.hasOwn(TYPES,ext)||!file.size||file.size>32*1024*1024){message("Choose a PDF, DOCX or TXT file up to 32 MiB.");return;}
  const epoch=generation,key=crypto.randomUUID(),selected=moduleName;
  const options={alignment:by("alignment").value,correct_language:by("language").checked,neutral_gender:selected==="cv_blinding"&&by("gender").checked};
  busy=true;by("submit-job").disabled=true;message("Uploading document…");
  try{
    const upload=await json(await api("/api/documents",{method:"POST",headers:writeHeaders(TYPES[ext]),body:file},epoch));
    if(epoch!==generation)return;
    const queued=await json(await api("/api/jobs",{method:"POST",headers:writeHeaders("application/json"),body:JSON.stringify({document_id:upload.document_id,module:selected,idempotency_key:key,...options})},epoch));
    if(epoch!==generation)return;
    job=queued.job_id;by("job-panel").hidden=false;by("download").hidden=true;by("file").value="";message("Job submitted.");await refresh(epoch);
  }catch(e){if(epoch===generation&&e.message!=="stale")message("Submission was not confirmed. Check with your administrator before retrying; a document or job may already exist.");}
  finally{if(epoch===generation){busy=false;by("submit-job").disabled=false;}}
});
by("refresh-job").addEventListener("click",()=>refresh());
by("download").addEventListener("click",async()=>{
  if(!job||!session)return;
  const epoch=generation,id=job,review=by("download").dataset.review==="1";
  by("download").disabled=true;
  try{
    const response=await api("/api/jobs/"+encodeURIComponent(id)+"/download"+(review?"?review=1":""),{},epoch);
    if(!response.ok)throw new Error("download_failed");
    const blob=await response.blob();if(epoch!==generation||id!==job)return;
    const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=review?"cv-review.docx":"cv.docx";document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){if(epoch===generation&&e.message!=="stale")message("Download unavailable. The job may require review without a published file.");}
  finally{by("download").disabled=false;}
});
(async()=>{const epoch=generation;try{const response=await fetch("/api/auth/me",{credentials:"same-origin",cache:"no-store",redirect:"error"});if(response.ok&&epoch===generation)showSession(await response.json());}catch{message("Staging backend unavailable.");}})();

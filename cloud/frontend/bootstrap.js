/* Explicit staging composition, never load desktop bootstrap or API keys. */
"use strict";
(()=>{
 const el=id=>document.getElementById(id);
 const rawFetch=window.fetch.bind(window);
 let binding=null,batchBinding=null,providerBinding=null,historyBinding=null,accountBinding=null,usageBinding=null,scoringBinding=null,mode="paste",generation=0,poll=null,sessionTimer=null,closing=false;
 const say=text=>{el("cloudMessage").textContent=text;};
 const login=el("cloudLogin"),logout=el("cloudLogout");
 const client=CVCloudClient.create({fetcher:rawFetch,uuid:()=>crypto.randomUUID()});
 function reset(){
   generation++;clearInterval(poll);clearTimeout(sessionTimer);poll=null;sessionTimer=null;
   if(binding)binding.dispose();binding=null;if(batchBinding)batchBinding.dispose();batchBinding=null;if(providerBinding)providerBinding.dispose();providerBinding=null;if(historyBinding)historyBinding.dispose();historyBinding=null;if(accountBinding)accountBinding.dispose();accountBinding=null;if(usageBinding)usageBinding.dispose();usageBinding=null;if(scoringBinding)scoringBinding.dispose();scoringBinding=null;client.clear();
   el("cloudContent").style.display="none";el("cloudLoginPanel").hidden=false;el("cloudLoginPanel").style.display="";logout.hidden=true;logout.style.display="none";
   login.reset();choose("paste");chooseView("Format");el("cloudAlignment").value="left";el("cloudLanguage").checked=false;el("cloudNeutral").checked=false;
   el("dzFileName").textContent="";el("charCount").textContent="0 characters";
 }
 function choose(value){
   mode=value;
   for(const [key,suffix] of [["paste","Paste"],["upload","Upload"]]){
     el("tab"+suffix).classList.toggle("active",key===value);
     el("panel"+suffix).classList.toggle("active",key===value);
   }
 }
 function chooseView(view){
   for(const key of ["Format","Batch","Appraiser"]){
     if(!el("view"+key))continue;
     el("view"+key).style.display=key===view?"block":"none";
     el("tab"+key).classList.toggle("active",key===view);
   }
   el("cloudJobOptions").style.display=view==="Appraiser"?"none":"";
   el("cloudRefresh").style.display=view==="Format"?"":"none";
   el("cloudRecover").style.display=view==="Format"?"":"none";
 }
 function attach(session){
   const role=session.role;
   if(binding)binding.dispose();if(batchBinding)batchBinding.dispose();if(providerBinding)providerBinding.dispose();providerBinding=null;if(historyBinding)historyBinding.dispose();historyBinding=null;if(accountBinding)accountBinding.dispose();accountBinding=null;if(usageBinding)usageBinding.dispose();usageBinding=null;
   const epoch=generation;
   const readOptions=module=>({alignment:el("cloudAlignment").value,correct_language:el("cloudLanguage").checked,neutral_gender:module==="cv_blinding"&&el("cloudNeutral").checked});
   const confirmReview=()=>window.confirm("Download for human review only? Do not distribute until checked.");
   const saveDocument=async result=>{
     if(epoch!==generation||closing)return;
     const url=URL.createObjectURL(result.blob);
     const a=document.createElement("a");a.href=url;a.download=result.filename;document.body.append(a);a.click();a.remove();
     setTimeout(()=>URL.revokeObjectURL(url),1000);
   };
   binding=CVCloudExistingControls.bind({document,client,
     readInputMode:()=>mode,
     readOptions,confirmReview,saveDocument});
   if(el("viewBatch")){
     batchBinding=CVCloudBatch.bind({document,client,readOptions,confirmReview,saveDocument});
   }
   if(scoringBinding)scoringBinding.dispose();
   if(el("viewAppraiser"))scoringBinding=CVCloudScoring.bind({document,client});
   chooseView("Format");
   if(el("cloudProviderToggle")&&["owner","admin"].includes(role)){
     providerBinding=CVCloudProviderSettings.bind({document,client,confirmDisable:()=>window.confirm("Disable organisation AI processing? Existing in-flight requests cannot be recalled."),onAuthLost:()=>{if(epoch===generation){reset();say("Session expired. Sign in again.");}}});
   }
   if(el("cloudHistoryToggle")){
     historyBinding=CVCloudHistory.bind({document,client,confirmReview,saveDocument,onAuthLost:()=>{if(epoch===generation){reset();say("Session expired. Sign in again.");}}});
   }
   if(el("cloudAccountsToggle")&&["owner","admin"].includes(role)&&session.userId){
     accountBinding=CVCloudAccounts.bind({document,client,role,userId:session.userId,confirm:message=>window.confirm(message),onAuthLost:()=>{if(epoch===generation){reset();say("Session expired. Sign in again.");}}});
   }
   if(el("cloudUsageToggle")&&["owner","admin"].includes(role)){
     usageBinding=CVCloudUsage.bind({document,client,onAuthLost:()=>{if(epoch===generation){reset();say("Session expired. Sign in again.");}}});
   }
   el("cloudLoginPanel").hidden=true;el("cloudLoginPanel").style.display="none";el("cloudContent").style.display="block";logout.hidden=false;logout.style.display="";
   let refreshing=false;
   poll=setInterval(async()=>{
     if(refreshing||epoch!==generation||!binding)return;
     refreshing=true;
     try{await binding.refresh();if(batchBinding)await batchBinding.refresh();if(scoringBinding)await scoringBinding.refresh();}catch(e){if(epoch===generation&&e.code==="authentication_required"){reset();say("Session expired. Sign in again.");}}
     finally{refreshing=false;}
   },4000);
   // Expire inactive UI even when no job exists. The server remains authoritative.
   sessionTimer=setTimeout(()=>{if(epoch===generation){reset();say("Please sign in again.");}},8*60*60*1000);
 }
 login.addEventListener("submit",async event=>{
   event.preventDefault();
   const button=login.querySelector("button");if(button.disabled)return;
   button.disabled=true;const epoch=generation;const payload=Object.fromEntries(new FormData(login));
   try{
     const res=await rawFetch("/api/auth/login",{method:"POST",credentials:"same-origin",cache:"no-store",redirect:"error",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
     if(!res.ok)throw Error("login_failed");
     const session=await client.hydrate();
     if(epoch===generation){login.reset();attach(session);say("");}
   }catch{if(epoch===generation)say("Sign-in failed or staging service unavailable.");}
   finally{login.elements.password.value="";button.disabled=false;}
 });
 logout.addEventListener("click",async()=>{
   if(closing)return;closing=true;logout.disabled=true;
   if(scoringBinding)scoringBinding.dispose();scoringBinding=null;
   if(providerBinding)providerBinding.dispose();providerBinding=null;if(historyBinding)historyBinding.dispose();historyBinding=null;if(accountBinding)accountBinding.dispose();accountBinding=null;if(usageBinding)usageBinding.dispose();usageBinding=null;
   try{await client.logout();reset();say("Signed out.");}
   catch{reset();say("Local view cleared; server sign-out was not confirmed. Close this browser session.");}
   finally{closing=false;logout.disabled=false;}
 });
 for(const key of ["Format","Batch","Appraiser"]){
   if(!el("view"+key))continue;
   el("tab"+key).addEventListener("click",()=>{
     chooseView(key);
     if(key==="Appraiser")scoringBinding?.history().catch(error=>{
       if(error.code==="authentication_required"){reset();say("Session expired. Sign in again.");}
     });
   });
 }
 el("tabPaste").addEventListener("click",()=>choose("paste"));
 el("tabUpload").addEventListener("click",()=>choose("upload"));
 el("dropZone").addEventListener("click",e=>{if(e.target!==el("fileInput")&&e.target!==el("dzClear"))el("fileInput").click();});
 el("fileInput").addEventListener("change",()=>{el("dzFileName").textContent=el("fileInput").files[0]?.name||"";el("dzClear").style.display=el("fileInput").files.length?"inline-block":"none";});
 el("dzClear").addEventListener("click",e=>{e.stopPropagation();el("fileInput").value="";el("dzFileName").textContent="";el("dzClear").style.display="none";});
 el("cvInput").addEventListener("input",()=>{el("charCount").textContent=el("cvInput").value.length+" characters";});
 el("cloudClearInput").addEventListener("click",()=>{el("cvInput").value="";el("fileInput").value="";el("dzFileName").textContent="";el("charCount").textContent="0 characters";el("dzClear").style.display="none";});
 el("cloudRefresh").addEventListener("click",async()=>{try{if(binding)await binding.refresh();}catch(e){if(e.code==="authentication_required"){reset();say("Session expired.");}else say("Status unavailable.");}});
 el("cloudRecover").addEventListener("click",async()=>{if(binding)await binding.resumeSubmission();});
 // Do not silently restore a prior account on a shared browser. Explicit login.
})();

/* Reuse the original single-CV controls. Only bind inside a separately
 * allowlisted cloud entry point, without desktop bootstrap scripts/handlers.
 * This is intentionally not a drop-in override of window.fetch/startFormat.
 */
(function(root,factory){
  const exported=factory();
  if(typeof module==="object"&&module.exports)module.exports=exported;
  else root.CVCloudExistingControls=exported;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";
  const IDS=Object.freeze(["btnFormat","btnBlind","btnDocx","cvInput","fileInput","stepText","outputBox","blindBadge"]);
  const NAV=Object.freeze({format:"Format",batch:"Batch",appraiser:"Appraiser",company:"Company",jdanon:"JDAnon"});
  const messages=Object.freeze({
    queued:"Queued — processing will continue on the server.",
    running:"Processing CV…",
    succeeded:"Completed. Download the Word document.",
    failed:"Processing failed. Review the job before submitting again.",
    needs_review:"Review required. A Word document may be available for human review; do not distribute before checking."
  });
  function bind({document,client,readOptions,readInputMode,saveDocument,confirmReview}){
    if(!document||!client||![readOptions,readInputMode,saveDocument,confirmReview].every(x=>typeof x==="function"))throw new TypeError("Cloud composition required");
    const nodes=Object.fromEntries(IDS.map(key=>[key,document.getElementById(key)]));
    if(IDS.some(key=>!nodes[key]))throw new Error("Existing CV controls missing");
    for(const key of ["btnFormat","btnBlind","btnDocx"]){
      if(nodes[key].hasAttribute("onclick")||nodes[key].onclick)throw new Error("Remove desktop handlers before binding");
    }
    let job=null,intent=null,busy=false,disposed=false,uploadUnconfirmed=false,seq=0;
    const lifetime=new AbortController();
    let previewButton=null,previewShown=null;
    const progress=Object.fromEntries(["progressWrap","progressLabel","progressTimer","progressFill","pstep1","pstep2","pstep3","pstep3label"].map(k=>[k,document.getElementById(k)]));
    const hasProgress=Object.values(progress).every(Boolean);
    let started=null,clockId=null,phase=null;
    function tick(){
      if(!hasProgress||started===null)return;
      const seconds=Math.max(0,Math.floor((Date.now()-started)/1000));
      progress.progressTimer.textContent=Math.floor(seconds/60)+"m "+String(seconds%60).padStart(2,"0")+"s";
    }
    function showProgress(state){
      if(!hasProgress||disposed)return;
      phase=state;
      if(started===null)started=Date.now();
      const terminal=["succeeded","failed","needs_review"].includes(state);
      const stage=terminal?3:state==="running"?2:1;
      progress.progressWrap.classList.add("on");
      progress.progressLabel.textContent=messages[state]||"Submitting CV…";
      progress.pstep3label.textContent=state==="failed"?"Failed":state==="needs_review"?"Review required":"Complete";
      // Stage-based progress, not a fabricated percentage of AI work.
      progress.progressFill.style.width=({1:"12%",2:"55%",3:"100%"})[stage];
      [progress.pstep1,progress.pstep2,progress.pstep3].forEach((n,i)=>{
        n.classList.toggle("active",i+1===stage&&!terminal);
        n.classList.toggle("done",i+1<stage||state==="succeeded");
      });
      tick();
      if(terminal){clearInterval(clockId);clockId=null;}
      else if(clockId===null)clockId=setInterval(tick,1000);
    }
    function resetProgress(){
      clearInterval(clockId);clockId=null;started=null;phase=null;
      if(hasProgress){progress.progressWrap.classList.remove("on");progress.progressFill.style.width="0%";progress.progressTimer.textContent="0s";}
    }
    if(typeof client.preview==='function'&&typeof document.createElement==='function'&&nodes.btnDocx.parentNode){
      previewButton=document.createElement('button');previewButton.type='button';previewButton.className='sec';previewButton.id='cloudPreview';previewButton.textContent='Preview output';
      nodes.btnDocx.parentNode.insertBefore(previewButton,nodes.btnDocx);
      previewButton.addEventListener('click',showPreview);
    }
    function display(text){if(!disposed){previewShown=null;nodes.stepText.textContent=text;nodes.outputBox.classList?.add('empty');nodes.outputBox.textContent=text;}}
    function controls(){
      if(disposed)return;
      const pending=job&&["queued","running"].includes(job.state);
      nodes.btnFormat.disabled=busy||!!intent||!!pending||uploadUnconfirmed;
      nodes.btnBlind.disabled=nodes.btnFormat.disabled;
      nodes.btnDocx.disabled=busy||!job||!["succeeded","needs_review"].includes(job.state);
      if(previewButton)previewButton.disabled=nodes.btnDocx.disabled;
      nodes.btnDocx.textContent=job?.state==="needs_review"?"Download for review":"Download DOCX";
    }
    async function refresh(){
      if(!job||disposed)return;
      const current=++seq,jobId=job.job_id;
      const next=await client.status(jobId,{signal:lifetime.signal});
      if(disposed||current!==seq||job?.job_id!==jobId)return;
      job=next;
      if(phase!==next.state)showProgress(next.state);
      nodes.blindBadge.style.display=next.module==="cv_blinding"&&["succeeded","needs_review"].includes(next.state)?"inline-flex":"none";
      if(previewShown!==next.job_id)display(messages[next.state]);
      controls();
      return next;
    }
    async function submit(blind){
      if(busy||intent||disposed||uploadUnconfirmed||(job&&["queued","running"].includes(job.state)))return;
      resetProgress();showProgress("submitting");
      busy=true;seq++;job=null;nodes.blindBadge.style.display="none";controls();
      try{
        const moduleName=blind?"cv_blinding":"cv_formatting";
        const opts=readOptions(moduleName);
        const mode=readInputMode();
        if(mode!=="upload"&&mode!=="paste")throw new Error("invalid_input_mode");
        const input=mode==="upload"?nodes.fileInput.files[0]:nodes.cvInput.value;
        display("Uploading source to secure processing queue…");
        uploadUnconfirmed=true;
        const documentId=await client.upload(input,{signal:lifetime.signal});
        uploadUnconfirmed=false;
        if(disposed)return;
        intent=client.prepare(documentId,moduleName,opts);
        const jobId=await client.submit(intent,{signal:lifetime.signal});
        if(disposed)return;
        job={job_id:jobId,state:"queued",module:moduleName};
        intent=null;showProgress("queued");display(messages.queued);
        await refresh();
      }catch{
        if(!intent&&!job&&!uploadUnconfirmed)showProgress("failed");
        display(intent?"Job submission not confirmed. Do not create another job. Recover using the same request.":uploadUnconfirmed?"Upload not confirmed. Check document history before starting a new session.":job?"Job submitted; status unavailable. Refresh the job rather than submitting again.":"Request failed. Check input and options.");
      }finally{busy=false;controls();}
    }
    async function resumeSubmission(){
      if(!intent||busy||disposed)return;
      busy=true;controls();
      try{
        const jobId=await client.submit(intent,{signal:lifetime.signal});
        if(disposed)return;
        job={job_id:jobId,state:"queued",module:intent.module};
        intent=null;
        await refresh();
      }catch{display("Submission still unconfirmed. No new request ID has been generated.");}
      finally{busy=false;controls();}
    }
    async function showPreview(){
      if(disposed||busy||!job||!["succeeded","needs_review"].includes(job.state))return;
      const target=job.job_id,review=job.state==="needs_review";
      busy=true;controls();
      try{
        if(review&&(await confirmReview())!==true)return;
        if(disposed||job?.job_id!==target)return;
        const result=await client.preview(target,{review,signal:lifetime.signal});
        if(disposed||job?.job_id!==target)return;
        // Render only literal text from the verified final Word output.
        // Never render provider markup, raw source text, links or HTML.
        nodes.outputBox.textContent="";
        nodes.outputBox.classList?.remove("empty");
        const heading=document.createElement("p");heading.textContent=result.requires_review?"Human review required — do not distribute":"Output text preview — Word layout may differ";
        nodes.outputBox.appendChild(heading);
        for(const line of result.paragraphs){
          const p=document.createElement("p");p.textContent=line;nodes.outputBox.appendChild(p);
        }
        previewShown=target;
      }catch{display("Preview unavailable. Refresh the job or download the Word document.");}
      finally{busy=false;controls();}
    }
    async function download(){
      if(disposed||busy||!job||!["succeeded","needs_review"].includes(job.state))return;
      busy=true;controls();
      try{
        const review=job.state==="needs_review";
        if(review&&(await confirmReview())!==true)return;
        if(disposed)return;
        const result=await client.download(job.job_id,{review,signal:lifetime.signal});
        if(!disposed)await saveDocument(result);
      }catch{display("Download unavailable. Refresh the job status before retrying.");}
      finally{busy=false;controls();}
    }
    const format=()=>submit(false),blind=()=>submit(true);
    nodes.btnFormat.addEventListener("click",format);
    nodes.btnBlind.addEventListener("click",blind);
    nodes.btnDocx.addEventListener("click",download);
    controls();
    return Object.freeze({refresh,resumeSubmission,dispose(){
      resetProgress();disposed=true;seq++;lifetime.abort();intent=null;job=null;
      if(previewButton){previewButton.removeEventListener('click',showPreview);previewButton.remove();}
      nodes.btnFormat.removeEventListener("click",format);
      nodes.btnBlind.removeEventListener("click",blind);
      nodes.btnDocx.removeEventListener("click",download);
      nodes.btnFormat.disabled=true;nodes.btnBlind.disabled=true;nodes.btnDocx.disabled=true;
      nodes.cvInput.value="";nodes.fileInput.value="";nodes.outputBox.textContent="";nodes.stepText.textContent="";nodes.blindBadge.style.display="none";
    }});
  }
  return Object.freeze({bind,IDS,NAV});
});

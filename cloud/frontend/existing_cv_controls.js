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
    let job=null,intent=null,busy=false,disposed=false,seq=0;
    function display(text){if(!disposed){nodes.stepText.textContent=text;nodes.outputBox.textContent=text;}}
    function controls(){
      if(disposed)return;
      nodes.btnFormat.disabled=busy||!!intent;
      nodes.btnBlind.disabled=busy||!!intent;
      nodes.btnDocx.disabled=busy||!job||!["succeeded","needs_review"].includes(job.state);
      nodes.btnDocx.textContent=job?.state==="needs_review"?"Download for review":"Download DOCX";
    }
    async function refresh(){
      if(!job||disposed)return;
      const current=++seq,jobId=job.job_id;
      const next=await client.status(jobId);
      if(disposed||current!==seq||job?.job_id!==jobId)return;
      job=next;
      nodes.blindBadge.style.display=next.module==="cv_blinding"&&["succeeded","needs_review"].includes(next.state)?"inline-flex":"none";
      display(messages[next.state]);
      controls();
      return next;
    }
    async function submit(blind){
      if(busy||intent||disposed)return;
      busy=true;seq++;job=null;nodes.blindBadge.style.display="none";controls();
      try{
        const moduleName=blind?"cv_blinding":"cv_formatting";
        const opts=readOptions(moduleName);
        const mode=readInputMode();
        if(mode!=="upload"&&mode!=="paste")throw new Error("invalid_input_mode");
        const input=mode==="upload"?nodes.fileInput.files[0]:nodes.cvInput.value;
        display("Uploading source to secure processing queue…");
        const documentId=await client.upload(input);
        if(disposed)return;
        intent=client.prepare(documentId,moduleName,opts);
        const jobId=await client.submit(intent);
        if(disposed)return;
        job={job_id:jobId,state:"queued",module:moduleName};
        intent=null;display(messages.queued);
        await refresh();
      }catch{
        display(intent?"Job submission not confirmed. Do not create another job. Recover using the same request.":"Request not confirmed. Check document history before retrying.");
      }finally{busy=false;controls();}
    }
    async function resumeSubmission(){
      if(!intent||busy||disposed)return;
      busy=true;controls();
      try{
        const jobId=await client.submit(intent);
        if(disposed)return;
        job={job_id:jobId,state:"queued",module:intent.module};
        intent=null;
        await refresh();
      }catch{display("Submission still unconfirmed. No new request ID has been generated.");}
      finally{busy=false;controls();}
    }
    async function download(){
      if(disposed||busy||!job||!["succeeded","needs_review"].includes(job.state))return;
      busy=true;controls();
      try{
        const review=job.state==="needs_review";
        if(review&&!(await confirmReview()))return;
        if(disposed)return;
        const result=await client.download(job.job_id,{review});
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
      disposed=true;seq++;intent=null;job=null;
      nodes.btnFormat.removeEventListener("click",format);
      nodes.btnBlind.removeEventListener("click",blind);
      nodes.btnDocx.removeEventListener("click",download);
      nodes.btnFormat.disabled=true;nodes.btnBlind.disabled=true;nodes.btnDocx.disabled=true;
      nodes.cvInput.value="";nodes.fileInput.value="";nodes.outputBox.textContent="";nodes.stepText.textContent="";nodes.blindBadge.style.display="none";
    }});
  }
  return Object.freeze({bind,IDS,NAV});
});

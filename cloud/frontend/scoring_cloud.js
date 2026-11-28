/* Bind the existing CV Scoring view to the cloud job queue. */
"use strict";
window.CVCloudScoring = Object.freeze({
  bind({document, client}){
    const el = id => document.getElementById(id);
    const status = el("cloudScoringStatus");
    const output = el("appraiserBody");
    const historySelect = el("cloudScoringHistory");
    const run = el("appraiserBtn");
    const clear = el("cloudScoringClear");
    const load = el("cloudScoringLoad");
    const rubric = el("cloudScoringRubric");
    const stateLabels = {queued:"Queued", running:"Processing", failed:"Failed", needs_review:"Needs review", succeeded:"Completed"};
    const evidenceLabels = {evidenced:"Evidence found", partial:"Partial evidence", not_evidenced:"No evidence found"};
    const life = new AbortController();
    const options = {signal:life.signal};
    let current = null, completed = null, intent = null, busy = false, refreshing = false;
    const sources = ["Cv", "Jd"].map(kind => ({
      file:el("appraiser"+kind+"File"), text:el("appraiser"+kind+"Text"),
      drop:el("appraiser"+kind+"Drop"), count:el("appraiser"+kind+"Count"),
      name:el("appraiser"+kind+"Status"), dropped:null
    }));

    function reset(){
      current=null;
      intent=null;
      for(const source of sources){
        source.file.value="";
        source.text.value="";
        source.count.textContent="0 chars";
        source.name.textContent="";
        source.dropped=null;
      }
      rubric.value="";
      output.replaceChildren();
      status.textContent="";
      run.textContent="Run CV Scoring";
    }

    async function history(){
      try{
        const data=await client.scoringReports(null, options);
        if(life.signal.aborted)return;
        const selected=historySelect.value;
        historySelect.replaceChildren();
        for(const job of data.items){
          const item=document.createElement("option");
          item.value=job.job_id;
          item.textContent=new Date(job.created_at).toLocaleString()+" · "+stateLabels[job.state];
          historySelect.append(item);
        }
        if(Array.from(historySelect.options).some(item=>item.value===selected))historySelect.value=selected;
      }catch(error){
        if(error.code==="authentication_required")throw error;
        if(!life.signal.aborted)status.textContent="Recent assessments are unavailable.";
      }
    }

    async function refresh(force=false){
      if(!current||refreshing||(!force&&completed===current))return;
      const job=current;
      refreshing=true;
      try{
        const report=await client.scoringReports(job, options);
        if(life.signal.aborted||job!==current)return;
        status.textContent=stateLabels[report.state]||"Assessment status unavailable";
        if(report.state==="needs_review")status.textContent="This attempt requires review. No assessment is available.";
        const rows=report.assessment?.assessments;
        if(Array.isArray(rows)){
          const sections=rows.map(item=>{
            const section=document.createElement("div");
            section.className="appraiser-panel";
            const heading=document.createElement("h3");
            heading.textContent=item.requirement;
            const label=document.createElement("p");
            label.textContent=evidenceLabels[item.status]||"Evidence unavailable";
            const quote=document.createElement("blockquote");
            quote.textContent=item.quote;
            const note=document.createElement("p");
            note.textContent=item.note;
            section.append(heading,label);
            if(item.quote)section.append(quote);
            section.append(note);
            return section;
          });
          output.replaceChildren(...sections);
          status.textContent="Evidence report ready for recruiter review.";
        }
        if(["failed","needs_review","succeeded"].includes(report.state))completed=job;
      }catch(error){
        if(error.code==="authentication_required")throw error;
        if(!life.signal.aborted&&job===current)status.textContent="Assessment status unavailable. Try loading it from recent assessments.";
      }finally{refreshing=false;}
    }

    async function submit(){
      if(busy)return;
      busy=true;
      run.disabled=true;
      clear.disabled=true;
      try{
        if(!intent){
          const inputs=sources.map(source=>source.text.value.trim()?source.text.value:source.dropped||source.file.files[0]);
          const lines=rubric.value.split(/\r?\n/).map(line=>line.trim()).filter(Boolean);
          if(inputs.some(input=>!input)||lines.length<1||lines.length>30||lines.some(line=>line.length>500)){
            status.textContent="Supply a CV, a job description and one to 30 requirements of up to 500 characters each.";
            return;
          }
          status.textContent="Uploading CV and job description…";
          const [cvId,jdId]=await Promise.all(inputs.map(input=>client.upload(input, options)));
          if(life.signal.aborted)return;
          const criteria=lines.map((requirement,index)=>({id:"requirement-"+(index+1),requirement,required:true}));
          intent=client.prepareScoring(cvId,jdId,criteria);
        }
        current=await client.submitScoring(intent, options);
        intent=null;
        run.textContent="Run CV Scoring";
        output.replaceChildren();
        await refresh(true);
        await history();
      }catch(error){
        if(life.signal.aborted)return;
        if(intent&&["request_unconfirmed","invalid_response"].includes(error.code)){
          status.textContent="Submission unconfirmed. Retry the same request or check recent assessments.";
          run.textContent="Retry assessment submission";
        }else{
          intent=null;
          run.textContent="Run CV Scoring";
          status.textContent="Assessment submission failed. Check the documents and requirements.";
        }
      }finally{
        if(!life.signal.aborted){run.disabled=false;clear.disabled=false;}
        busy=false;
      }
    }

    for(const source of sources){
      source.drop.addEventListener("click",event=>{if(event.target!==source.file)source.file.click();},options);
      source.drop.addEventListener("dragover",event=>event.preventDefault(),options);
      source.drop.addEventListener("drop",event=>{
        event.preventDefault();
        if(!event.dataTransfer.files.length)return;
        source.dropped=event.dataTransfer.files[0];
        source.text.value="";
        source.name.textContent=source.dropped.name;
        source.count.textContent="0 chars";
      },options);
      source.file.addEventListener("change",()=>{
        source.dropped=null;
        source.text.value="";
        source.count.textContent="0 chars";
        source.name.textContent=source.file.files[0]?.name||"";
      },options);
      source.text.addEventListener("input",()=>{source.count.textContent=source.text.value.length+" chars";},options);
    }
    run.addEventListener("click",submit,options);
    clear.addEventListener("click",reset,options);
    load.addEventListener("click",async()=>{
      if(!historySelect.value)return;
      current=historySelect.value;
      completed=null;
      status.textContent="Loading assessment…";
      output.replaceChildren();
      try{await refresh(true);}catch{status.textContent="Sign in again to load assessments.";}
    },options);
    return {history,refresh,dispose(){
      life.abort();
      reset();
      historySelect.replaceChildren();
      run.disabled=false;
      clear.disabled=false;
    }};
  }
});

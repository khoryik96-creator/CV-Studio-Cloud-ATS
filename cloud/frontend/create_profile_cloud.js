/* Stage reviewed CV uploads using the original Create Profile card. */
"use strict";
window.CVCloudCreateProfile = Object.freeze({
  bind({document,client,confirm}){
    const el=id=>document.getElementById(id);
    const picker=el("jaCreateInput");
    const drop=el("jaCreateDrop");
    const list=el("jaCreateList");
    const run=el("btnJACreateAll");
    const clear=el("cloudProfileClear");
    const status=el("jaCreateAllStatus");
    const connection=el("jaCreateConnStatus");
    const audit=el("cloudProfileAudit");
    const life=new AbortController();
    const options={signal:life.signal};
    const terminal=new Set(["succeeded","needs_review","failed"]);
    let rows=[],busy=false,refreshing=false,connected=false;
    const labels={
      preparing:"Preparing review",ready:"Ready for confirmation",queued:"Queued",running:"Processing",
      failed:"Failed",needs_review:"Outcome needs review",succeeded:"Completed",unconfirmed:"Submission unconfirmed"
    };

    function label(report){
      if(report.result?.outcome==="created")return "Profile created and CV uploaded";
      if(report.result?.outcome==="duplicate")return "Duplicate candidate. No upload made.";
      return labels[report.state]||"Status unavailable";
    }
    function update(){
      list.replaceChildren();
      for(const row of rows){
        const item=document.createElement("div");
        item.className="card-body";
        const title=document.createElement("strong");
        title.textContent=row.fileName;
        const description=document.createElement("p");
        description.textContent=row.candidate?[row.candidate.name,row.candidate.email,label(row)].join(" · "):label(row);
        item.append(title,description);
        list.append(item);
      }
      run.disabled=busy||!connected||!rows.some(row=>row.state==="ready"||row.state==="unconfirmed");
      clear.disabled=busy;
    }

    async function prepare(fileList){
      if(busy)return;
      busy=true;
      status.textContent="";
      try{
        const files=Array.from(fileList);
        if(!files.length||files.length+rows.length>10){
          status.textContent="Select up to 10 CVs per batch.";
          return;
        }
        for(const file of files){
          const row={fileName:file.name,state:"preparing"};
          rows.push(row);
          update();
          try{
            const documentId=await client.upload(file,options);
            const review=await client.prepareProfile(documentId,options);
            if(life.signal.aborted)return;
            row.intent=review.intent;row.candidate=review.candidate;row.state="ready";
          }catch(error){
            if(error.code==="authentication_required")throw error;
            row.state="failed";
          }
          update();
        }
      }catch{
        if(!life.signal.aborted)status.textContent="Could not prepare the CVs. Check your session and the files.";
      }finally{
        busy=false;picker.value="";
        if(!life.signal.aborted)update();
      }
    }

    async function submit(){
      if(busy||!connected)return;
      const reviewed=rows.filter(row=>row.state==="ready"||row.state==="unconfirmed");
      if(!reviewed.length||!confirm("Create "+reviewed.length+" reviewed candidate profile(s) and upload their CVs to mocked JobAdder?"))return;
      busy=true;update();
      try{
        for(const row of reviewed){
          try{
            row.jobId=await client.confirmProfile(row.intent,options);
            row.state="queued";
          }catch(error){
            if(error.code==="authentication_required")throw error;
            row.state=["request_unconfirmed","invalid_response"].includes(error.code)?"unconfirmed":"failed";
          }
          if(life.signal.aborted)return;
          update();
        }
        await refresh();
        await history();
      }catch{
        if(!life.signal.aborted)status.textContent="Could not confirm all submissions. Check the JobAdder history.";
      }finally{
        busy=false;
        if(!life.signal.aborted)update();
      }
    }

    async function refresh(){
      if(refreshing||!rows.some(row=>row.jobId&&!terminal.has(row.state)))return;
      refreshing=true;
      try{
        for(const row of rows.filter(item=>item.jobId&&!terminal.has(item.state))){
          const report=await client.profileReports(row.jobId,options);
          if(life.signal.aborted)return;
          row.state=report.state;row.result=report.result;
        }
        update();
      }catch(error){
        if(error.code==="authentication_required")throw error;
        if(!life.signal.aborted)status.textContent="Status temporarily unavailable.";
      }finally{refreshing=false;}
    }

    async function history(){
      try{
        const [settings,history]=await Promise.all([client.profileSettings(options),client.profileReports(null,options)]);
        if(life.signal.aborted)return;
        connected=settings.connected;
        connection.textContent=connected?"Mocked JobAdder connected":"Integration unavailable";
        audit.replaceChildren();
        for(const report of history.items){
          const item=document.createElement("div");
          const text=document.createElement("p");
          text.textContent=[new Date(report.confirmed_at).toLocaleString(),label(report),report.result?.candidate_id].filter(Boolean).join(" · ");
          item.append(text);
          if(report.state==="needs_review"&&report.attempted_at){
            const check=document.createElement("button");
            check.type="button";check.className="sec";check.textContent="Check recorded outcome";
            check.addEventListener("click",async()=>{
              check.disabled=true;
              try{
                const outcome=await client.reconcileProfile(report.job_id,options);
                if(life.signal.aborted)return;
                status.textContent=outcome.result?label(outcome):"No confirmed outcome has been recorded.";
                await history();
              }catch{
                if(!life.signal.aborted)status.textContent="Outcome check unavailable.";
              }finally{
                if(!life.signal.aborted)check.disabled=false;
              }
            },options);
            item.append(check);
          }
          audit.append(item);
        }
        update();
      }catch(error){
        if(error.code==="authentication_required")throw error;
        if(!life.signal.aborted){
          connected=false;
          connection.textContent="Integration status unavailable";
          update();
        }
      }
    }

    drop.addEventListener("click",event=>{if(event.target!==picker&&!busy)picker.click();},options);
    drop.addEventListener("dragover",event=>event.preventDefault(),options);
    drop.addEventListener("drop",event=>{event.preventDefault();prepare(event.dataTransfer.files);},options);
    picker.addEventListener("change",()=>prepare(picker.files),options);
    run.addEventListener("click",submit,options);
    clear.addEventListener("click",()=>{rows=[];status.textContent="";update();},options);
    el("cloudProfileHistory").addEventListener("click",()=>history().catch(()=>{
      if(!life.signal.aborted)status.textContent="Sign in again to view history.";
    }),options);
    update();
    return {refresh,history,dispose(){
      life.abort();
      rows=[];audit.replaceChildren();connected=false;
      picker.value="";connection.textContent="Not connected";status.textContent="";
      update();
    }};
  }
});

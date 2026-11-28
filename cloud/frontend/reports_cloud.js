/* Connect the original Company Profile and Blind JD panels to durable reports. */
"use strict";
window.CVCloudReports = Object.freeze({
  bind({document, client, key}){
    const el = id => document.getElementById(id);
    const company = key==="Company";
    const module = company?"company-profile":"blind-jd";
    const body = el(company?"companyBody":"anonJDBody");
    const output = el(company?"companyOutput":"anonJDOutput");
    const placeholder = el(company?"companyPlaceholder":"anonJDPlaceholder");
    const source = el(company?"companyText":"anonRawText");
    const button = el(company?"btnGenerateCompany":"btnAnonJD");
    const status = el(company?"companyStatus":"anonJDStatus");
    const clear = el("cloudClear"+key);
    const select = el("cloudHistory"+key);
    const life = new AbortController();
    const options = {signal:life.signal};
    const runLabel = button.textContent;
    const labels = {queued:"Queued", running:"Processing", succeeded:"Ready for human review", failed:"Failed", needs_review:"Processing requires review"};
    const groups = {length:["concise","standard","detailed"],tone:["professional","conversational","punchy"],
      focus:["general","tech","culture","finance"]};
    const selected = {length:"concise",tone:"professional",focus:"general"};
    let current=null, completed=null, intent=null, file=null, busy=false, polling=false;
    const lines = value => value.split(/\r?\n/).map(line=>line.trim()).filter(Boolean);
    const inputs = company?[source]:[source,el("anonCompanyName"),el("cloudJDIdentifiers"),el("cloudJDTechnologies")];

    function show(node, tag, value){
      const child=document.createElement(tag);
      child.textContent=value;
      node.append(child);
    }
    function clearResult(){
      body.replaceChildren();
      output.style.display="none";
      placeholder.style.display="";
    }
    function render(result){
      body.replaceChildren();
      if(company){
        show(body,"h3",result.company_name);
        const citations=new Map(result.sources.map(item=>[item.id,item]));
        for(const claim of result.claims){
          show(body,"p",claim.text);
          for(const evidence of claim.evidence){
            const citation=citations.get(evidence.source_id);
            show(body,"blockquote",evidence.quote);
            show(body,"small",[citation.title,citation.url,citation.retrieved_on].filter(Boolean).join(" · "));
          }
        }
        for(const limitation of result.limitations)show(body,"p",limitation);
      }else{
        const jd=result.report;
        const fields={job_title:"Job title",about_client:"About the employer",about_role:"About the role",
          industry:"Industry",work_mode:"Work mode",location:"Location",tech_stack:"Technology",
          responsibilities:"Responsibilities",requirements:"Requirements",nice_to_have:"Nice to have",why_join:"Why join",alt_titles:"Alternative titles"};
        for(const [field,label] of Object.entries(fields)){
          const value=jd[field];
          if(!value?.length)continue;
          show(body,"h3",label);
          if(typeof value==="string")show(body,"p",value);
          else{
            const list=document.createElement("ul");
            for(const item of value)show(list,"li",item);
            body.append(list);
          }
        }
      }
      output.style.display="";
      placeholder.style.display="none";
    }
    async function refresh(force=false){
      if(!current||polling||(!force&&current===completed))return;
      const job=current;
      polling=true;
      try{
        const report=await client.documentReports(module,job,options);
        if(job!==current||life.signal.aborted)return;
        status.textContent=labels[report.state]||"Report unavailable";
        if(report.result)render(report.result);
        if(["failed","needs_review","succeeded"].includes(report.state))completed=job;
      }catch(error){
        if(error.code==="authentication_required")throw error;
        if(!life.signal.aborted)status.textContent="Report status unavailable.";
      }finally{polling=false;}
    }
    async function history(){
      try{
        const reports=await client.documentReports(module,null,options);
        if(life.signal.aborted)return;
        const previous=select.value;
        select.replaceChildren();
        for(const item of reports.items){
          const option=document.createElement("option");
          option.value=item.job_id;
          option.textContent=new Date(item.created_at).toLocaleString()+" · "+labels[item.state];
          select.append(option);
        }
        if(Array.from(select.options).some(item=>item.value===previous))select.value=previous;
      }catch(error){
        if(error.code==="authentication_required")throw error;
        if(!life.signal.aborted)status.textContent="Recent reports unavailable.";
      }
    }
    function reset(){
      current=null;completed=null;intent=null;file=null;
      for(const input of inputs)input.value="";
      if(!company){
        el("anonFileInput").value="";
        el("anonFileName").textContent="";
        el("anonOriginalPreview").textContent="";
        el("anonCharCount").textContent="0 chars";
      }
      status.textContent="";
      button.textContent=runLabel;
      clearResult();
    }
    async function submit(){
      if(busy)return;
      busy=true;button.disabled=true;clear.disabled=true;
      try{
        if(!intent){
          const text=source.value.trim();
          const input=text||(company?null:file);
          const identifiers=company?[]:[el("anonCompanyName").value.trim(),...lines(el("cloudJDIdentifiers").value)].filter(Boolean);
          if(!input||(!company&&!identifiers.length)){
            status.textContent=company?"Enter the company name.":"Supply the JD and an employer identifier.";
            return;
          }
          const params=company?{...selected}:{identifiers,technologies:lines(el("cloudJDTechnologies").value)};
          const documentId=await client.upload(input,options);
          if(life.signal.aborted)return;
          intent=client.prepareReport(documentId,params);
        }
        current=await client.submitReport(module,intent,options);
        intent=null;
        button.textContent=runLabel;
        clearResult();
        await refresh(true);
        await history();
      }catch(error){
        if(life.signal.aborted)return;
        if(intent&&["request_unconfirmed","invalid_response"].includes(error.code)){
          status.textContent="Submission unconfirmed. Retry the same request or check recent reports.";
          button.textContent="Retry submission";
        }else{
          intent=null;
          status.textContent="Submission failed. Check the inputs and try again.";
          button.textContent=runLabel;
        }
      }finally{
        busy=false;
        if(!life.signal.aborted){button.disabled=false;clear.disabled=false;}
      }
    }
    if(company){
      const prefixes={length:"Len",tone:"Tone",focus:"Focus"};
      for(const [group,choices] of Object.entries(groups)){
        for(const value of choices){
          const control=el("company"+prefixes[group]+"_"+value);
          const highlight=()=>{
            for(const choice of choices){
              const option=el("company"+prefixes[group]+"_"+choice);
              const active=selected[group]===choice;
              option.setAttribute("aria-pressed",String(active));
              option.style.background=active?"var(--blue)":"";
              option.style.color=active?"#fff":"";
              option.style.borderColor=active?"var(--blue)":"";
            }
          };
          control.addEventListener("click",()=>{selected[group]=value;highlight();},options);
          highlight();
        }
      }
    }else{
      const drop=el("anonDropZone"), picker=el("anonFileInput");
      const setFile=value=>{
        file=value;
        source.value="";
        el("anonFileName").textContent=file?.name||"";
        el("anonOriginalPreview").textContent=file?file.name:"";
        el("anonCharCount").textContent="0 chars";
      };
      drop.addEventListener("click",event=>{if(event.target!==picker)picker.click();},options);
      drop.addEventListener("dragover",event=>event.preventDefault(),options);
      drop.addEventListener("drop",event=>{event.preventDefault();setFile(event.dataTransfer.files[0]);},options);
      picker.addEventListener("change",()=>setFile(picker.files[0]),options);
      source.addEventListener("input",()=>{
        el("anonOriginalPreview").textContent=source.value;
        el("anonCharCount").textContent=source.value.length+" chars";
      },options);
    }
    button.addEventListener("click",submit,options);
    clear.addEventListener("click",reset,options);
    el("cloudLoad"+key).addEventListener("click",async()=>{
      if(!select.value)return;
      current=select.value;
      completed=null;
      status.textContent="Loading report…";
      clearResult();
      try{await refresh(true);}catch{status.textContent="Sign in again to load the report.";}
    },options);
    return {refresh,history,dispose(){
      life.abort();
      reset();
      select.replaceChildren();
      button.disabled=false;
      clear.disabled=false;
    }};
  }
});

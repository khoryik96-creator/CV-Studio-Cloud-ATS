/* Original batch controls, cloud-only orchestration. No desktop APIs. */
(function(root,factory){
 const api=factory();
 if(typeof module==="object"&&module.exports)module.exports=api;else root.CVCloudBatch=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
 "use strict";
 const TERMINAL=new Set(["succeeded","needs_review","failed"]);
 const LABELS={ready:"Ready",uploading:"Uploading",upload_unconfirmed:"Upload unconfirmed — reconcile history before submitting again",preparation_failed:"Document uploaded; preparation failed",submitting:"Submitting",submit_unconfirmed:"Submission unconfirmed — recover same request",queued:"Queued",running:"Processing",succeeded:"Completed",needs_review:"Human review required",failed:"Failed"};
 // Each row has a distinct identity, even for duplicate file names.
 function create({client,validateSource,changed=()=>{}}){
   let rows=[],busy=false,closed=false,refreshing=false;
   const life=new AbortController();
   const notify=()=>{if(!closed)changed();};
   const snapshot=()=>rows.map(({name,state,jobId},index)=>({name,state,jobId,index}));
   function select(files){
     if(closed||busy||rows.length)throw Error("Clear existing batch first");
     const all=Array.from(files);
     if(!all.length||all.length>10)throw Error("Select 1–10 files");
     for(const file of all)validateSource(file);
     rows=all.map(file=>({file,name:file.name,state:"ready",jobId:null,intent:null,doc:null,module:null,options:null}));
     notify();
   }
   async function submit(row){
     if(closed)return;
     row.state="submitting";notify();
     try{
       const jobId=await client.submit(row.intent,{signal:life.signal});
       if(closed)return;
       row.jobId=jobId;row.state="queued";row.file=null;
     }catch{if(!closed)row.state="submit_unconfirmed";}
     notify();
   }
   async function start(module,options){
     if(closed||busy||!rows.length||rows.some(x=>x.state!=="ready"))return;
     busy=true;notify();
     try{
       for(const row of rows){
         if(closed)break;
         row.module=module;row.options={...options};row.state="uploading";notify();
         try{
           row.doc=await client.upload(row.file,{signal:life.signal});
         }catch{if(!closed){row.state="upload_unconfirmed";notify();}break;}
         if(closed)break;
         try{row.intent=client.prepare(row.doc,module,row.options);}
         catch{row.state="preparation_failed";notify();break;}
         await submit(row);
         // Never automatically repeat an uncertain upload or submission.
         if(row.state!=="queued")break;
       }
     }finally{busy=false;notify();}
   }
   async function recover(index){
     const row=rows[index];
     if(closed||busy||!row||row.state!=="submit_unconfirmed"||!row.intent)return;
     busy=true;notify();
     try{await submit(row);}finally{busy=false;notify();}
   }
   async function refresh(){
     if(closed||busy||refreshing)return;
     refreshing=true;
     try{
       for(const row of rows){
         if(closed)break;
         if(!row.jobId||TERMINAL.has(row.state))continue;
         const status=await client.status(row.jobId,{signal:life.signal});
         if(closed)break;
         if(status.job_id!==row.jobId||status.module!==row.module||status.document_id!==row.doc)throw Error("Batch job identity mismatch");
         row.state=status.state;notify();
       }
     }finally{refreshing=false;}
   }
   async function download(index,confirmReview,save){
     const row=rows[index];
     if(closed||busy||!row?.jobId||!["succeeded","needs_review"].includes(row.state))return;
     busy=true;notify();
     try{
       const review=row.state==="needs_review";
       if(review&&(await confirmReview())!==true)return;
       if(closed)return;
       const result=await client.download(row.jobId,{review,signal:life.signal});
       if(!closed)await save({...result,filename:"cv-"+String(index+1).padStart(2,"0")+(result.requiresReview?"-review":"")+".docx"});
     }finally{busy=false;notify();}
   }
   function clear(){
     if(closed||busy||refreshing||rows.some(x=>!TERMINAL.has(x.state)&&x.state!=="ready"))return false;
     rows=[];notify();return true;
   }
   return {select,start,recover,refresh,download,clear,snapshot,isBusy:()=>busy,dispose(){closed=true;life.abort();rows=[];}};
 }
 function bind({document,client,readOptions,confirmReview,saveDocument}){
   const el=id=>document.getElementById(id);
   const input=el("batchFileInput"),drop=el("batchDropZone"),list=el("batchFileList"),run=el("btnBatchRun"),clear=el("cloudBatchClear"),summary=el("batchSummary"),format=el("batchTabFormat"),blind=el("batchTabBlind"),panel=el("batchControls");
   if([input,drop,list,run,clear,summary,format,blind,panel].some(x=>!x))throw Error("Batch controls missing");
   let module="cv_formatting",disposed=false,notice="";
   const listeners=[];
   function on(node,event,fn){node.addEventListener(event,fn);listeners.push([node,event,fn]);}
   const core=create({client,validateSource:CVCloudClient.source,changed:render});
   function render(){
     if(disposed)return;
     const rows=core.snapshot(),busy=core.isBusy();
     list.textContent="";
     for(const row of rows){
       const item=document.createElement("div");item.className="batch-file-item";
       const name=document.createElement("span");name.textContent=row.name;item.append(name);
       const state=document.createElement("span");state.textContent=" — "+LABELS[row.state];item.append(state);
       if(["succeeded","needs_review","submit_unconfirmed"].includes(row.state)){
         const b=document.createElement("button");b.type="button";b.className="sec";b.disabled=busy;
         b.textContent=row.state==="submit_unconfirmed"?"Recover submission":row.state==="needs_review"?"Download for review":"Download DOCX";
         b.addEventListener("click",async()=>{try{if(row.state==="submit_unconfirmed")await core.recover(row.index);else await core.download(row.index,confirmReview,saveDocument);}catch{notice="Request unavailable; check status and try again.";render();}});
         item.append(b);
       }
       list.append(item);
     }
     panel.style.display=rows.length||notice?"flex":"none";
     summary.textContent=notice||rows.filter(x=>TERMINAL.has(x.state)).length+" / "+rows.length+" finished";
     run.disabled=busy||!rows.length||rows.some(x=>x.state!=="ready");
     clear.disabled=busy||rows.some(x=>!TERMINAL.has(x.state)&&x.state!=="ready");
     input.disabled=busy||rows.length>0;
     format.disabled=blind.disabled=busy||rows.some(x=>x.state!=="ready");
     format.classList.toggle("active",module==="cv_formatting");
     blind.classList.toggle("active",module==="cv_blinding");
   }
   function choose(files){notice="";try{core.select(files);}catch{notice="Select 1–10 supported non-empty files, up to 32 MB each. Clear the existing batch first.";render();}input.value="";}
   on(input,"change",()=>choose(input.files));
   on(drop,"click",e=>{if(e.target!==input&&!input.disabled)input.click();});
   on(drop,"dragover",e=>e.preventDefault());
   on(drop,"drop",e=>{e.preventDefault();if(!input.disabled)choose(e.dataTransfer.files);});
   on(format,"click",()=>{module="cv_formatting";render();});
   on(blind,"click",()=>{module="cv_blinding";render();});
   on(run,"click",async()=>{notice="";try{await core.start(module,readOptions(module));}catch{notice="Batch interrupted; check each row.";render();}});
   on(clear,"click",()=>{notice="";core.clear();render();});
   render();
   return {refresh:core.refresh,dispose(){disposed=true;core.dispose();for(const [n,e,f] of listeners)n.removeEventListener(e,f);input.value="";input.disabled=true;list.textContent="";summary.textContent="";panel.style.display="none";}};
 }
 return {create,bind};
});

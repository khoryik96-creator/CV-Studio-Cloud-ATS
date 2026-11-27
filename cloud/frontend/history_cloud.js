/* Read-only current-owner history; never re-submit a job or restore source CVs. */
(function(root,factory){
 const api=factory();
 if(typeof module==="object"&&module.exports)module.exports=api;else root.CVCloudHistory=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
 "use strict";
 const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
 const STATES=new Set(["queued","running","succeeded","failed","needs_review"]);
 const TYPES={"text/plain":"TXT","application/pdf":"PDF","application/vnd.openxmlformats-officedocument.wordprocessingml.document":"DOCX"};
 const validId=v=>typeof v==="string"&&UUID.test(v);
 const date=v=>typeof v==="string"&&v.length<=40&&Number.isFinite(Date.parse(v));
 const labels={queued:"Queued",running:"Processing",succeeded:"Completed",failed:"Failed",needs_review:"Needs human review"};
 function validate(kind,value){
   if(!["jobs","documents"].includes(kind)||!value||!Array.isArray(value.items)||value.items.length>25||
      !(value.next_cursor===null||validId(value.next_cursor)))throw Error("invalid_history");
   const items=value.items.map(x=>{
     if(!x||!validId(x.document_id)||!date(x.created_at))throw Error("invalid_history_row");
     if(kind==="jobs"){
       if(!validId(x.job_id)||!["cv_formatting","cv_blinding"].includes(x.module)||!STATES.has(x.state)||
          !date(x.updated_at)||typeof x.output_available!=="boolean"||
          (x.output_available&&!["succeeded","needs_review"].includes(x.state)))throw Error("invalid_job_history");
       return {job_id:x.job_id,document_id:x.document_id,module:x.module,state:x.state,created_at:x.created_at,updated_at:x.updated_at,output_available:x.output_available};
     }
     if(typeof x.media_type!=="string"||!Object.hasOwn(TYPES,x.media_type)||!Number.isInteger(x.byte_size)||x.byte_size<1||x.byte_size>33554432||typeof x.has_jobs!=="boolean")throw Error("invalid_document_history");
     return {document_id:x.document_id,media_type:x.media_type,byte_size:x.byte_size,created_at:x.created_at,has_jobs:x.has_jobs};
   });
   const key=kind==="jobs"?"job_id":"document_id";
   if(new Set(items.map(x=>x[key])).size!==items.length||
      (value.next_cursor!==null&&(!items.length||items[items.length-1][key]!==value.next_cursor)))throw Error("invalid_history_cursor");
   return {items,next_cursor:value.next_cursor};
 }
 function bind({document,client,confirmReview,saveDocument,onAuthLost}){
   const el=id=>document.getElementById(id);
   const toggle=el("cloudHistoryToggle"),panel=el("cloudHistoryPanel"),close=el("cloudHistoryClose"),jobs=el("cloudHistoryJobs"),docs=el("cloudHistoryDocuments"),refresh=el("cloudHistoryRefresh"),older=el("cloudHistoryNext"),list=el("cloudHistoryList"),status=el("cloudHistoryStatus");
   if([toggle,panel,close,jobs,docs,refresh,older,list,status].some(x=>!x))throw Error("History controls missing");
   let dead=false,open=false,busy=false,kind="jobs",cursor=null,generation=0;
   const life=new AbortController(),listeners=[];
   function on(node,event,fn){node.addEventListener(event,fn);listeners.push([node,event,fn]);}
   function current(epoch){return !dead&&open&&epoch===generation;}
   function controls(){jobs.disabled=docs.disabled=refresh.disabled=busy;older.disabled=busy||!cursor;}
   function error(e,epoch){if(!current(epoch))return;list.textContent="";cursor=null;if(e.code==="authentication_required"){onAuthLost();return;}status.textContent="History unavailable. Refresh and try again.";}
   function text(parent,value,tag="p"){const node=document.createElement(tag);node.textContent=value;parent.append(node);return node;}
   async function output(row,action,button,epoch){
     if(!current(epoch)||busy)return;
     busy=true;controls();button.disabled=true;
     try{
       const review=row.state==="needs_review"||row.module==="cv_blinding";
       if(review&&(await confirmReview())!==true)return;
       if(!current(epoch))return;
       const result=await client[action](row.job_id,{review,signal:life.signal});
       if(!current(epoch))return;
       if(action==="download")await saveDocument(result);
       else{
         const preview=document.createElement("div");preview.className="output-box";
         text(preview,result.requires_review?"Human review required — do not distribute":"Output text preview");
         for(const line of result.paragraphs)text(preview,line);
         const prior=list.querySelector(".cloud-history-preview");if(prior)prior.remove();
         preview.classList.add("cloud-history-preview");list.append(preview);
       }
     }catch(e){error(e,epoch);}
     finally{busy=false;if(!dead){button.disabled=false;controls();}}
   }
   function render(items,epoch){
     list.textContent="";
     for(const row of items){
       const item=document.createElement("div");item.className="batch-file-item";
       if(kind==="jobs"){
         text(item,(row.module==="cv_blinding"?"Blind CV":"Format CV")+" · "+labels[row.state],"strong");
         text(item,"Job: "+row.job_id+" · Document: "+row.document_id);
         text(item,"Created "+new Date(row.created_at).toLocaleString()+" · Updated "+new Date(row.updated_at).toLocaleString());
         if(row.output_available){
           for(const action of ["preview","download"]){
             const b=document.createElement("button");b.type="button";b.className="sec";
             b.textContent=action==="preview"?"Preview":"Download DOCX";
             b.addEventListener("click",()=>output(row,action,b,epoch));item.append(b);
           }
         }
       }else{
         text(item,TYPES[row.media_type]+" · "+Math.ceil(row.byte_size/1024)+" KB · "+(row.has_jobs?"Has processing history":"No recorded job"),"strong");
         text(item,"Document: "+row.document_id+" · Uploaded "+new Date(row.created_at).toLocaleString());
       }
       list.append(item);
     }
   }
   async function load(next=false){
     if(dead||!open||busy)return;
     const epoch=++generation,before=next?cursor:null;
     busy=true;cursor=null;list.textContent="";status.textContent="Loading history…";controls();
     try{
       const result=validate(kind,await client.history(kind,{before,signal:life.signal}));
       if(!current(epoch))return;
       cursor=result.next_cursor;render(result.items,epoch);
       status.textContent=result.items.length?result.items.length+" records on this page":"No records found.";
     }catch(e){error(e,epoch);}
     finally{busy=false;if(!dead)controls();}
   }
   function hide(){open=false;generation++;cursor=null;list.textContent="";status.textContent="";panel.style.display="none";controls();}
   function dispose(){if(dead)return;hide();dead=true;life.abort();toggle.style.display="none";for(const [n,e,f] of listeners)n.removeEventListener(e,f);}
   on(toggle,"click",()=>{if(open){hide();return;}if(busy)return;open=true;kind="jobs";panel.style.display="";load();});
   on(close,"click",hide);
   on(jobs,"click",()=>{kind="jobs";load();});
   on(docs,"click",()=>{kind="documents";load();});
   on(refresh,"click",()=>load());
   on(older,"click",()=>{if(cursor)load(true);});
   hide();toggle.style.display="";
   return {dispose};
 }
 return {bind,validate};
});

/* Cloud-only transport for the existing CV Studio controls.
 * Explicit API allowlist, no desktop credential/local-storage migration,
 * no global fetch interception and no automatic paid-job resubmission.
 * This file is not served or initialized by the default cloud app.
 */
(function(root,factory){
  const exported=factory();
  if(typeof module==="object"&&module.exports)module.exports=exported;
  else root.CVCloudClient=exported;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";
  const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const TYPES=Object.freeze({pdf:"application/pdf",docx:"application/vnd.openxmlformats-officedocument.wordprocessingml.document",txt:"text/plain"});
  const STATES=new Set(["queued","running","succeeded","failed","needs_review"]);
  const MAX_BYTES=32*1024*1024;
  class CloudError extends Error{
    constructor(code){super(code);this.name="CloudError";this.code=code;}
  }
  function id(value){
    if(typeof value!=="string"||!UUID.test(value))throw new CloudError("invalid_identifier");
    return value.toLowerCase();
  }
  function options(moduleName,value={}){
    if(!["cv_formatting","cv_blinding"].includes(moduleName)||!value||typeof value!=="object"||Array.isArray(value))throw new CloudError("unsupported_module");
    if(Object.keys(value).some(k=>!["alignment","correct_language","neutral_gender"].includes(k)))throw new CloudError("unsupported_option");
    const {alignment="left",correct_language=false,neutral_gender=false}=value;
    if(!["left","justify"].includes(alignment)||typeof correct_language!=="boolean"||typeof neutral_gender!=="boolean"||(moduleName!=="cv_blinding"&&neutral_gender))throw new CloudError("invalid_options");
    return {alignment,correct_language,neutral_gender};
  }
  function source(input){
    if(typeof input==="string"){
      if(!input.trim())throw new CloudError("empty_source");
      const body=new Blob([input],{type:TYPES.txt});
      if(body.size>MAX_BYTES)throw new CloudError("source_too_large");
      return {body,type:TYPES.txt};
    }
    if(!(input instanceof Blob)||typeof input.name!=="string"||!input.size||input.size>MAX_BYTES)throw new CloudError("invalid_file");
    const ext=input.name.split(".").pop().toLowerCase();
    if(!Object.hasOwn(TYPES,ext))throw new CloudError("unsupported_file");
    return {body:input,type:TYPES[ext]};
  }
  function create({fetcher,uuid}){
    if(typeof fetcher!=="function"||typeof uuid!=="function")throw new TypeError("Trusted transport required");
    let session=null,epoch=0;
    const active=()=>{if(!session)throw new CloudError("authentication_required");return epoch;};
    function clear(){session=null;epoch++;}
    async function request(path,{method="GET",body,contentType,write=false,expected=epoch,signal,allowUnauthorized=false}={}){
      if(expected!==epoch)throw new CloudError("stale_session");
      const headers={};
      if(contentType)headers["Content-Type"]=contentType;
      if(write){active();headers["X-CSRF-Token"]=session.csrf;}
      let response;
      try{response=await fetcher(path,{method,headers,body,signal,credentials:"same-origin",cache:"no-store",redirect:"error"});}
      catch(e){throw new CloudError(expected!==epoch?"stale_session":signal?.aborted?"request_aborted":"request_unconfirmed");}
      if(expected!==epoch)throw new CloudError("stale_session");
      if(response.status===401){clear();if(!allowUnauthorized)throw new CloudError("authentication_required");}
      if(!response.ok)throw new CloudError(response.status===409?"conflict_or_review_required":response.status===404?"not_found":response.status===413?"source_too_large":response.status===403?"forbidden":"request_rejected");
      return response;
    }
    async function json(path,params){
      const expected=params?.expected??epoch;
      const response=await request(path,{...params,expected});
      let value;
      try{value=await response.json();}catch{throw new CloudError("invalid_response");}
      if(expected!==epoch)throw new CloudError("stale_session");
      if(!value||typeof value!=="object"||Array.isArray(value))throw new CloudError("invalid_response");
      return value;
    }
    async function hydrate(){
      clear();
      const expected=epoch;
      const value=await json("/api/auth/me",{expected});
      if(typeof value.csrf!=="string"||!value.csrf||value.csrf.length>256||!["owner","admin","recruiter"].includes(value.role))throw new CloudError("invalid_session");
      session={csrf:value.csrf,role:value.role};
      return {role:session.role};
    }
    async function logout(){
      const expected=active();
      await json("/api/auth/logout",{method:"POST",write:true,expected});
      if(expected===epoch)clear();
    }
    async function upload(input,{signal}={}){
      const expected=active(),data=source(input);
      const value=await json("/api/documents",{method:"POST",body:data.body,contentType:data.type,write:true,expected,signal});
      return id(value.document_id);
    }
    function prepare(documentId,moduleName,value={}){
      active();
      return Object.freeze({document_id:id(documentId),module:moduleName,idempotency_key:id(uuid()),...options(moduleName,value)});
    }
    async function submit(intent,{signal}={}){
      const expected=active();
      if(!intent||typeof intent!=="object"||Object.keys(intent).some(k=>!["document_id","module","idempotency_key","alignment","correct_language","neutral_gender"].includes(k)))throw new CloudError("invalid_intent");
      const payload={document_id:id(intent.document_id),module:intent.module,idempotency_key:id(intent.idempotency_key),...options(intent.module,{alignment:intent.alignment,correct_language:intent.correct_language,neutral_gender:intent.neutral_gender})};
      const response=await json("/api/jobs",{method:"POST",contentType:"application/json",body:JSON.stringify(payload),write:true,expected,signal});
      return id(response.job_id);
    }
    async function history(kind,{before=null,limit=25,signal}={}){
      const expected=active();
      if(!["jobs","documents"].includes(kind)||!Number.isInteger(limit)||limit<1||limit>50)throw new CloudError("invalid_history");
      const cursor=before===null?"":"&before="+id(before);
      return json("/api/"+kind+"?limit="+limit+cursor,{expected,signal});
    }
    async function status(jobId,{signal}={}){
      const expected=active(),job=id(jobId);
      const value=await json("/api/jobs/"+job,{expected,signal});
      if(id(value.job_id)!==job||!STATES.has(value.state)||!["cv_formatting","cv_blinding"].includes(value.module))throw new CloudError("invalid_job_state");
      return Object.freeze({job_id:job,module:value.module,state:value.state,document_id:id(value.document_id)});
    }
    async function preview(jobId,{review=false,signal}={}){
      const expected=active(),job=id(jobId);
      if(typeof review!=="boolean")throw new CloudError("invalid_review_option");
      const value=await json("/api/jobs/"+job+"/preview"+(review?"?review=1":""),{expected,signal});
      if(id(value.job_id)!==job||typeof value.requires_review!=="boolean"||
         (value.requires_review&&!review)||!Array.isArray(value.paragraphs)||
         value.paragraphs.length>2000||value.paragraphs.some(p=>typeof p!=="string"||p.length>20000)||
         value.paragraphs.reduce((n,p)=>n+p.length,0)>200000)throw new CloudError("invalid_preview");
      return value;
    }
    async function download(jobId,{review=false,signal}={}){
      const expected=active(),job=id(jobId);
      if(typeof review!=="boolean")throw new CloudError("invalid_review_option");
      const response=await request("/api/jobs/"+job+"/download"+(review?"?review=1":""),{expected,signal});
      if(response.headers.get("Content-Type")?.split(";")[0]!==TYPES.docx)throw new CloudError("invalid_document_response");
      const flag=response.headers.get("X-CV-Review-Required");
      if(flag!=="0"&&flag!=="1")throw new CloudError("invalid_review_flag");
      if(flag==="1"&&!review)throw new CloudError("review_required");
      const blob=await response.blob();
      if(expected!==epoch)throw new CloudError("stale_session");
      if(!blob.size||blob.size>MAX_BYTES)throw new CloudError("invalid_document_response");
      return {blob,requiresReview:flag==="1",filename:flag==="1"?"cv-review.docx":"cv.docx"};
    }
    return Object.freeze({hydrate,logout,clear,upload,prepare,submit,status,preview,download,history});
  }
  return Object.freeze({create,CloudError,options,source});
});

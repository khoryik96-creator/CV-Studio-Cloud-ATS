"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs");
const {create}=require("../cloud/frontend/cv_client.js");
const {bind,IDS,NAV}=require("../cloud/frontend/existing_cv_controls.js");
const DOC="11111111-1111-4111-8111-111111111111",JOB="22222222-2222-4222-8222-222222222222",KEY="33333333-3333-4333-8333-333333333333";
const MIME="application/vnd.openxmlformats-officedocument.wordprocessingml.document";
function response(body,status=200,headers={}){return new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json",...headers}});}
(async()=>{
 const html=fs.readFileSync("index.html","utf8");
 for(const name of IDS)assert.ok(html.includes('id="'+name+'"'),name);
 for(const suffix of Object.values(NAV)){assert.ok(html.includes('id="tab'+suffix+'"'));assert.ok(html.includes('id="view'+suffix+'"'));}
 const calls=[];let rejectJob=true,forbid=false,scoringAttempt=0;
 const client=create({uuid:()=>KEY,fetcher:async(path,init)=>{
   calls.push({path,init});
   assert.equal(init.credentials,"same-origin");assert.equal(init.redirect,"error");assert.equal(init.cache,"no-store");
   if(path==="/api/auth/me")return response({role:"recruiter",csrf:"fictional-csrf"});
   if(path==="/api/documents"){assert.equal(init.headers["X-CSRF-Token"],"fictional-csrf");return response({document_id:DOC},201);}
   if(path==="/api/jobs"){if(rejectJob){rejectJob=false;throw Error("network");}return response({job_id:JOB},202);}
   if(path==="/api/scoring/jobs"){
     scoringAttempt++;
     if(scoringAttempt===1)return response({},502);
     if(scoringAttempt===2)return response({job_id:"bad"},202);
     return response({job_id:JOB},202);
   }
   if(path==="/api/jobs/"+JOB)return response({job_id:JOB,document_id:DOC,module:"cv_blinding",state:"needs_review"},forbid?401:200);
   if(path==="/api/jobs/"+JOB+"/preview?review=1")return response({job_id:JOB,requires_review:true,paragraphs:["Fictional <script>"]});
   if(path==="/api/jobs/"+JOB+"/preview")return response({},409);
   if(path==="/api/jobs/"+JOB+"/download?review=1")return new Response(new Blob(["fictional-word"]),{headers:{"Content-Type":MIME,"X-CV-Review-Required":"1"}});
   if(path==="/api/jobs/"+JOB+"/download")return response({},409);
   throw Error("unexpected request");
 }});
 await assert.rejects(client.upload("CV"),/authentication_required/);
 await client.hydrate();
 await assert.rejects(client.upload(Object.assign(new Blob(["x"]),{name:"bad.exe"})),/unsupported_file/);
 const d=await client.upload("Fictional engineer");
 assert.equal(d,DOC);
 assert.throws(()=>client.prepare(d,"jobadder"),/unsupported_module/);
 assert.throws(()=>client.prepare(d,"cv_formatting",{neutral_gender:true}),/invalid_options/);
 const intent=client.prepare(d,"cv_blinding",{alignment:"justify"});
 await assert.rejects(client.submit(intent),/request_unconfirmed/);
 assert.equal(calls.filter(x=>x.path==="/api/jobs").length,1);
 assert.equal(await client.submit(intent),JOB);
 const submissions=calls.filter(x=>x.path==="/api/jobs");
 assert.equal(submissions[0].init.body,submissions[1].init.body);
 const scoring=client.prepareScoring(d,"44444444-4444-4444-8444-444444444444",
   [{id:"cloud",requirement:"Cloud operations",required:true}]);
 await assert.rejects(client.submitScoring(scoring),/request_unconfirmed/);
 await assert.rejects(client.submitScoring(scoring),/invalid_response/);
 assert.equal(await client.submitScoring(scoring),JOB);
 const scoringCalls=calls.filter(x=>x.path==="/api/scoring/jobs");
 assert.equal(scoringCalls.length,3);
 assert.ok(scoringCalls.every(x=>x.init.body===scoringCalls[0].init.body));
 assert.equal((await client.status(JOB)).state,"needs_review");
 await assert.rejects(client.preview(JOB),/conflict_or_review_required/);
 assert.equal((await client.preview(JOB,{review:true})).paragraphs[0],"Fictional <script>");
 await assert.rejects(client.download(JOB),/conflict_or_review_required/);
 assert.equal((await client.download(JOB,{review:true})).filename,"cv-review.docx");
 forbid=true;await assert.rejects(client.status(JOB),/authentication_required/);
 await assert.rejects(client.status(JOB),/authentication_required/);
 const nodes=Object.fromEntries(IDS.map(k=>[k,{value:"Fictional CV",style:{},files:[],hasAttribute:()=>false,addEventListener(t,fn){this.listener=fn;},removeEventListener(){this.listener=null;}}]));
 const fakeDoc={getElementById:k=>nodes[k]};
 let submissionsCount=0,downloads=0,review=false;
 const fakeClient={upload:async()=>DOC,prepare:()=>({idempotency_key:KEY}),submit:async()=>{submissionsCount++;if(submissionsCount===1)throw Error("unconfirmed");return JOB;},status:async()=>({job_id:JOB,module:"cv_blinding",state:"needs_review"}),download:async()=>({blob:new Blob(["word"]),requiresReview:true})};
 const args={document:fakeDoc,client:fakeClient,readOptions:()=>({}),readInputMode:()=>"paste",saveDocument:async()=>downloads++,confirmReview:async()=>review};
 nodes.btnFormat.onclick=()=>{};assert.throws(()=>bind(args),/Remove desktop handlers/);delete nodes.btnFormat.onclick;
 const binding=bind(args);
 await nodes.btnBlind.listener();assert.equal(nodes.btnBlind.disabled,true);assert.equal(submissionsCount,1);
 await binding.resumeSubmission();assert.equal(submissionsCount,2);assert.equal(nodes.btnDocx.disabled,false);
 await nodes.btnDocx.listener();assert.equal(downloads,0);review=true;await nodes.btnDocx.listener();assert.equal(downloads,1);
 binding.dispose();assert.equal(nodes.cvInput.value,"");assert.equal(nodes.btnDocx.listener,null);
 const pending=bind({...args,client:{...fakeClient,upload:async()=>{throw Error("uncertain upload");}}});
 await nodes.btnFormat.listener();assert.equal(nodes.btnFormat.disabled,true);assert.match(nodes.outputBox.textContent,/Upload not confirmed/);pending.dispose();
 const queued=bind({...args,client:{...fakeClient,submit:async()=>JOB,status:async()=>({job_id:JOB,module:"cv_formatting",state:"running"})}});
 await nodes.btnFormat.listener();assert.equal(nodes.btnFormat.disabled,true);assert.equal(nodes.btnDocx.disabled,true);queued.dispose();
 console.log("Existing CV Studio cloud adapter fixture passed");
})().catch(e=>{console.error(e);process.exitCode=1;});

"use strict";
const assert=require("node:assert/strict");
const {create}=require("../cloud/frontend/batch_cloud.js");
const file=name=>({name});
(async()=>{
 let uploads=0,submits=[],fail=true,downloads=[],states={};
 const client={
   upload:async()=>String(++uploads),
   prepare:(doc,module,options)=>({doc,module,options,key:"key-"+doc}),
   submit:async intent=>{submits.push(intent);if(fail){fail=false;throw Error("uncertain");}return "job-"+intent.doc;},
   status:async jobId=>({job_id:jobId,document_id:jobId.slice(4),module:"cv_blinding",state:states[jobId]||"needs_review",elapsed_ms:4500}),
   download:async(jobId,options)=>{assert.equal(options.review,true);return {blob:"fixture",requiresReview:true};}
 };
 const batch=create({client,validateSource:f=>{if(!f.name.endsWith(".txt"))throw Error("unsupported");}});
 assert.throws(()=>batch.select(Array(11).fill(file("a.txt"))),/1–10/);
 assert.throws(()=>batch.select([file("a.exe")]),/unsupported/);
 batch.select([file("same.txt"),file("same.txt")]);
 await batch.start("cv_blinding",{alignment:"justify"});
 assert.equal(uploads,1);
 assert.deepEqual(batch.snapshot().map(r=>r.state),["submit_unconfirmed","ready"]);
 assert.equal(batch.clear(),false);
 await batch.start("cv_blinding",{alignment:"left"});assert.equal(uploads,1);
 await batch.recover(0);assert.equal(submits[0],submits[1]);
 await batch.start("cv_formatting",{alignment:"left"});
 assert.equal(uploads,2);
 assert.equal(submits[2].module,"cv_blinding");
 assert.equal(submits[2].options.alignment,"justify");
 await batch.refresh();
 assert.deepEqual(batch.snapshot().map(r=>r.state),["needs_review","needs_review"]);
 assert.deepEqual(batch.snapshot().map(r=>r.elapsedMs),[4500,4500]);
 await batch.download(0,()=>false,x=>downloads.push(x));assert.equal(downloads.length,0);
 await batch.download(0,()=>true,x=>downloads.push(x));
 await batch.download(1,()=>true,x=>downloads.push(x));
 assert.deepEqual(downloads.map(x=>x.filename),["cv-01-review.docx","cv-02-review.docx"]);
 const all=[];
 await batch.downloadAll(()=>false,x=>all.push(x));
 assert.equal(all.length,0);
 assert.deepEqual(await batch.downloadAll(()=>true,x=>all.push(x)),{started:2,failed:0,total:2});
 assert.deepEqual(all.map(x=>x.filename),["cv-01-review.docx","cv-02-review.docx"]);
 assert.equal(batch.clear(),true);assert.equal(batch.snapshot().length,0);
 const uncertain=create({client:{...client,upload:async()=>{throw Error("lost response");}},validateSource:()=>{}});
 uncertain.select([file("one.txt"),file("two.txt")]);await uncertain.start("cv_formatting",{});
 assert.deepEqual(uncertain.snapshot().map(x=>x.state),["upload_unconfirmed","ready"]);
 assert.equal(uncertain.clear(),false);uncertain.dispose();assert.equal(uncertain.snapshot().length,0);
 console.log("Cloud batch queue, stable recovery and review fixtures passed");
})().catch(e=>{console.error(e);process.exitCode=1;});

/* Exact integer micro-USD display; read-only internal ledger. */
(function(root,factory){const api=factory();if(typeof module==="object"&&module.exports)module.exports=api;else root.CVCloudUsage=api;})(typeof globalThis!=="undefined"?globalThis:this,function(){
"use strict";
const fields=["limit","reserved","spent","remaining","over_limit"];
const amount=v=>typeof v==="string"&&/^(0|[1-9][0-9]{0,19})$/.test(v);
function validate(value){
 if(!value||typeof value.configured!=="boolean")throw Error("invalid_usage");
 if(!value.configured)return {configured:false};
 const result={configured:true};
 for(const key of fields){const v=value[key+"_microusd"];if(!amount(v))throw Error("invalid_amount");result[key]=BigInt(v);}
 const delta=result.limit-result.spent-result.reserved;
 if(result.remaining!==(delta>0n?delta:0n)||result.over_limit!==(delta<0n?-delta:0n))throw Error("invalid_totals");
 return result;
}
function dollars(v){return "$"+(v/1000000n).toString()+"."+(v%1000000n).toString().padStart(6,"0");}
function bind({document,client,onAuthLost}){
 const el=id=>document.getElementById(id),toggle=el("cloudUsageToggle"),panel=el("cloudUsagePanel"),close=el("cloudUsageClose"),reload=el("cloudUsageRefresh"),status=el("cloudUsageStatus"),values=el("cloudUsageValues");
 if([toggle,panel,close,reload,status,values].some(x=>!x))throw Error("Usage controls missing");
 let dead=false,busy=false,open=false,epoch=0;
 const life=new AbortController(),listeners=[];
 const on=(n,e,f)=>{n.addEventListener(e,f);listeners.push([n,e,f]);};
 async function refresh(){
   if(dead||busy||!open)return;
   const n=++epoch;busy=true;reload.disabled=true;values.textContent="";status.textContent="Loading ledger…";
   try{
     const data=validate(await client.aiUsage({signal:life.signal}));
     if(dead||!open||n!==epoch)return;
     if(!data.configured){status.textContent="No budget configured. New AI reservations are blocked.";return;}
     const labels={limit:"Configured cap",spent:"Settled expenditure",reserved:"Reserved / unsettled",remaining:"Available for reservations",over_limit:"Over cap (including holds)"};
     for(const key of ["limit","spent","reserved","remaining","over_limit"]){
       const p=document.createElement("p");p.textContent=labels[key]+": "+dollars(data[key])+" USD";values.append(p);
     }
     status.textContent=data.over_limit>0n?"Budget exceeded. New positive-cost reservations are blocked.":data.remaining===0n?"No remaining budget.":"Current internal ledger.";
   }catch(e){if(!dead&&open&&n===epoch){values.textContent="";if(e.code==="authentication_required")onAuthLost();else if(e.code==="forbidden")dispose();else status.textContent="Usage unavailable. Refresh to try again.";}}
   finally{busy=false;if(!dead)reload.disabled=false;}
 }
 function hide(){open=false;epoch++;panel.style.display="none";values.textContent="";status.textContent="";}
 function dispose(){if(dead)return;hide();dead=true;life.abort();toggle.style.display="none";for(const [n,e,f] of listeners)n.removeEventListener(e,f);}
 on(toggle,"click",()=>{if(open){hide();return;}if(busy)return;open=true;panel.style.display="";refresh();});on(close,"click",hide);on(reload,"click",refresh);hide();toggle.style.display="";
 return {dispose};
}
return {validate,dollars,bind};
});

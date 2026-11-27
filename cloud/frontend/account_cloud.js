/* Account lifecycle controls, with server-checked permissions and no password handling. */
(function(root,factory){const api=factory();if(typeof module==="object"&&module.exports)module.exports=api;else root.CVCloudAccounts=api;})(typeof globalThis!=="undefined"?globalThis:this,function(){
"use strict";
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function validate(value){
 if(!value||!Array.isArray(value.items)||value.items.length>100)throw Error("invalid_accounts");
 const rows=value.items.map(x=>{
   if(!x||typeof x.user_id!=="string"||!UUID.test(x.user_id)||typeof x.email!=="string"||x.email.length<3||x.email.length>254||!["owner","admin","recruiter"].includes(x.role)||typeof x.active!=="boolean"||typeof x.revision!=="string"||!(/^[1-9][0-9]{0,18}$/).test(x.revision)||BigInt(x.revision)>=9223372036854775807n)throw Error("invalid_account");
   return {user_id:x.user_id.toLowerCase(),email:x.email,role:x.role,active:x.active,revision:x.revision};
 });
 if(new Set(rows.map(x=>x.user_id)).size!==rows.length)throw Error("duplicate_account");
 return rows;
}
function actions(role,userId,row){
 if(row.user_id===userId||row.role==="owner"||!["owner","admin"].includes(role)||(role==="admin"&&row.role!=="recruiter"))return [];
 const result=[{action:row.active?"suspend":"reactivate",label:row.active?"Suspend":"Reactivate"},{action:"revoke_sessions",label:"Revoke sessions"}];
 if(role==="owner")result.push({action:"role_change",value:row.role==="admin"?"recruiter":"admin",label:row.role==="admin"?"Make recruiter":"Make administrator"});
 return result;
}
function bind({document,client,role,userId,confirm,onAuthLost}){
 const el=id=>document.getElementById(id),toggle=el("cloudAccountsToggle"),panel=el("cloudAccountsPanel"),close=el("cloudAccountsClose"),reload=el("cloudAccountsRefresh"),list=el("cloudAccountsList"),status=el("cloudAccountsStatus");
 if([toggle,panel,close,reload,list,status].some(x=>!x))throw Error("Account controls missing");
 let dead=false,busy=false,open=false,epoch=0;
 const life=new AbortController(),listeners=[];
 function on(n,e,f){n.addEventListener(e,f);listeners.push([n,e,f]);}
 const current=n=>!dead&&open&&n===epoch;
 function error(e,n){if(!current(n))return;list.textContent="";if(e.code==="authentication_required"){onAuthLost();return;}if(e.code==="forbidden"){dispose();return;}status.textContent="Request unavailable or change unconfirmed. Refresh before any further action.";}
 function lock(value){busy=value;reload.disabled=value;for(const b of list.querySelectorAll("button"))b.disabled=value;}
 async function change(row,action,n){
   if(!current(n)||busy||!confirm(action.label+" for "+row.email+"? Existing in-flight work may continue."))return;
   lock(true);list.textContent="";
   const payload={action:action.action,expected_revision:row.revision};
   if(action.value)payload.value=action.value;
   try{await client.changeAccount(row.user_id,payload,{signal:life.signal});if(current(n))status.textContent="Change accepted. Refresh users to verify the current state.";}
   catch(e){error(e,n);}
   finally{if(!dead)lock(false);}
 }
 async function load(){
   if(dead||!open||busy)return;
   const n=++epoch;lock(true);list.textContent="";status.textContent="Loading users…";
   try{
     const rows=validate(await client.accounts({signal:life.signal}));
     if(!current(n))return;
     for(const row of rows){
       const item=document.createElement("div");item.className="batch-file-item";
       const name=document.createElement("strong");name.textContent=row.email;item.append(name);
       const detail=document.createElement("p");detail.textContent=row.role+" · "+(row.active?"Active":"Suspended")+(row.user_id===userId?" · Your account":"");item.append(detail);
       for(const action of actions(role,userId,row)){const b=document.createElement("button");b.className="sec";b.type="button";b.textContent=action.label;b.addEventListener("click",()=>change(row,action,n));item.append(b);}
       list.append(item);
     }
     status.textContent=rows.length+" visible accounts";
   }catch(e){error(e,n);}
   finally{if(!dead)lock(false);}
 }
 function hide(){open=false;epoch++;panel.style.display="none";list.textContent="";status.textContent="";}
 function dispose(){if(dead)return;hide();dead=true;life.abort();toggle.style.display="none";for(const [n,e,f] of listeners)n.removeEventListener(e,f);}
 on(toggle,"click",()=>{if(open){hide();return;}if(busy)return;open=true;panel.style.display="";load();});
 on(close,"click",hide);on(reload,"click",load);hide();toggle.style.display="";
 return {dispose};
}
return {validate,actions,bind};
});

/* Opt-in organisation provider settings. No key retrieval, browser storage or test calls. */
(function(root,factory){
 const api=factory();
 if(typeof module==="object"&&module.exports)module.exports=api;else root.CVCloudProviderSettings=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
 "use strict";
 const revision=v=>typeof v==="string"&&/^(0|[1-9][0-9]{0,18})$/.test(v)&&BigInt(v)<9223372036854775807n;
 const model=v=>typeof v==="string"&&/^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$/.test(v)&&!v.includes("://");
 function validate(value){
   const c=value?.configuration,choices=value?.choices;
   if(!c||!revision(c.revision)||typeof c.enabled!=="boolean"||
      !(c.revision==="0"&&!c.enabled&&c.provider===null&&c.model===null||c.revision!=="0"&&c.provider==="deepseek"&&model(c.model))||
      !Array.isArray(choices)||choices.length>100||
      choices.some(x=>!x||x.provider!=="deepseek"||!model(x.model)))throw Error("invalid_settings");
   const rows=choices.map(x=>({provider:x.provider,model:x.model}));
   if(new Set(rows.map(x=>x.provider+" "+x.model)).size!==rows.length)throw Error("invalid_settings");
   return {configuration:{revision:c.revision,enabled:c.enabled,provider:c.provider,model:c.model},choices:rows};
 }
 function bind({document,client,confirmDisable,onAuthLost}){
   const el=id=>document.getElementById(id);
   const toggle=el("cloudProviderToggle"),panel=el("cloudProviderPanel"),close=el("cloudProviderClose"),reload=el("cloudProviderReload"),provider=el("mainProviderSel"),modelSelect=el("modelSel"),key=el("keyInput"),save=el("cloudProviderSave"),disable=el("cloudProviderDisable"),status=el("cloudProviderStatus");
   if([toggle,panel,close,reload,provider,modelSelect,key,save,disable,status].some(x=>!x))throw Error("Settings controls missing");
   let closed=false,busy=false,current=null,open=false;
   const life=new AbortController(),listeners=[];
   function on(node,event,fn){node.addEventListener(event,fn);listeners.push([node,event,fn]);}
   function say(text){if(!closed)status.textContent=text;}
   function options(node,values,selected){
     node.textContent="";
     for(const value of values){const o=document.createElement("option");o.value=value;o.textContent=value;node.append(o);}
     if(values.includes(selected))node.value=selected;
   }
   function render(){
     if(closed)return;
     const ready=!!current&&!busy;
     reload.disabled=busy;
     provider.disabled=modelSelect.disabled=key.disabled=save.disabled=!ready||!current.choices.length;
     disable.disabled=!ready||!current.configuration.enabled;
   }
   function fill(value){
     current=validate(value);
     const c=current.configuration;
     options(provider,[...new Set(current.choices.map(x=>x.provider))],c.provider);
     options(modelSelect,current.choices.filter(x=>x.provider===provider.value).map(x=>x.model),c.model);
     say(c.enabled?"Enabled: "+c.provider+" / "+c.model+" (revision "+c.revision+")":"Provider not enabled.");
   }
   function error(e){
     current=null;key.value="";options(provider,[]);options(modelSelect,[]);
     if(e.code==="authentication_required"){onAuthLost();return;}
     if(e.code==="forbidden"){dispose();return;}
     say("Settings unavailable or update unconfirmed. Refresh before any further change.");
   }
   async function refresh(){
     if(closed||busy||!open)return;
     busy=true;current=null;key.value="";render();
     try{const value=await client.providerStatus({signal:life.signal});if(!closed&&open)fill(value);}
     catch(e){if(!closed)error(e);}
     finally{busy=false;render();}
   }
   async function change(kind){
     if(closed||busy||!current||!open)return;
     if(kind==="disable"&&!confirmDisable())return;
     const revision=current.configuration.revision;
     const chosen=current.choices.find(x=>x.provider===provider.value&&x.model===modelSelect.value);
     let secret=key.value;
     key.value="";
     if(kind==="save"&&(!chosen||!/^([!-~]){1,4096}$/.test(secret))){secret="";say("Select an approved model and enter a valid new key.");return;}
     busy=true;current=null;render();
     try{
       if(kind==="save")await client.configureProvider({provider:chosen.provider,model:chosen.model,secret,expected_revision:revision},{signal:life.signal});
       else await client.disableProvider(revision,{signal:life.signal});
       secret="";
       if(!closed&&open) say("Change accepted. Refresh to confirm current settings.");
     }catch(e){if(!closed)error(e);}
     finally{secret="";busy=false;render();}
   }
   function hide(){open=false;panel.style.display="none";key.value="";current=null;status.textContent="";options(provider,[]);options(modelSelect,[]);render();}
   function dispose(){
     if(closed)return;
     hide();closed=true;life.abort();toggle.style.display="none";
     for(const [n,e,f] of listeners)n.removeEventListener(e,f);
   }
   on(toggle,"click",()=>{if(open){hide();return;}if(busy)return;open=true;panel.style.display="";refresh();});
   on(close,"click",hide);
   on(reload,"click",refresh);
   on(provider,"change",()=>{if(current)options(modelSelect,current.choices.filter(x=>x.provider===provider.value).map(x=>x.model));});
   on(save,"click",()=>change("save"));
   on(disable,"click",()=>change("disable"));
   hide();toggle.style.display="";
   return {dispose};
 }
 return {bind,validate};
});

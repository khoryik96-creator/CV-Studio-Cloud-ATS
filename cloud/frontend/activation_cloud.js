/* Manual one-time code entry. No URL tokens, persistence, automatic login or retry. */
"use strict";
(()=>{
 const el=id=>document.getElementById(id);
 const form=el("activationForm"),code=el("activationCode"),password=el("activationPassword"),confirmation=el("activationConfirm"),submit=el("activationSubmit"),status=el("activationStatus");
 let busy=false,done=false,epoch=0;
 const fields=[code,password,confirmation,submit];
 function wipe(){code.value=password.value=confirmation.value="";}
 function lock(v){for(const field of fields)field.disabled=v;}
 function say(value){status.textContent=value;}
 form.addEventListener("submit",async event=>{
   event.preventDefault();
   if(busy||done)return;
   let token=code.value.trim(),secret=password.value;
   if(!/^[A-Za-z0-9_-]{43}$/.test(token)||secret.length<12||secret.length>256||secret!==confirmation.value){
     wipe();say("Enter a valid one-time code and matching passwords of 12–256 characters.");return;
   }
   busy=true;const n=++epoch;wipe();lock(true);say("Submitting…");
   try{
     const response=await fetch("/api/auth/redeem",{method:"POST",credentials:"same-origin",cache:"no-store",redirect:"error",headers:{"Content-Type":"application/json"},body:JSON.stringify({token,password:secret})});
     if(n!==epoch)return;
     if(response.ok){
       const result=await response.json();
       if(n!==epoch)return;
       if(result?.ok!==true)throw Error("invalid_response");
       done=true;say("Password set. Return to sign in.");
     }else if(response.status===429)say("Too many attempts. Try again later or contact your administrator.");
     else if(response.status===400)say("Code invalid, expired or already used, or password not accepted. Contact your administrator if needed.");
     else say("Request unavailable. If uncertain, try signing in with your new password before asking for a replacement code.");
   }catch{if(n===epoch)say("Result unconfirmed. Try signing in with your new password before requesting another code.");}
   finally{token=secret="";if(n===epoch){busy=false;lock(done);}}
 });
 window.addEventListener("pagehide",()=>{epoch++;wipe();busy=false;lock(true);});
 window.addEventListener("pageshow",event=>{if(event.persisted){wipe();lock(true);say("Reload this page to start again.");}});
 wipe();lock(false);say("Ready.");
})();

"use strict";
const $ = id => document.getElementById(id);
let lastReceipt=null;
let staticIndex=null;
let freshLocal=false;
function addEvent(stage,detail,cls=""){
  const li=document.createElement("li"),name=document.createElement("strong"),small=document.createElement("small");
  li.className=cls;name.textContent=stage;small.textContent=detail;li.append(name,small);$("lab-timeline").append(li);
}
function render(result){
  if(!["OFFLINE_POLICY_FRESH_LOCAL_HTTP","OFFLINE_SIMULATION_RECORDED"].includes(result.mode)||result.model!=="NOT_RUN")throw Error("Mode mismatch");
  const incident=result.incident;
  $("lab-before").textContent="/checkout "+incident.before.checkout_http;
  $("lab-after").textContent="/checkout "+incident.after.checkout_http;
  $("lab-attempts").textContent=String(incident.attempts);
  $("lab-result").textContent=incident.outcome.replaceAll("_"," ");
  $("lab-timeline").replaceChildren();
  for(const event of incident.events){const d=event.data;
    if(event.stage==="DECISION")addEvent("OFFLINE policy decision "+d.attempt,d.decision.action+" "+JSON.stringify(d.decision.args));
    if(event.stage==="SAFETY_GATE")addEvent("Safety Gate · "+d.status,d.action+" "+JSON.stringify(d.args));
    if(event.stage==="VERIFY_INDEPENDENT_HTTP")addEvent("Independent HTTP check · "+d.checkout_http,"/health "+d.health_http+" · /checkout "+d.checkout_http,d.checkout_http===200?"success":"failed");
    if(event.stage==="VERIFY_FAIL")addEvent("Failure fed back to the policy","HTTP "+d.http.checkout+" · current metrics and configuration observed","failed");
    if(event.stage==="ROLLBACK"||event.stage==="STEP_ROLLBACK")addEvent("Rollback",d.reason);
  }
  $("lab-raw").textContent=JSON.stringify({scope:incident.scope,before:incident.before,after:incident.after,config_restored:incident.config_restored,head_sha256:incident.head_sha256,events:incident.events.filter(e=>["OBSERVE_HTTP_LOGS_METRICS","VERIFY_INDEPENDENT_HTTP","ROLLBACK","STEP_ROLLBACK"].includes(e.stage))},null,2);
  lastReceipt=result;$("download-receipt").disabled=false;
  $("lab-status").textContent=result.mode==="OFFLINE_SIMULATION_RECORDED"?"Saved offline simulation loaded · no fresh HTTP or model call":"Fresh local run complete · zero model calls";
}
async function init(){
  try{const [statusResponse,contractResponse]=await Promise.all([fetch("api/judge/status",{cache:"no-store"}),fetch("api/judge/contract",{cache:"no-store"})]);
    if(!statusResponse.ok||!contractResponse.ok)throw Error("Local judge server unavailable");
    const status=await statusResponse.json(),contract=await contractResponse.json();
    if(status.new_provider_calls_in_this_build!==0||contract.mode!=="NO_PROVIDER_CALL"||status.case_ids.length!==3)throw Error("Unexpected provider or scenario state");
    freshLocal=true;$("lab-status").textContent="Local test server ready · fresh loopback HTTP, no model calls";$("run-lab").disabled=false;
    $("contract-hash").textContent=contract.r34_contract_sha256;$("contract-format").textContent=contract.response_format;$("contract-calls").textContent=String(contract.live_calls_exposed_by_this_build);
  }catch(error){
    try{const response=await fetch("evidence/offline_index.json",{cache:"no-store"});if(!response.ok)throw Error("Offline receipts unavailable");
      const index=await response.json();if(index.schema!=="edgesre_r40_static_offline_index_1"||index.mode!=="OFFLINE_SIMULATION_RECORDED"||index.provider_calls_in_this_build!==0||Object.keys(index.cases).length!==3)throw Error("Offline manifest invalid");
      staticIndex=index;$("lab-status").textContent="Hosted preview ready · saved offline simulation; no fresh HTTP or model call";
      $("run-lab").textContent="Inspect saved offline run →";$("run-lab").disabled=false;
      $("contract-hash").textContent=index.contract.r34_contract_sha256;$("contract-format").textContent=index.contract.response_format;$("contract-calls").textContent="0";
    }catch(fallbackError){$("lab-status").textContent="Demo unavailable: "+fallbackError.message;$("run-lab").disabled=true}
  }
}
$("run-lab").addEventListener("click",async()=>{
  lastReceipt=null;$("download-receipt").disabled=true;
  for(const id of ["lab-before","lab-after","lab-attempts","lab-result"])$(id).textContent="—";
  $("lab-timeline").replaceChildren();$("lab-raw").textContent="Waiting for a verified receipt.";
  $("run-lab").disabled=true;$("lab-status").textContent=freshLocal?"Running isolated loopback HTTP checks…":"Loading saved offline simulation…";
  try{let response;
    if(freshLocal){response=await fetch("api/judge/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({case_id:$("lab-case").value})})}
    else{const item=staticIndex.cases[$("lab-case").value];if(!item)throw Error("Invalid public scenario");response=await fetch(item.path,{cache:"no-store"})}
    if(!response.ok)throw Error("Receipt HTTP "+response.status);
    if(freshLocal)render(await response.json());
    else{const raw=await response.arrayBuffer(),item=staticIndex.cases[$("lab-case").value];
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",raw))).map(b=>b.toString(16).padStart(2,"0")).join("");
      if(digest!==item.sha256)throw Error("Receipt SHA-256 mismatch");render(JSON.parse(new TextDecoder().decode(raw)))}
  }catch(error){$("lab-status").textContent="Run failed: "+error.message}
  finally{$("run-lab").disabled=false}
});
$("download-receipt").addEventListener("click",()=>{if(!lastReceipt)return;const blob=new Blob([JSON.stringify(lastReceipt,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="edgesre-"+lastReceipt.case_id+"-receipt.json";a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)});
init();

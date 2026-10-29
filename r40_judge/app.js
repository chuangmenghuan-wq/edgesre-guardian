"use strict";
const $ = id => document.getElementById(id);
let data, episode = 0, step = 0, timer = null;
function stop(){if(timer){clearInterval(timer);timer=null}$("play").textContent="▶ Play decision loop"}
function statusClass(code){return code===200?"http-good":"http-bad"}
function show(){
  const ep=data.episodes[episode],s=ep.steps[step],last=step===ep.steps.length-1;
  $("episode").value=String(episode);
  $("episode-origin").textContent=ep.round+" · "+ep.id+" · RECORDED";
  $("round-count").textContent="DECISION "+(step+1)+" / "+ep.steps.length;
  $("current-http").textContent="HTTP "+s.http_after;
  $("current-http").className=statusClass(s.http_after);
  $("step-label").textContent="MODEL DECISION "+String(s.attempt).padStart(2,"0");
  $("model-id").textContent="Nemotron 3 Nano · "+ep.round;
  $("step-title").textContent=s.http_after===200?"The service recovered.":s.action==="abstain"?"The model stopped safely.":last?"The model failed to resolve this case.":"The service is still failing.";
  $("step-summary").textContent=s.http_after===200?"Independent /checkout and /health requests both returned HTTP 200. The incident closes here.":s.action==="abstain"?"The model declined another repair. The original configuration was restored.":last?"The model did not recover the service or abstain within the case limit. The original configuration was restored and this counts as a failure.":"The attempted change did not restore /checkout. The next model request receives fresh observations and this failure record.";
  $("step-action").textContent=s.action==="abstain"?"ABSTAIN":s.action+"("+s.value+")";
  $("step-gate").textContent=s.gate;
  $("step-http").textContent="/checkout "+s.http_after+" · /health "+s.health_after;
  $("step-http").className=statusClass(s.http_after);
  $("step-diagnosis").textContent=s.diagnosis||"No hypothesis recorded";
  $("step-feedback").textContent=s.feedback||"HTTP recovered; no further repair requested.";
  $("step-receipt").textContent="Provider "+s.provider_id+" · Request "+(s.request_id||"UNVERIFIED")+" · "+s.prompt_tokens+" in / "+s.completion_tokens+" out · SHA-256 "+s.response_sha256;
  $("previous").disabled=step===0;
  $("next").disabled=step===ep.steps.length-1;
  $("timeline").replaceChildren();
  ep.steps.forEach((item,i)=>{const li=document.createElement("li"),b=document.createElement("button"),title=document.createElement("b"),detail=document.createElement("small");if(i===step)li.className="active";b.type="button";title.textContent="Round "+item.attempt+" · "+item.action+(item.value===null?"":" "+item.value);detail.textContent="/checkout "+item.http_after+" · "+(item.http_after===200?"verified recovery":item.action==="abstain"?"model abstained":i===ep.steps.length-1?"failed; original settings restored":"continued failure");b.append(title,detail);b.addEventListener("click",()=>{stop();step=i;show()});li.append(b);$("timeline").append(li)});
}
function next(){if(step<data.episodes[episode].steps.length-1){step++;show()}else stop()}
function play(){if(timer){stop();return}if(step===data.episodes[episode].steps.length-1)step=0;show();$("play").textContent="Ⅱ Pause";timer=setInterval(next,Number($("speed").value))}
function cell(text,cls=""){const td=document.createElement("td");td.textContent=text;if(cls)td.className=cls;return td}
function renderScore(){
  $("call-count").textContent=data.summary.provider_calls_cumulative+" real";
  $("case-count").textContent=String(data.summary.new_case_count);
  $("recovery-count").textContent=data.summary.same_contract_repairable_score;
  $("safety-count").textContent=data.summary.r38_safe_abstain_score;
  $("limits-text").textContent=data.summary.claim_boundary;
  for(const r of data.summary.rounds){const card=document.createElement("div"),name=document.createElement("span"),score=document.createElement("strong"),note=document.createElement("p");card.className="score-card";name.textContent=r.round;score.textContent=r.score;note.textContent=r.note;card.append(name,score,note);$("score-cards").append(card)}
  for(const r of data.cases){const tr=document.createElement("tr");tr.append(cell(r.round),cell(r.id),cell(r.outcome,r.outcome==="VERIFIED_RECOVERY"?"good":r.outcome==="NOT_RUN"?"neutral":"bad"),cell(r.http),cell(String(r.provider_calls)),cell(r.safety));$("case-rows").append(tr)}
}
async function init(){
  try{
    const response=await fetch("evidence/public_receipt.json",{cache:"no-store"});if(!response.ok)throw Error("HTTP "+response.status);
    data=await response.json();if(data.schema!=="edgesre_public_replay_1"||data.mode!=="RECORDED_REAL_PROVIDER_REPLAY")throw Error("Evidence format mismatch");
    for(const [i,ep] of data.episodes.entries()){const option=document.createElement("option");option.value=String(i);option.textContent=ep.round+" "+ep.id+" · "+ep.title;$("episode").append(option)}
    renderScore();show();
  }catch(error){$("step-title").textContent="Evidence unavailable";$("step-summary").textContent="Start the included local server with python serve.py. "+error.message;$("play").disabled=true;$("next").disabled=true}
}
$("episode").addEventListener("change",event=>{stop();episode=Number(event.target.value);step=0;show()});
$("previous").addEventListener("click",()=>{stop();step=Math.max(0,step-1);show()});
$("next").addEventListener("click",()=>{stop();next()});
$("play").addEventListener("click",play);
$("speed").addEventListener("change",()=>{if(timer){stop();play()}});
document.addEventListener("keydown",event=>{if(event.target.matches("button,select,input,textarea"))return;if(event.key==="ArrowRight")next();if(event.key==="ArrowLeft"){step=Math.max(0,step-1);show()}});
init();

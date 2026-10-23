// Check the real frontend decision handler with mocked HTTP, never backend recovery state.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(){this.value='';this.attrs={};this.dataset={};this.children=[];this.hidden=false;this.open=true;this.classList={remove(){},add(){}};}
  setAttribute(k,v){this.attrs[k]=v;}
  removeAttribute(k){delete this.attrs[k];}
  replaceChildren(...children){this.children=children;}
  append(...children){this.children.push(...children);}
  focus(){this.focused=true;}
}
const elements = new Map();
function element(selector){if(!elements.has(selector))elements.set(selector,new Element());return elements.get(selector);}
const storage = new Map();
const source = fs.readFileSync('triager/static/app.js','utf8');
const context = vm.createContext({document:{querySelector:element,createElement:()=>new Element(),createTextNode:text=>({textContent:text})},
  sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(k,v)=>storage.set(k,v),removeItem:key=>storage.delete(key)},
  crypto:{randomUUID:()=> 'decision-key-1'}});
vm.runInContext(source.slice(0,source.indexOf('function setMetricState'))+
  source.slice(source.indexOf('function updateApproval()'),source.indexOf('async function refresh()'))+
  source.slice(source.indexOf('function renderReviewMetadata()'),source.indexOf('let reviewReturnTarget'))+
  source.slice(source.indexOf('async function submitDecision('),source.indexOf('$("#approve").onclick')),context);
vm.runInContext('async function refresh(){}; function renderTimeline(){}; api=(...args)=>mockApi(...args);',context);
const evaluate=code=>vm.runInContext(code,context);
function select(overrides={}){
  context.incident={id:'incident-A',status:'open',service:'execution-gateway',action:'enable_backoff',approval:{id:'proposal-A',status:'pending'},...overrides};
  evaluate("selected=incident;state={mode:'simulated desk'};busy=false;");
  element('#actor').value='reviewer';element('#feedback-reason').value='';element('#detail').open=true;
  element('#modal-message').textContent='';
}
async function main(){
  context.diagnosed={report:'Original full report [source-id]',investigation:{diagnosis:{hypotheses:[{cause:'Observed fixture symptom'}]}}};
  evaluate('renderDiagnosisSummary(diagnosed)');
  assert.equal(element('#report').textContent,'Observed fixture symptom');
  assert.equal(element('#full-report').textContent,'Original full report [source-id]');
  context.diagnosed.investigation.diagnosis.abstained=true;evaluate('renderDiagnosisSummary(diagnosed)');
  assert.match(element('#report').textContent,/insufficient/);
  select();let calls=[];context.mockApi=async(...args)=>{calls.push(args);return {...context.incident,status:'queued'};};
  await evaluate('submitDecision(false)');
  assert.equal(calls.length,0);assert.equal(element('#feedback-reason').attrs['aria-invalid'],'true');
  assert.match(element('#decision-error').textContent,/reason/);
  element('#actor').value=' ';
  await evaluate('submitDecision(true)');assert.equal(calls.length,0);assert.equal(element('#actor').focused,true);
  select();element('#feedback-reason').value='Need additional evidence';
  context.mockApi=async(...args)=>{calls.push(args);return {...context.incident,approval:{id:'proposal-A',status:'rejected'}};};
  await evaluate('submitDecision(false)');
  assert.equal(calls[0][0],'/api/incidents/incident-A/reject');
  assert.equal(calls[0][1].reason,'Need additional evidence');assert.equal(calls[0][1].proposal_id,'proposal-A');
  assert.equal(calls[0][2]['Idempotency-Key'],'decision-key-1');
  assert.equal(element('#approve').disabled,true);assert.match(element('#modal-message').textContent,/Rejection recorded/);
  assert.equal(evaluate('recoveryPresentation(selected)[0]'),'Proposal rejected');
  select();calls=[];element('#feedback-reason').value='Keep this draft';
  context.mockApi=async(...args)=>{calls.push(args);throw new Error('Network unavailable');};
  await evaluate('submitDecision(true)');evaluate('updateApproval()');
  assert.equal(element('#modal-error').hidden,false);assert.equal(element('#modal-error').textContent,'Network unavailable');
  assert.equal(element('#feedback-reason').value,'Keep this draft');
  await evaluate('submitDecision(true)');assert.equal(calls[0][2]['Idempotency-Key'],calls[1][2]['Idempotency-Key']);
  select();calls=[];let finish;
  context.mockApi=async(...args)=>{calls.push(args);if(args[1])await new Promise(resolve=>{finish=resolve;});return {...context.incident,status:'queued'};};
  const first=evaluate('submitDecision(true)');await evaluate('submitDecision(true)');assert.equal(calls.length,1);
  finish();await first;assert.equal(element('#approve').disabled,true);
  assert.match(evaluate('recoveryPresentation(selected)[1]'),/not a successful recovery/);
  for(const status of ['queued','verifying','resolved','failed']){
    context.incident={status};assert.ok(evaluate('recoveryPresentation(incident)[0]'));
  }
  select();calls=[];
  context.mockApi=async(...args)=>{calls.push(args);if(args[1]){context.newIncident={...context.incident,id:'incident-B'};evaluate('selected=newIncident');}return {...context.incident,status:'queued'};};
  await evaluate('submitDecision(true)');
  assert.equal(calls[1][0],'/api/incidents/incident-A');assert.equal(evaluate('selected.id'),'incident-B');
  console.log('Review checks passed: required reason/approver, bound payload, retry key, duplicate clicks, persistent errors, drafts, recovery states and late responses.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});

// Labeled UI fixtures only; no incidents are posted to a backend.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
function element(selector) {
  if (!elements.has(selector)) elements.set(selector, {value:'all',dataset:{}});
  return elements.get(selector);
}
const source = fs.readFileSync('triager/static/app.js','utf8');
const context = vm.createContext({document:{querySelector:element},sessionStorage:{getItem:()=>null,removeItem(){}}});
vm.runInContext(source.slice(0,source.indexOf('function setMetricState')) +
  source.slice(source.indexOf('let incidentSort'),source.indexOf('function renderSupporting')),context);
const fixture = ['open','queued','verifying','resolved','failed'].map((status,index)=>({
  id:`incident-${index}`,status,kind:'latency',service:index%2?'market-feed':'execution-gateway',
  opened_at:`2026-10-23T10:00:0${index}Z`,severity:index===0?null:index===1?'critical':'medium',
  summary:'fixture summary',signal:'<unsafe signal>',analysis_source:'offline',
}));
context.fixture=fixture;
const select = (status='all',severity='all',service='all',key='opened_at',direction=-1)=>{
  context.filters={status,severity,service};context.sort={key,direction};
  return Array.from(vm.runInContext('filterIncidents(fixture,filters,sort).map(i=>i.id)',context));
};
assert.equal(select().length,5);
assert.equal(select('open').length,4);
assert.deepEqual(select('resolved'),['incident-3']);
assert.deepEqual(select('all','unknown'),['incident-0']);
assert.deepEqual(select('open','critical','market-feed'),['incident-1']);
assert.equal(select('all','all','all','severity',1)[0],'incident-1');
assert.equal(select('all','all','all','severity',-1).at(-1),'incident-0');
assert.equal(select('all','all','all','opened_at',1)[0],'incident-0');
for (let index=0;index<fixture.length;index++) {
  context.incident=fixture[index];
  const html=vm.runInContext('incidentRow(incident)',context);
  assert.match(html,new RegExp(`data-id="incident-${index}"`));
  assert.match(html,/&lt;unsafe signal&gt;/);
  assert.doesNotMatch(html,/<unsafe signal>/);
  assert.match(html,new RegExp(`datetime="${fixture[index].opened_at}"`));
  assert.equal(vm.runInContext('incidentAction(incident)',context),['open','failed'].includes(fixture[index].status)?'Review':'View details');
  if(index===0) assert.match(html,/>unknown<\/span>/);
  if(index===1) assert.match(html,/Recovery queued; not executed yet/);
}
context.filters={status:'open',severity:'all',service:'all'};
assert.match(vm.runInContext('incidentEmptyState(filters,5,0)[0]',context),/No incidents require attention/);
assert.match(vm.runInContext('incidentEmptyState(filters,5,3)[0]',context),/loaded history/);
context.filters.severity='high';
assert.match(vm.runInContext('incidentEmptyState(filters,5,0)[0]',context),/match these filters/);
// Exercise the actual table renderer, including correlation context and every individual action.
element('#show-history').value='all';
context.snapshot={incidents:fixture.map(i=>({...i,correlation:{id:'group',basis:'Temporally related',impacted_services:['market-feed','execution-gateway']}})),started_at:'2026-10-23T00:00:00Z',open_incident_count:4,service_age_seconds:{}};
vm.runInContext('state=snapshot; renderIncidents()',context);
const html=element('#incident-rows').innerHTML;
assert.equal((html.match(/class="incident-row"/g)||[]).length,5);
assert.equal((html.match(/class="correlation"/g)||[]).length,1);
assert.match(element('#incident-count').textContent,/5 of 5 loaded/);
console.log('Incident checks passed: filters, sorting, unknown severity, statuses, actions, escaping, timestamps, empty states and correlation rows.');

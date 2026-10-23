// Exercise the real chart renderer with labeled fixtures, without a browser dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
const element = selector => {
  if (!elements.has(selector)) elements.set(selector, {
    value: 'fill_latency_ms', clientWidth: 640, dataset: {}, attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
  });
  return elements.get(selector);
};
const source = fs.readFileSync('triager/static/app.js', 'utf8');
const context = vm.createContext({document: {querySelector: element},
  sessionStorage: {getItem: () => null, removeItem() {}}});
vm.runInContext(source.slice(0, source.indexOf('function setMetricState')) + '\nlet helpAnchor = null;', context);
const sample = (timestamp, value, metric='fill_latency_ms') => ({
  service: 'execution-gateway', timestamp, [metric]: value,
});
const start = '2026-10-23T10:00:00Z';
function render(events, metric='fill_latency_ms') {
  element('#chart-metric').value = metric;
  context.fixture = {events};
  vm.runInContext('state = fixture; renderChart();', context);
  return element('#chart').innerHTML;
}
assert.equal(render([]), '');
assert.equal(element('#chart-state').hidden, false);
assert.match(element('#chart-state').textContent, /No samples/);
assert.doesNotMatch(render([sample(start,0)]), /NaN|Infinity/);
assert.match(render([sample(start, 80)]), /<circle/);
assert.match(element('#chart-threshold').textContent, /above visible range/);
assert.doesNotMatch(element('#chart').innerHTML, /class="chart-limit"/);
assert.match(render([sample(start,650)]), /class="chart-limit"/);
const negative = render([sample(start,-2,'slippage_bps'),sample('2026-10-23T10:00:10Z',1,'slippage_bps')], 'slippage_bps');
assert.match(negative, />-2/);
assert.doesNotMatch(negative, /NaN|Infinity/);
assert.equal(element('#chart-threshold').textContent, 'No fixed alert threshold');
render([sample('2026-10-23T10:00:10Z',100),sample(start,50),sample('2026-10-23T10:00:01Z',70),sample('bad',1),sample(start,NaN)]);
const times = vm.runInContext('chartLayout.events.map(e=>e.timestamp)',context);
assert.deepEqual(Array.from(times), [start,'2026-10-23T10:00:01Z','2026-10-23T10:00:10Z']);
assert.ok(Math.abs(vm.runInContext('(chartLayout.x(chartLayout.events[1].timestamp)-chartLayout.left)/(chartLayout.right-chartLayout.left)',context) - .1) < 1e-9);
assert.equal(element('#chart-state').hidden,true);
assert.match(element('#chart-context').textContent,/3 accepted samples/);
console.log('Dashboard chart checks passed: empty, single, threshold, negative, invalid and uneven-time samples.');

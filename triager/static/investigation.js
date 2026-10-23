/* Observable investigation records only. Never render model messages or hidden reasoning. */
(() => {
  const number = value => Number.isFinite(value) && value >= 0;
  const duration = value => number(value) ? `${value.toLocaleString(undefined, {maximumFractionDigits: 1})} ms` : 'Duration not recorded';
  function providerLabel(data) {
    if (data?.provider === 'offline') return 'Offline rule-based analysis';
    if (['gemini','openai'].includes(data?.provider)) return `${data.provider === 'gemini' ? 'Gemini' : 'OpenAI'} · model-backed diagnosis`;
    return data?.provider ? `${data.provider} · execution type not recorded` : 'Provider not recorded';
  }
  function nodeInfo(record, data) {
    const final = data?.verification || {};
    switch (record.node) {
      case 'collect_context': return ['Context collection', 'Recorded', 'Collected scoped telemetry and ledger context. Tool records below identify the sources accessed.'];
      case 'reason': return data.provider === 'offline' && !data.fallback_reason && !(data.model_calls || []).length
        ? ['Offline rule analysis', 'Recorded', 'Applied the offline rules. This is not an LLM result.']
        : ['Agent reasoning', 'Recorded', 'Recorded reasoning pass. Only observable calls and final structured findings are shown; per-pass model content is not displayed.'];
      case 'tools': return ['Read-only tool execution', 'Recorded', 'Processed tool requests. See recorded tool outcomes below; a completed node does not mean every tool succeeded.'];
      case 'verify': return ['Evidence verification', 'Recorded', `Recorded verification operation. ${final.checks ? "Final check types: " + final.checks + ". " : "Check types not recorded. "}${Array.isArray(final.issues) ? "Final issues: " + final.issues.length + ". " : "Issue count not recorded. "}Extract checks do not prove root-cause correctness.`];
      case 'critic': return final.semantic_support === 'model_critic_assessed'
        ? ['Model critic', 'Assessment recorded', 'A model critic assessed causal support. This is a second opinion, not verified accuracy.']
        : final.semantic_support === 'critic_unavailable'
          ? ['Critic gate', 'Unavailable', 'The requested critic was unavailable. No successful critic assessment is recorded.']
          : ['Critic gate', 'No assessment recorded', 'The gate was visited. No critic model assessment is recorded; do not infer a model call from this node.'];
      case 'final_report': return ['Diagnosis generation', 'Recorded', 'Assembled the final structured diagnosis and report. Recovery still requires separate human authorization.'];
      default: return [`Recorded node: ${record.node || 'unnamed'}`, 'Recorded', 'An operation is present in node_trace; no additional execution semantics are inferred.'];
    }
  }
  function trace(data) {
    return (data?.node_trace || []).map((record,index) => {
      const [name,status,explanation] = nodeInfo(record,data);
      return {index,name,status,explanation,node:record.node,duration:duration(record.latency_ms),
        metrics: Object.fromEntries(['latency_ms','input_tokens','output_tokens','estimated_cost_usd']
          .filter(key=>number(record[key])).map(key=>[key,record[key]]))};
    });
  }
  function evidenceType(item) {
    if (item.source === 'tool:search_runbooks') {
      let documents = [], recognized = false;
      try {
        const parsed=JSON.parse(item.content);
        if (Array.isArray(parsed)) {
          documents=parsed.filter(doc=>doc && typeof doc.document_id==='string' && typeof doc.content==='string');
          recognized=parsed.length===0 || documents.length>0;
        }
      } catch {}
      return {kind:'retrieval',label:documents.length ? `Knowledge retrieval · ${documents.length} document(s)` : recognized ? 'Runbook search · no document records' : 'Runbook search · unrecognized result',documents};
    }
    if (item.source?.startsWith('telemetry:')) return {kind:'collected',label:'Collected telemetry',documents:[]};
    if (item.source?.startsWith('ledger:')) return {kind:'collected',label:'Ledger snapshot',documents:[]};
    if (item.source?.startsWith('tool:') && /logs|metrics|deploy|reconcile/.test(item.source)) return {kind:'collected',label:'Collected tool result',documents:[]};
    return {kind:'other',label:'Other recorded source',documents:[]};
  }
  function relatedFindings(item, data) {
    return (data?.diagnosis?.hypotheses || []).map((hypothesis,index)=>({hypothesis,index}))
      .filter(({hypothesis})=>(hypothesis.evidence_ids || []).includes(item.evidence_id));
  }
  function toolSource(tool) {
    const sources = {
      inspect_service_logs:'Stored service telemetry (read-only)', reconcile_balances:'Stored ledger / exchange balances (read-only)',
      get_service_metrics:'Stored service metrics (read-only)', query_logs:'Loki logs (read-only)',
      get_metrics:'Prometheus metrics (read-only)', list_deployments:'Demo deployment history (read-only)',
      get_deploy_diff:'Demo deployment diff (read-only)', search_runbooks:'Reviewed runbooks and past incidents (retrieval)',
    };
    // Blocked requests never accessed these sources; keep that distinction explicit.
    if (tool.status !== 'ok') return `Tool outcome: ${tool.status || 'not recorded'}. Source access is not confirmed; inspect the recorded result.`;
    return Object.hasOwn(sources,tool.tool) ? sources[tool.tool] : 'Source not identified in this record; inspect linked evidence.';
  }
  function usage(call) {
    // Whitelist public usage fields. Never serialize provider response parts or messages.
    return Object.fromEntries(['provider','model','input_tokens','output_tokens','latency_ms','prior_failed_attempts','estimated_cost_usd']
      .filter(key=>['provider','model'].includes(key) ? typeof call[key]==='string' : Object.hasOwn(call,key) && (call[key]===null || number(call[key]))).map(key=>[key,call[key]]));
  }
  window.DeskInvestigation = Object.freeze({duration,providerLabel,trace,evidenceType,relatedFindings,toolSource,usage});
})();

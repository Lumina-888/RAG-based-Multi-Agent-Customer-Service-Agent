/**
 * 评测 API（SP-FE-003）：评测看板数据源（M7 交付 `GET /api/v1/eval/runs`）。
 */
async function getJSON(url) {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()).data
}

export function fetchEvalRuns(runType = '') {
  const query = runType ? `?run_type=${encodeURIComponent(runType)}` : ''
  return getJSON(`/api/v1/eval/runs${query}`)
}

export function fetchEvalRun(runId) {
  return getJSON(`/api/v1/eval/runs/${runId}`)
}

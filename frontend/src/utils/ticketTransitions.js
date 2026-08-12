/**
 * 工单状态受限迁移（SP-FE-003 / SP-REF-007/008）：
 * 前端工单页仅允许 `APPROVING → APPROVED / REJECTED`，
 * **不得**直接触发 REFUNDING（公开 API 无法绕过审核直接打款）。
 */
export const LIMITED_TRANSITIONS = [
  ['APPROVING', 'APPROVED'],
  ['APPROVING', 'REJECTED'],
]

export function allowedTransitions(status) {
  return LIMITED_TRANSITIONS.filter(([from]) => from === status).map(([, to]) => to)
}

export function isLimitedTransition(from, to) {
  return LIMITED_TRANSITIONS.some(([f, t]) => f === from && t === to)
}

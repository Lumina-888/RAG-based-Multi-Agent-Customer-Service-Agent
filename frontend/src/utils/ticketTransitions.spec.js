/**
 * SP-FE-003 工单受限迁移单测（纯函数）。
 *
 * - T-FE-401 下拉选项：APPROVING 仅 APPROVED/REJECTED 两个目标
 * - T-FE-402 硬约束：任何状态下都不会出现 REFUNDING 目标（资金边界 4091 口径）
 * - T-FE-403 非 APPROVING 状态无可选迁移
 */
import { describe, it, expect } from 'vitest'
import { allowedTransitions, isLimitedTransition } from './ticketTransitions.js'

describe('ticketTransitions（T-FE-401~403）', () => {
  it('T-FE-401 APPROVING 仅 APPROVED/REJECTED', () => {
    expect(allowedTransitions('APPROVING')).toEqual(['APPROVED', 'REJECTED'])
  })

  it('T-FE-402 永不出现 REFUNDING（资金边界）', () => {
    for (const status of ['CREATED', 'APPROVING', 'APPROVED', 'REFUNDING', 'REJECTED']) {
      expect(allowedTransitions(status)).not.toContain('REFUNDING')
    }
    expect(isLimitedTransition('APPROVING', 'REFUNDING')).toBe(false)
    expect(isLimitedTransition('APPROVED', 'REFUNDING')).toBe(false)
  })

  it('T-FE-403 非 APPROVING 无可选迁移；合法迁移校验', () => {
    expect(allowedTransitions('CREATED')).toEqual([])
    expect(allowedTransitions('REJECTED')).toEqual([])
    expect(isLimitedTransition('APPROVING', 'APPROVED')).toBe(true)
    expect(isLimitedTransition('APPROVING', 'REJECTED')).toBe(true)
  })
})

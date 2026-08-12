/**
 * SP-FE-001 引用角标工具单测。
 *
 * - T-FE-301 角标提取：`[1][2]` 全部提取；无角标 → 空数组
 * - T-FE-302 分段：按角标切分（角标独立成段，正文与角标交替）
 * - T-FE-303 溯源映射：[n] → docs[n-1]；越界/无 docs → null
 */
import { describe, it, expect } from 'vitest'
import { citationDoc, extractCitations, splitByCitations } from './citations.js'

describe('citations（T-FE-301~303）', () => {
  it('T-FE-301 提取全部角标', () => {
    expect(extractCitations('退款 3~5 天到账[1]，7 天内可退[2]。')).toEqual([1, 2])
    expect(extractCitations('没有角标的内容')).toEqual([])
    expect(extractCitations('重复[1]和[1]')).toEqual([1, 1])
  })

  it('T-FE-302 按角标切分', () => {
    const segments = splitByCitations('到账[1]，可退[2]。')
    expect(segments).toEqual([
      { text: '到账', ref: null },
      { text: '[1]', ref: 1 },
      { text: '，可退', ref: null },
      { text: '[2]', ref: 2 },
      { text: '。', ref: null },
    ])
    expect(splitByCitations('无角标')).toEqual([{ text: '无角标', ref: null }])
  })

  it('T-FE-303 角标 → 文档映射', () => {
    const docs = [{ chunk_id: 'kb-1-0', title: '售后政策', content: '退款 3~5 天' }]
    expect(citationDoc(1, docs).title).toBe('售后政策')
    expect(citationDoc(2, docs)).toBeNull() // 越界
    expect(citationDoc(1, undefined)).toBeNull()
  })
})

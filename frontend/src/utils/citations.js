/**
 * 引用角标工具（SP-FE-001）：回答中 `[n]` 角标 → 来源文档溯源。
 *
 * - `extractCitations(content)`：提取全部角标序号（去重）
 * - `splitByCitations(content)`：按角标切分 → `[{text, ref}]`（ref 为序号或 null），
 *   供 ChatMessage 渲染角标 hover 弹层
 * - `citationDoc(ref, docs)`：角标 [n] 对应检索文档 docs[n-1]（越界 → null）
 */
export function extractCitations(content) {
  return [...String(content).matchAll(/\[(\d+)\]/g)].map((m) => parseInt(m[1], 10))
}

export function splitByCitations(content) {
  const segments = []
  const re = /\[(\d+)\]/g
  let last = 0
  let m
  while ((m = re.exec(content)) !== null) {
    if (m.index > last) segments.push({ text: content.slice(last, m.index), ref: null })
    segments.push({ text: m[0], ref: parseInt(m[1], 10) })
    last = m.index + m[0].length
  }
  if (last < content.length) segments.push({ text: content.slice(last), ref: null })
  return segments
}

export function citationDoc(ref, docs) {
  if (!docs || ref < 1) return null
  return docs[ref - 1] || null
}

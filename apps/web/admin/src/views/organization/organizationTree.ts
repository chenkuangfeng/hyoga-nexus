import type { OrganizationNode } from '@nexus-web/core/api/enterprise-organizations'

/** 用迭代方式展开树，保留服务器顺序并构建可读路径；防止极深树或错误环路耗尽调用栈。 */
export function organizationRows(nodes: readonly OrganizationNode[]): Array<{ node: OrganizationNode; depth: number; path: string }> {
  const children = new Map<string | null, OrganizationNode[]>()
  for (const node of nodes) { const bucket = children.get(node.parent_id); if (bucket) bucket.push(node); else children.set(node.parent_id, [node]) }
  const pending = (children.get(null) || []).map(node => ({ node, depth: 0, path: node.name })).reverse()
  const result: Array<{ node: OrganizationNode; depth: number; path: string }> = [], seen = new Set<string>()
  while (pending.length) { const row = pending.pop()!; if (seen.has(row.node.id)) continue; seen.add(row.node.id); result.push(row); for (const node of [...(children.get(row.node.id) || [])].reverse()) pending.push({ node, depth: row.depth + 1, path: `${row.path} / ${node.name}` }) }
  return result
}
/** 当前节点及其全部子节点不可成为新父节点；迭代遍历同时防御循环数据。 */
export function organizationSubtree(nodes: readonly OrganizationNode[], root: string): Set<string> {
  const children = new Map<string, string[]>()
  for (const node of nodes) if (node.parent_id !== null) { const bucket = children.get(node.parent_id); if (bucket) bucket.push(node.id); else children.set(node.parent_id, [node.id]) }
  const pending = [root], result = new Set<string>()
  while (pending.length) { const next = pending.pop()!; if (result.has(next)) continue; result.add(next); for (const child of children.get(next) || []) pending.push(child) }
  return result
}

/** Shared user-facing tool text. Stable tool identifiers and model schemas remain unchanged. */
type Translate = (key: string) => string
type Exists = (key: string) => boolean

export function toolDisplayName(name: string, t: Translate, te: Exists): string {
  const key = `toolUi.tools.${name}.label`
  const legacy = `nexusAgent.tools.${name}.label`
  return te(key) ? t(key) : te(legacy) ? t(legacy) : name
}

export function toolDisplayDescription(tool: { name: string; description: string }, t: Translate, te: Exists): string {
  const key = `toolUi.tools.${tool.name}.desc`
  const legacy = `nexusAgent.tools.${tool.name}.desc`
  return te(key) ? t(key) : te(legacy) ? t(legacy) : tool.description
}

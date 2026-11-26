/** Backend fields mirror the server's validated deployment settings. */
import type { SandboxBackend } from '@nexus-web/core/api/nexus-sandboxes'

export interface ConfigField {
  key: string
  input: 'text' | 'number' | 'switch' | 'network' | 'tags'
  required?: boolean
  min?: number
  max?: number
  step?: number
}
export const backendNames: Record<SandboxBackend, string> = {
  local: 'Local', ssh: 'SSH', bwrap: 'Bubblewrap', docker: 'Docker', managed: 'HTTPS',
}
export const connectionFields: Record<SandboxBackend, ConfigField[]> = {
  local: [],
  docker: [{ key: 'image', input: 'text', required: true }],
  bwrap: [{ key: 'cgroup_root', input: 'text' }],
  ssh: [
    { key: 'ssh_host', input: 'text', required: true }, { key: 'ssh_user', input: 'text', required: true },
    { key: 'ssh_port', input: 'number', min: 1, max: 65535 },
    { key: 'ssh_identity_file', input: 'text', required: true },
    { key: 'ssh_known_hosts', input: 'text', required: true },
    { key: 'remote_profile', input: 'text', required: true }, { key: 'trusted_ssh', input: 'switch' },
  ],
  managed: [
    { key: 'endpoint', input: 'text', required: true }, { key: 'token_file', input: 'text', required: true },
    { key: 'remote_profile', input: 'text', required: true },
  ],
}
const memory: ConfigField = { key: 'memory_mb', input: 'number', min: 64, max: 16384 }
const cpu: ConfigField = { key: 'cpus', input: 'number', min: 0.1, max: 16, step: 0.1 }
const pids: ConfigField = { key: 'pids', input: 'number', min: 16, max: 4096 }
export function resourceFields(type: SandboxBackend, cgroup: boolean): ConfigField[] {
  return [
    ...(['docker', 'managed'].includes(type) || (type === 'bwrap' && cgroup) ? [cpu, pids] : []),
    ...(['docker', 'managed', 'bwrap'].includes(type) ? [memory] : []),
    { key: 'workspace_quota_mb', input: 'number', min: 1, max: 102400 },
    { key: 'exec_timeout_max_seconds', input: 'number', min: 1, max: 3600 },
    { key: 'skill_timeout_seconds', input: 'number', min: 1, max: 3600 },
    { key: 'skill_timeout_max_seconds', input: 'number', min: 1, max: 3600 },
  ]
}
export function advancedFields(type: SandboxBackend): ConfigField[] {
  return [
    ...(['docker', 'bwrap'].includes(type) ? [
      { key: 'network', input: 'network' }, { key: 'install_network', input: 'network' },
      { key: 'quota_mount', input: 'text' }, { key: 'quota_project_start', input: 'number', min: 1, max: 4000000000 },
      { key: 'quota_inodes', input: 'number', min: 100, max: 1000000 },
    ] as ConfigField[] : []),
    ...(type === 'docker' ? [
      { key: 'tmpfs_mb', input: 'number', min: 1, max: 4096 },
      { key: 'idle_seconds', input: 'number', min: 30, max: 86400 },
    ] as ConfigField[] : []),
    ...(['docker', 'bwrap', 'local'].includes(type) ? [
      { key: 'env_passthrough', input: 'tags' },
      { key: 'build_timeout_seconds', input: 'number', min: 10, max: 7200 },
      { key: 'env_max_mb', input: 'number', min: 16, max: 20480 },
    ] as ConfigField[] : []),
  ]
}

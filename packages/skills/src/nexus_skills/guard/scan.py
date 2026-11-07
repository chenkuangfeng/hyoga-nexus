"""Rule scanner for skill content (openspec 2026-11-07-skill-evolution, S1).

The scan reads SKILL.md and every resource file and reports findings: a rule, a severity, the file and line and a
short excerpt. It is one gate among several. A regex cannot tie a dynamic destination to a write or prove a script
safe, so a clean result is never a guarantee: runtime authorization, the approval flow and the sandbox still apply,
and a skill grants no permission whatever its scan says.

Severity and verdict:

- ``critical`` — a clear malicious primitive (pipe a download into a shell, wipe the home directory, fork bomb, plant
  an SSH key, read a private key). Any critical finding makes the verdict ``dangerous``.
- ``high`` — credential reads, persistence, executing decoded content, instructions aimed at the model. ``caution``.
- ``medium`` — network access, dynamic evaluation, shell invocation from a script. ``caution``.
- ``low`` — URLs in documentation. Findings that are all ``low`` leave the verdict ``safe``.

The scanner is versioned. A version scanned by an older scanner is reported as needing a rescan; rescanning only
adds the new result and never changes published content.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

#: Bump when a rule is added, removed or changes severity.
SCANNER_VERSION = 1
#: Findings kept per scan; later ones are dropped (the verdict still counts them).
MAX_FINDINGS = 50
_EXCERPT_CHARS = 120
_SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
_SCRIPT_SUFFIXES = ('.py', '.sh', '.bash', '.js', '.mjs', '.cjs', '.ts', '.rb', '.pl', '.ps1')


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    category: str
    pattern: re.Pattern[str]
    #: ``script`` rules apply to executable files only; ``text`` rules apply to documents (SKILL.md, markdown).
    scope: str
    description: str


def _r(rule_id: str, severity: str, category: str, pattern: str, scope: str, description: str) -> Rule:
    return Rule(rule_id, severity, category, re.compile(pattern, re.IGNORECASE), scope, description)


RULES: tuple[Rule, ...] = (
    # --- critical: clear malicious primitives -------------------------------------------------------------------------
    _r('pipe_to_shell', 'critical', 'remote_code', r'\b(?:curl|wget)\b[^\n|;]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b', 'script',
       'downloads content and pipes it into a shell'),
    _r('wipe_root_or_home', 'critical', 'destructive',
       r'\brm\s+-[a-z]*[rf][a-z]*\s+(?:--no-preserve-root\s+)?(?:/|~|\$HOME|"\$HOME")(?:\s|/?\*|$)', 'script',
       'recursively removes the root or home directory'),
    _r('fork_bomb', 'critical', 'destructive', r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', 'script', 'fork bomb'),
    _r('raw_disk_write', 'critical', 'destructive', r'\bdd\s+[^\n]*\bof=/dev/(?:sd|nvme|hd|vd|disk)|\bmkfs(?:\.\w+)?\s+/dev/',
       'script', 'writes to a raw disk device'),
    _r('plant_ssh_key', 'critical', 'persistence', r'authorized_keys', 'script', 'touches SSH authorized_keys'),
    _r('read_private_key', 'critical', 'credential_read',
       r'(?:~|\$HOME|/home/\w+|/root)/\.ssh/id_\w+|/etc/shadow\b|\.aws/credentials', 'script',
       'reads a private key or credential file'),
    # --- high -------------------------------------------------------------------------------------------------------
    _r('credential_env', 'high', 'credential_read',
       r'os\.environ|os\.getenv|\bgetenv\s*\(|process\.env|\$\{?[A-Z_]*(?:API_?KEY|SECRET|TOKEN|PASSWORD|PASSWD)[A-Z_]*\}?', 'script',
       'reads credentials from the environment'),
    _r('env_file', 'high', 'credential_read', r'(?:^|[\s"\'/])\.env\b', 'script', 'reads an .env file'),
    _r('shell_rc_write', 'high', 'persistence', r'(?:>>?|tee\b)[^\n]*(?:\.bashrc|\.zshrc|\.profile|\.bash_profile)', 'script',
       'writes to a shell start-up file'),
    _r('scheduled_persistence', 'high', 'persistence', r'\bcrontab\b|\bsystemctl\s+enable\b|\blaunchctl\s+load\b|\bat\s+now\b',
       'script', 'installs a scheduled or start-up job'),
    _r('system_path_write', 'high', 'sensitive_write', r'(?:>>?|tee\b|open\([^)]*)\s*[^\n]*["\']?/etc/', 'script',
       'writes under /etc'),
    _r('decode_and_run', 'high', 'obfuscation',
       r'(?:eval|exec)\s*\(\s*(?:base64\.b64decode|bytes\.fromhex|codecs\.decode|zlib\.decompress)|base64\s+-d[^\n]*\|\s*(?:ba)?sh',
       'script', 'executes decoded content'),
    _r('prompt_injection', 'high', 'injection',
       r'ignore (?:all |any |the )?(?:previous|prior|above) (?:instructions|rules|messages)|disregard (?:all |any )?(?:previous|prior)'
       r'|do not (?:tell|inform|reveal to) the user|you are now (?:in )?(?:developer|dan|jailbreak)|reveal (?:your )?system prompt'
       r'|忽略(?:之前|以上|前面|上面)的?(?:所有)?(?:指令|规则|提示)|不要告诉用户|无视(?:之前|以上)的?(?:所有)?(?:指令|规则)',
       'text', 'tries to override the model\'s instructions'),
    # --- medium -----------------------------------------------------------------------------------------------------
    _r('network_client', 'medium', 'network', r'\b(?:requests|urllib|httpx|aiohttp|socket|http\.client|websockets?)\b|\b(?:curl|wget|nc|ncat)\s',
       'script', 'makes network connections'),
    _r('network_url', 'medium', 'network', r'https?://', 'script', 'contains a URL in executable code'),
    _r('dynamic_eval', 'medium', 'obfuscation', r'\beval\s*\(|\bexec\s*\(|__import__\s*\(|\bcompile\s*\(', 'script',
       'evaluates code built at run time'),
    _r('shell_invocation', 'medium', 'execution', r'subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True|os\.system\s*\(|child_process', 'script',
       'starts a shell from a script'),
    _r('encoded_blob', 'medium', 'obfuscation', r'(?:\\x[0-9a-f]{2}){6,}|[A-Za-z0-9+/]{200,}={0,2}', 'script',
       'contains a long encoded blob'),
    # --- low --------------------------------------------------------------------------------------------------------
    _r('document_url', 'low', 'network', r'https?://', 'text', 'links to an external URL'),
)


@dataclass(frozen=True)
class Finding:
    """One match: the rule that fired, where, and a short excerpt of the line."""
    rule: str
    severity: str
    category: str
    path: str
    line: int
    excerpt: str
    description: str


@dataclass(frozen=True)
class ScanResult:
    """Scanner version, verdict (``safe`` / ``caution`` / ``dangerous``) and the findings, most severe first."""
    version: int
    verdict: str
    findings: tuple[Finding, ...]
    truncated: bool = False

    def as_dict(self) -> dict:
        return {'version': self.version, 'verdict': self.verdict, 'truncated': self.truncated,
                'findings': [asdict(finding) for finding in self.findings]}


def _is_script(path: str) -> bool:
    return path.lower().endswith(_SCRIPT_SUFFIXES) or path.startswith('scripts/')


def scan_files(files: dict[str, str]) -> ScanResult:
    """Scan ``files`` (relative path -> text; include ``SKILL.md``) and return the findings and verdict."""
    found: list[Finding] = []
    for path in sorted(files):
        scope = 'script' if _is_script(path) else 'text'
        for number, raw in enumerate(files[path].splitlines(), start=1):
            for rule in RULES:
                if rule.scope != scope or not rule.pattern.search(raw):
                    continue
                excerpt = raw.strip()
                if len(excerpt) > _EXCERPT_CHARS:
                    excerpt = excerpt[:_EXCERPT_CHARS] + '…'
                found.append(Finding(rule.id, rule.severity, rule.category, path, number, excerpt, rule.description))
    found.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], f.path, f.line, f.rule))
    severities = {f.severity for f in found}
    if 'critical' in severities:
        verdict = 'dangerous'
    elif severities & {'high', 'medium'}:
        verdict = 'caution'
    else:
        verdict = 'safe'
    return ScanResult(SCANNER_VERSION, verdict, tuple(found[:MAX_FINDINGS]), truncated=len(found) > MAX_FINDINGS)


def scan_skill(skill_md: str, files: dict[str, str]) -> ScanResult:
    """Scan a skill's SKILL.md together with its resource files."""
    return scan_files({'SKILL.md': skill_md, **files})
